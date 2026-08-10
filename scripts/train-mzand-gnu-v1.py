#!/usr/bin/env python3
import json
import math
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier

DATA = Path(os.environ.get('GNU_BATCH_OUT', 'gnu-teacher-batch.jsonl'))
MODEL = Path(os.environ.get('MZAND_MODEL_OUT', 'mzand-gnu-v1.joblib'))
REPORT_JSON = Path('mzand-gnu-v1-report.json')
REPORT_TXT = Path('mzand-gnu-v1-report.txt')


def global_board_features(board):
    own = list(board['own'])
    opp = list(board['opp'])
    bar_own = float(board.get('barOwn', 0))
    bar_opp = float(board.get('barOpp', 0))
    off_own = float(board.get('offOwn', 0))
    off_opp = float(board.get('offOpp', 0))
    pip_own = sum((i + 1) * own[i] for i in range(24)) + 25 * bar_own
    pip_opp = sum((24 - i) * opp[i] for i in range(24)) + 25 * bar_opp
    made_own = sum(1 for x in own if x >= 2)
    made_opp = sum(1 for x in opp if x >= 2)
    blot_own = sum(1 for x in own if x == 1)
    blot_opp = sum(1 for x in opp if x == 1)
    adj_own = sum(1 for i in range(23) if own[i] >= 2 and own[i + 1] >= 2)
    adj_opp = sum(1 for i in range(23) if opp[i] >= 2 and opp[i + 1] >= 2)
    return [
        *own, *opp, bar_own, bar_opp, off_own, off_opp,
        pip_own / 200.0, pip_opp / 200.0, (pip_own - pip_opp) / 200.0,
        made_own / 12.0, made_opp / 12.0,
        blot_own / 15.0, blot_opp / 15.0,
        adj_own / 11.0, adj_opp / 11.0,
    ]


def apply_hint(board, hint):
    own = list(board['own'])
    opp = list(board['opp'])
    bar_own = int(board.get('barOwn', 0))
    bar_opp = int(board.get('barOpp', 0))
    off_own = int(board.get('offOwn', 0))
    hit_count = 0
    bearoff_count = 0
    reentry_count = 0
    total_advance = 0
    for m in hint.get('moves', []):
        kind = m.get('moveKind', 'point-to-point')
        fr = m.get('from')
        to = m.get('to')
        is_hit = bool(m.get('isHit', False))
        if kind == 'reenter':
            reentry_count += 1
            if bar_own > 0:
                bar_own -= 1
            if isinstance(to, (int, float)) and 1 <= int(to) <= 24:
                ti = int(to) - 1
                if is_hit and opp[ti] == 1:
                    opp[ti] = 0
                    bar_opp += 1
                    hit_count += 1
                own[ti] += 1
            if isinstance(to, (int, float)):
                total_advance += max(0, 25 - int(to))
        elif kind == 'bear-off':
            bearoff_count += 1
            if isinstance(fr, (int, float)) and 1 <= int(fr) <= 24:
                fi = int(fr) - 1
                if own[fi] > 0:
                    own[fi] -= 1
                    off_own += 1
                total_advance += int(fr)
        else:
            if isinstance(fr, (int, float)) and isinstance(to, (int, float)):
                fi, ti = int(fr) - 1, int(to) - 1
                if 0 <= fi < 24 and own[fi] > 0:
                    own[fi] -= 1
                if 0 <= ti < 24:
                    if is_hit and opp[ti] == 1:
                        opp[ti] = 0
                        bar_opp += 1
                        hit_count += 1
                    own[ti] += 1
                total_advance += max(0, int(fr) - int(to))
    return own, opp, bar_own, bar_opp, off_own, hit_count, bearoff_count, reentry_count, total_advance


def candidate_features(row, hint):
    board = row['board']
    dice = sorted([int(x) for x in row['dice']], reverse=True)
    base = global_board_features(board)
    base += [dice[0] / 6.0, dice[1] / 6.0, 1.0 if dice[0] == dice[1] else 0.0]

    move_features = []
    moves = list(hint.get('moves', []))[:4]
    for j in range(4):
        if j < len(moves):
            m = moves[j]
            fr = m.get('from')
            to = m.get('to')
            kind = m.get('moveKind', 'point-to-point')
            frv = float(fr) if isinstance(fr, (int, float)) else (25.0 if kind == 'reenter' else 0.0)
            tov = float(to) if isinstance(to, (int, float)) else (0.0 if kind == 'bear-off' else 0.0)
            move_features += [
                frv / 25.0,
                tov / 25.0,
                max(0.0, frv - tov) / 25.0,
                1.0 if kind == 'point-to-point' else 0.0,
                1.0 if kind == 'reenter' else 0.0,
                1.0 if kind == 'bear-off' else 0.0,
                1.0 if m.get('isHit') else 0.0,
            ]
        else:
            move_features += [0.0] * 7

    own2, opp2, bar_own2, bar_opp2, off_own2, hits, bearoffs, reentries, advance = apply_hint(board, hint)
    pip_own_after = sum((i + 1) * own2[i] for i in range(24)) + 25 * bar_own2
    pip_opp_after = sum((24 - i) * opp2[i] for i in range(24)) + 25 * bar_opp2
    made_after = sum(1 for x in own2 if x >= 2)
    blots_after = sum(1 for x in own2 if x == 1)
    opp_blots_after = sum(1 for x in opp2 if x == 1)
    cand = [
        len(moves) / 4.0,
        hits / 4.0,
        bearoffs / 4.0,
        reentries / 4.0,
        advance / 100.0,
        pip_own_after / 200.0,
        pip_opp_after / 200.0,
        (pip_own_after - pip_opp_after) / 200.0,
        made_after / 12.0,
        blots_after / 15.0,
        opp_blots_after / 15.0,
        off_own2 / 15.0,
        bar_opp2 / 15.0,
    ]
    return np.asarray(base + move_features + cand, dtype=np.float32)


def load_rows():
    rows = []
    with DATA.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_examples(rows, split):
    X, y, groups = [], [], []
    for sample_idx, row in enumerate(rows):
        if row.get('split') != split:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        gid = (int(row.get('gameIndex', -1)), int(row.get('turn', -1)))
        for hint in hints:
            X.append(candidate_features(row, hint))
            y.append(1 if int(hint.get('rank', 99)) == 1 else 0)
            groups.append((gid, hint))
    return np.stack(X), np.asarray(y, dtype=np.int8), groups


def evaluate(model, rows, split='dev'):
    total = strict = tie_ok = hard_total = hard_ok = 0
    eq_loss = []
    details = []
    for row in rows:
        if row.get('split') != split:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        feats = np.stack([candidate_features(row, h) for h in hints])
        scores = model.predict_proba(feats)[:, 1]
        pick = int(np.argmax(scores))
        top_eq = float(hints[0].get('equity', 0.0))
        picked_eq = float(hints[pick].get('equity', 0.0))
        loss = max(0.0, top_eq - picked_eq)
        total += 1
        strict += int(int(hints[pick].get('rank', 99)) == 1)
        tie_ok += int(loss <= 1e-4)
        hard = bool(row.get('hard'))
        if hard:
            hard_total += 1
            hard_ok += int(int(hints[pick].get('rank', 99)) == 1)
        eq_loss.append(loss)
        details.append({
            'gameIndex': row.get('gameIndex'),
            'turn': row.get('turn'),
            'dice': row.get('dice'),
            'teacherMargin': row.get('teacherMargin'),
            'hard': hard,
            'pickedRank': int(hints[pick].get('rank', 99)),
            'equityLoss': loss,
        })
    return {
        'samples': total,
        'strictTop1': strict / total if total else 0.0,
        'equityTieTop1': tie_ok / total if total else 0.0,
        'meanEquityLoss': float(np.mean(eq_loss)) if eq_loss else None,
        'p95EquityLoss': float(np.quantile(eq_loss, 0.95)) if eq_loss else None,
        'hardSamples': hard_total,
        'hardStrictTop1': hard_ok / hard_total if hard_total else None,
        'details': details,
    }


def main():
    rows = load_rows()
    train_x, train_y, _ = build_examples(rows, 'train')
    if train_x.shape[0] < 50:
        raise SystemExit(f'not enough training candidates: {train_x.shape[0]}')
    model = ExtraTreesClassifier(
        n_estimators=600,
        max_features='sqrt',
        class_weight='balanced',
        min_samples_leaf=1,
        random_state=20260810,
        n_jobs=-1,
    )
    model.fit(train_x, train_y)
    dev = evaluate(model, rows, 'dev')
    train = evaluate(model, rows, 'train')
    joblib.dump({'model': model, 'version': 'mzand-gnu-v1'}, MODEL)
    report = {
        'model': 'mzand-gnu-v1',
        'teacher': 'GNU Backgammon board-based',
        'metricScope': 'rerank within GNU-provided top-N candidates; not full candidate coverage',
        'pristineDataUsed': False,
        'teacherRankEquityUsedAsInputFeatures': False,
        'train': {k: v for k, v in train.items() if k != 'details'},
        'dev': {k: v for k, v in dev.items() if k != 'details'},
        'devDetails': dev['details'],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2) + '\n')
    REPORT_TXT.write_text('\n'.join([
        'MODEL: mzand-gnu-v1',
        'TEACHER: GNU Backgammon board-based',
        f"TRAIN_SAMPLES: {train['samples']}",
        f"TRAIN_STRICT_TOP1: {train['strictTop1']:.6f}",
        f"DEV_SAMPLES: {dev['samples']}",
        f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",
        f"DEV_EQUITY_TIE_TOP1: {dev['equityTieTop1']:.6f}",
        f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",
        f"DEV_HARD_SAMPLES: {dev['hardSamples']}",
        f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",
        'METRIC_SCOPE: GNU_TOPN_RERANK_ONLY_NOT_FULL_CANDIDATE_COVERAGE',
        'PRISTINE_DATA_USED: False',
        'GNU_RANK_EQUITY_AS_INPUT: False',
    ]) + '\n')
    print(REPORT_TXT.read_text())


if __name__ == '__main__':
    main()
