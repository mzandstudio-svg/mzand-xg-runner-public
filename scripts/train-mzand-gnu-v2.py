#!/usr/bin/env python3
import json
import math
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from xgboost import XGBRegressor

DATA = Path(os.environ.get('GNU_BATCH_OUT', 'gnu-teacher-batch-v2.jsonl'))
MODEL = Path(os.environ.get('MZAND_MODEL_OUT', 'mzand-gnu-v2.joblib'))
REPORT_JSON = Path('mzand-gnu-v2-report.json')
REPORT_TXT = Path('mzand-gnu-v2-report.txt')


def longest_prime(values):
    best = cur = 0
    for v in values:
        if v >= 2:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def board_derived(own, opp, bar_own, bar_opp, off_own, off_opp):
    own = np.asarray(own, dtype=np.float32)
    opp = np.asarray(opp, dtype=np.float32)
    pip_own = sum((i + 1) * float(own[i]) for i in range(24)) + 25.0 * bar_own
    pip_opp = sum((24 - i) * float(opp[i]) for i in range(24)) + 25.0 * bar_opp
    made_own = int(np.sum(own >= 2))
    made_opp = int(np.sum(opp >= 2))
    blots_own = int(np.sum(own == 1))
    blots_opp = int(np.sum(opp == 1))
    home_made_own = int(np.sum(own[:6] >= 2))
    home_made_opp = int(np.sum(opp[18:] >= 2))
    home_checkers_own = float(np.sum(own[:6]))
    home_checkers_opp = float(np.sum(opp[18:]))
    anchors_own = int(np.sum(own[18:] >= 2))
    anchors_opp = int(np.sum(opp[:6] >= 2))
    prime_own = longest_prime(own)
    prime_opp = longest_prime(opp)
    own_idx = np.where(own > 0)[0]
    opp_idx = np.where(opp > 0)[0]
    contact = 0.0
    if len(own_idx) and len(opp_idx):
        contact = 1.0 if int(np.max(own_idx)) > int(np.min(opp_idx)) else 0.0
    return np.asarray([
        pip_own / 200.0,
        pip_opp / 200.0,
        (pip_own - pip_opp) / 200.0,
        made_own / 12.0,
        made_opp / 12.0,
        blots_own / 15.0,
        blots_opp / 15.0,
        home_made_own / 6.0,
        home_made_opp / 6.0,
        home_checkers_own / 15.0,
        home_checkers_opp / 15.0,
        anchors_own / 6.0,
        anchors_opp / 6.0,
        prime_own / 6.0,
        prime_opp / 6.0,
        bar_own / 15.0,
        bar_opp / 15.0,
        off_own / 15.0,
        off_opp / 15.0,
        contact,
    ], dtype=np.float32)


def apply_hint(board, hint):
    own = np.asarray(board['own'], dtype=np.float32).copy()
    opp = np.asarray(board['opp'], dtype=np.float32).copy()
    bar_own = float(board.get('barOwn', 0))
    bar_opp = float(board.get('barOpp', 0))
    off_own = float(board.get('offOwn', 0))
    off_opp = float(board.get('offOpp', 0))
    hits = bearoffs = reentries = 0
    total_advance = 0.0
    for move in hint.get('moves', []):
        kind = move.get('moveKind', 'point-to-point')
        fr = move.get('from')
        to = move.get('to')
        is_hit = bool(move.get('isHit', False))
        if kind == 'reenter':
            reentries += 1
            if bar_own > 0:
                bar_own -= 1
            if isinstance(to, (int, float)) and 1 <= int(to) <= 24:
                ti = int(to) - 1
                if is_hit and opp[ti] == 1:
                    opp[ti] = 0
                    bar_opp += 1
                    hits += 1
                own[ti] += 1
                total_advance += 25 - int(to)
        elif kind == 'bear-off':
            bearoffs += 1
            if isinstance(fr, (int, float)) and 1 <= int(fr) <= 24:
                fi = int(fr) - 1
                if own[fi] > 0:
                    own[fi] -= 1
                    off_own += 1
                total_advance += int(fr)
        else:
            if isinstance(fr, (int, float)) and isinstance(to, (int, float)):
                fi = int(fr) - 1
                ti = int(to) - 1
                if 0 <= fi < 24 and own[fi] > 0:
                    own[fi] -= 1
                if 0 <= ti < 24:
                    if is_hit and opp[ti] == 1:
                        opp[ti] = 0
                        bar_opp += 1
                        hits += 1
                    own[ti] += 1
                total_advance += max(0, int(fr) - int(to))
    return own, opp, bar_own, bar_opp, off_own, off_opp, hits, bearoffs, reentries, total_advance


def candidate_features(row, hint):
    board = row['board']
    own = np.asarray(board['own'], dtype=np.float32)
    opp = np.asarray(board['opp'], dtype=np.float32)
    bar_own = float(board.get('barOwn', 0))
    bar_opp = float(board.get('barOpp', 0))
    off_own = float(board.get('offOwn', 0))
    off_opp = float(board.get('offOpp', 0))
    own2, opp2, bar_own2, bar_opp2, off_own2, off_opp2, hits, bearoffs, reentries, advance = apply_hint(board, hint)
    dice = sorted([int(x) for x in row['dice']], reverse=True)

    seq = []
    moves = list(hint.get('moves', []))[:4]
    for j in range(4):
        if j >= len(moves):
            seq.extend([0.0] * 7)
            continue
        move = moves[j]
        kind = move.get('moveKind', 'point-to-point')
        fr = float(move.get('from')) if isinstance(move.get('from'), (int, float)) else 0.0
        to = float(move.get('to')) if isinstance(move.get('to'), (int, float)) else 0.0
        seq.extend([
            fr / 24.0,
            to / 24.0,
            (fr - to) / 24.0,
            1.0 if kind == 'point-to-point' else 0.0,
            1.0 if kind == 'reenter' else 0.0,
            1.0 if kind == 'bear-off' else 0.0,
            1.0 if move.get('isHit') else 0.0,
        ])

    return np.concatenate([
        own / 5.0,
        opp / 5.0,
        np.asarray([bar_own / 5.0, bar_opp / 5.0, off_own / 15.0, off_opp / 15.0], dtype=np.float32),
        board_derived(own, opp, bar_own, bar_opp, off_own, off_opp),
        own2 / 5.0,
        opp2 / 5.0,
        np.asarray([bar_own2 / 5.0, bar_opp2 / 5.0, off_own2 / 15.0, off_opp2 / 15.0], dtype=np.float32),
        board_derived(own2, opp2, bar_own2, bar_opp2, off_own2, off_opp2),
        np.asarray([
            dice[0] / 6.0,
            dice[1] / 6.0,
            1.0 if dice[0] == dice[1] else 0.0,
            len(moves) / 4.0,
            hits / 4.0,
            bearoffs / 4.0,
            reentries / 4.0,
            advance / 24.0,
        ], dtype=np.float32),
        np.asarray(seq, dtype=np.float32),
    ]).astype(np.float32)


def load_rows():
    with DATA.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def make_candidate_dataset(rows, splits):
    x, y, weights = [], [], []
    wanted = set(splits)
    for row in rows:
        if row.get('split') not in wanted:
            continue
        hard_weight = 3.0 if row.get('hard') else 1.0
        for hint in row.get('hints') or []:
            x.append(candidate_features(row, hint))
            y.append(float(hint.get('equity', 0.0)))
            weights.append(hard_weight)
    if not x:
        raise RuntimeError(f'No candidate rows for {sorted(wanted)}')
    return np.stack(x), np.asarray(y, dtype=np.float32), np.asarray(weights, dtype=np.float32)


def evaluate(model, rows, split):
    total = strict = tie_ok = top2 = 0
    hard_total = hard_strict = 0
    losses = []
    details = []
    for row in rows:
        if row.get('split') != split:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        feats = np.stack([candidate_features(row, h) for h in hints])
        pred = np.asarray(model.predict(feats), dtype=float)
        pick = int(np.argmax(pred))
        rank = int(hints[pick].get('rank', 99))
        top_eq = float(hints[0].get('equity', 0.0))
        picked_eq = float(hints[pick].get('equity', 0.0))
        loss = max(0.0, top_eq - picked_eq)
        total += 1
        strict += int(rank == 1)
        top2 += int(rank <= 2)
        tie_ok += int(loss <= 1e-4)
        if row.get('hard'):
            hard_total += 1
            hard_strict += int(rank == 1)
        losses.append(loss)
        details.append({
            'gameIndex': row.get('gameIndex'),
            'turn': row.get('turn'),
            'dice': row.get('dice'),
            'teacherMargin': row.get('teacherMargin'),
            'hard': bool(row.get('hard')),
            'pickedRank': rank,
            'equityLoss': loss,
        })
    arr = np.asarray(losses, dtype=float)
    return {
        'samples': total,
        'strictTop1': strict / total if total else 0.0,
        'equityTieTop1': tie_ok / total if total else 0.0,
        'top2': top2 / total if total else 0.0,
        'meanEquityLoss': float(np.mean(arr)) if total else None,
        'p95EquityLoss': float(np.quantile(arr, 0.95)) if total else None,
        'hardSamples': hard_total,
        'hardStrictTop1': hard_strict / hard_total if hard_total else None,
        'details': details,
    }


def model_specs():
    return [
        ('xgb-d6', lambda: XGBRegressor(
            n_estimators=1100, max_depth=6, learning_rate=0.035,
            min_child_weight=3, subsample=0.90, colsample_bytree=0.90,
            reg_alpha=0.01, reg_lambda=2.0, objective='reg:squarederror',
            tree_method='hist', n_jobs=-1, random_state=20260810,
        )),
        ('xgb-d8', lambda: XGBRegressor(
            n_estimators=1250, max_depth=8, learning_rate=0.025,
            min_child_weight=4, subsample=0.90, colsample_bytree=0.85,
            reg_alpha=0.02, reg_lambda=3.0, objective='reg:squarederror',
            tree_method='hist', n_jobs=-1, random_state=20260811,
        )),
        ('extra-trees', lambda: ExtraTreesRegressor(
            n_estimators=1000, max_features=0.80, min_samples_leaf=1,
            n_jobs=-1, random_state=20260812,
        )),
        ('hist-gbr', lambda: HistGradientBoostingRegressor(
            max_iter=600, learning_rate=0.04, max_leaf_nodes=63,
            l2_regularization=1.5, min_samples_leaf=12,
            random_state=20260813,
        )),
    ]


def metric_key(m):
    return (m['strictTop1'], -m['meanEquityLoss'], m['top2'])


def main():
    rows = load_rows()
    split_counts = {s: sum(1 for r in rows if r.get('split') == s) for s in ('train', 'tune', 'dev')}
    if min(split_counts.values()) < 100:
        raise SystemExit(f'Insufficient independent split sizes: {split_counts}')

    train_x, train_y, train_w = make_candidate_dataset(rows, ['train'])
    trials = []
    best_name = None
    best_factory = None
    best_tune = None
    for name, factory in model_specs():
        model = factory()
        model.fit(train_x, train_y, sample_weight=train_w)
        tune = evaluate(model, rows, 'tune')
        trials.append({'name': name, 'tune': {k: v for k, v in tune.items() if k != 'details'}})
        if best_tune is None or metric_key(tune) > metric_key(best_tune):
            best_name, best_factory, best_tune = name, factory, tune

    final_x, final_y, final_w = make_candidate_dataset(rows, ['train', 'tune'])
    final_model = best_factory()
    final_model.fit(final_x, final_y, sample_weight=final_w)

    train_metric = evaluate(final_model, rows, 'train')
    tune_metric = evaluate(final_model, rows, 'tune')
    dev_metric = evaluate(final_model, rows, 'dev')
    joblib.dump({'model': final_model, 'version': 'mzand-gnu-v2', 'selectedModel': best_name}, MODEL)

    report = {
        'model': 'mzand-gnu-v2',
        'teacher': 'GNU Backgammon board-based',
        'selectedBy': 'tune only; dev untouched until final selection',
        'selectedModel': best_name,
        'splitUnit': 'whole game',
        'splitCounts': split_counts,
        'hardPositionWeight': 3.0,
        'metricScope': 'rerank within GNU-provided top-N candidates; not full legal candidate coverage',
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
        'gnuRankEquityUsedAsInputFeatures': False,
        'trials': trials,
        'train': {k: v for k, v in train_metric.items() if k != 'details'},
        'tuneAfterRefit': {k: v for k, v in tune_metric.items() if k != 'details'},
        'dev': {k: v for k, v in dev_metric.items() if k != 'details'},
        'devDetails': dev_metric['details'],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2) + '\n')
    REPORT_TXT.write_text('\n'.join([
        'MODEL: mzand-gnu-v2',
        f'SELECTED_MODEL: {best_name}',
        'SELECTION_SPLIT: TUNE_ONLY',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        f"TRAIN_POSITION_SAMPLES: {split_counts['train']}",
        f"TUNE_POSITION_SAMPLES: {split_counts['tune']}",
        f"DEV_POSITION_SAMPLES: {split_counts['dev']}",
        f"TRAIN_STRICT_TOP1: {train_metric['strictTop1']:.6f}",
        f"TUNE_STRICT_TOP1_AFTER_REFIT: {tune_metric['strictTop1']:.6f}",
        f"DEV_STRICT_TOP1: {dev_metric['strictTop1']:.6f}",
        f"DEV_TOP2: {dev_metric['top2']:.6f}",
        f"DEV_EQUITY_TIE_TOP1: {dev_metric['equityTieTop1']:.6f}",
        f"DEV_MEAN_EQUITY_LOSS: {dev_metric['meanEquityLoss']:.6f}",
        f"DEV_P95_EQUITY_LOSS: {dev_metric['p95EquityLoss']:.6f}",
        f"DEV_HARD_SAMPLES: {dev_metric['hardSamples']}",
        f"DEV_HARD_STRICT_TOP1: {dev_metric['hardStrictTop1'] if dev_metric['hardStrictTop1'] is not None else 'NA'}",
        'HARD_POSITION_WEIGHT: 3.0',
        'METRIC_SCOPE: GNU_TOPN_RERANK_ONLY_NOT_FULL_LEGAL_CANDIDATE_COVERAGE',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
        'GNU_RANK_EQUITY_AS_INPUT: False',
    ]) + '\n')
    print(REPORT_TXT.read_text())


if __name__ == '__main__':
    main()
