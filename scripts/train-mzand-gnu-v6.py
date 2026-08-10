#!/usr/bin/env python3
"""MZand v6 bootstrap trainer.

This is an evidence-producing bridge from the v5 ranker to the later neural
rollout-distillation engine. It deliberately uses only GNU labels and never
uses the held-out dev split for model selection.
"""
import importlib.util
import json
import os
from pathlib import Path

import joblib
import numpy as np
from xgboost import XGBRanker, XGBRegressor

BASE = Path(__file__).with_name('train-mzand-gnu-v2.py')
spec = importlib.util.spec_from_file_location('mzv2', BASE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

DATA = Path(os.environ.get('GNU_V6_BATCH_OUT', 'gnu-teacher-v6.jsonl'))
MODEL = Path(os.environ.get('MZAND_V6_MODEL_OUT', 'mzand-gnu-v6.joblib'))
REPORT_JSON = Path('mzand-gnu-v6-report.json')
REPORT_TXT = Path('mzand-gnu-v6-report.txt')


def load_rows():
    with DATA.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def group_weight(row):
    margin = row.get('teacherMargin')
    if row.get('rolloutCandidate'):
        return 8.0
    if row.get('hard') or (isinstance(margin, (int, float)) and margin < 0.03):
        return 5.0
    return 1.0


def make_rank_dataset(rows, splits):
    wanted = set(splits)
    X, y, qid, weights = [], [], [], []
    group = 0
    for row in rows:
        if row.get('split') not in wanted:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        n = len(hints)
        weights.append(group_weight(row))
        for hint in hints:
            X.append(m.candidate_features(row, hint))
            rank = int(hint.get('rank', n))
            y.append(float(max(0, n - rank + 1)))
            qid.append(group)
        group += 1
    if not X:
        raise RuntimeError('empty v6 rank dataset')
    return (
        np.stack(X),
        np.asarray(y, dtype=np.float32),
        np.asarray(qid, dtype=np.int32),
        np.asarray(weights, dtype=np.float32),
    )


def make_equity_dataset(rows, splits):
    wanted = set(splits)
    X, y, weights = [], [], []
    for row in rows:
        if row.get('split') not in wanted:
            continue
        w = group_weight(row)
        for hint in row.get('hints') or []:
            X.append(m.candidate_features(row, hint))
            y.append(float(hint.get('equity', 0.0)))
            weights.append(w)
    if not X:
        raise RuntimeError('empty v6 equity dataset')
    return np.stack(X), np.asarray(y, dtype=np.float32), np.asarray(weights, dtype=np.float32)


def zscore(values):
    values = np.asarray(values, dtype=float)
    if len(values) <= 1:
        return np.zeros_like(values)
    sd = float(np.std(values))
    if sd < 1e-9:
        return values - float(np.mean(values))
    return (values - float(np.mean(values))) / sd


def evaluate(ranker, regressor, alpha, rows, split, keep_details=False):
    total = strict = top2 = top3 = hard_total = hard_strict = 0
    losses, details = [], []
    for row in rows:
        if row.get('split') != split:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        feats = np.stack([m.candidate_features(row, h) for h in hints])
        rank_score = zscore(ranker.predict(feats))
        equity_score = zscore(regressor.predict(feats))
        score = alpha * rank_score + (1.0 - alpha) * equity_score
        pick = int(np.argmax(score))
        picked_rank = int(hints[pick].get('rank', 999))
        top_equity = float(hints[0].get('equity', 0.0))
        picked_equity = float(hints[pick].get('equity', 0.0))
        loss = max(0.0, top_equity - picked_equity)
        total += 1
        strict += int(picked_rank == 1)
        top2 += int(picked_rank <= 2)
        top3 += int(picked_rank <= 3)
        losses.append(loss)
        if row.get('hard'):
            hard_total += 1
            hard_strict += int(picked_rank == 1)
        if keep_details:
            details.append({
                'gameIndex': row.get('gameIndex'),
                'turn': row.get('turn'),
                'dice': row.get('dice'),
                'teacherMargin': row.get('teacherMargin'),
                'rolloutCandidate': bool(row.get('rolloutCandidate')),
                'hard': bool(row.get('hard')),
                'pickedRank': picked_rank,
                'equityLoss': loss,
            })
    arr = np.asarray(losses, dtype=float)
    return {
        'samples': total,
        'strictTop1': strict / total if total else 0.0,
        'top2': top2 / total if total else 0.0,
        'top3': top3 / total if total else 0.0,
        'meanEquityLoss': float(np.mean(arr)) if total else None,
        'p95EquityLoss': float(np.quantile(arr, 0.95)) if total else None,
        'hardSamples': hard_total,
        'hardStrictTop1': hard_strict / hard_total if hard_total else None,
        'details': details,
    }


def ranker_factory(seed):
    return XGBRanker(
        objective='rank:pairwise', eval_metric='ndcg@1',
        n_estimators=1400, max_depth=8, learning_rate=0.025,
        min_child_weight=4, subsample=0.92, colsample_bytree=0.92,
        reg_alpha=0.02, reg_lambda=3.0, tree_method='hist',
        n_jobs=-1, random_state=seed,
    )


def regressor_factory(seed):
    return XGBRegressor(
        objective='reg:squarederror', n_estimators=1400,
        max_depth=8, learning_rate=0.025, min_child_weight=4,
        subsample=0.92, colsample_bytree=0.92,
        reg_alpha=0.02, reg_lambda=3.0, tree_method='hist',
        n_jobs=-1, random_state=seed,
    )


def metric_key(metrics):
    return (
        metrics['strictTop1'],
        -metrics['meanEquityLoss'],
        metrics['top2'],
        metrics['hardStrictTop1'] or 0.0,
    )


def train_pair(rows, splits, seed):
    Xr, yr, qid, gw = make_rank_dataset(rows, splits)
    ranker = ranker_factory(seed)
    ranker.fit(Xr, yr, qid=qid, sample_weight=gw)
    Xe, ye, ew = make_equity_dataset(rows, splits)
    regressor = regressor_factory(seed + 1)
    regressor.fit(Xe, ye, sample_weight=ew)
    return ranker, regressor


def main():
    rows = load_rows()
    counts = {s: sum(1 for r in rows if r.get('split') == s and len(r.get('hints') or []) >= 2)
              for s in ('train', 'tune', 'dev')}
    if min(counts.values()) < 100:
        raise SystemExit(f'insufficient independent v6 split sizes: {counts}')

    ranker, regressor = train_pair(rows, ['train'], 20260821)
    trials = []
    best = None
    for alpha in (0.25, 0.50, 0.65, 0.80, 1.00):
        tune = evaluate(ranker, regressor, alpha, rows, 'tune')
        compact = {k: v for k, v in tune.items() if k != 'details'}
        trials.append({'rankBlendAlpha': alpha, 'tune': compact})
        key = metric_key(tune)
        if best is None or key > best[0]:
            best = (key, alpha)
    best_alpha = best[1]

    final_ranker, final_regressor = train_pair(rows, ['train', 'tune'], 20260823)
    dev = evaluate(final_ranker, final_regressor, best_alpha, rows, 'dev', keep_details=True)
    train = evaluate(final_ranker, final_regressor, best_alpha, rows, 'train')
    tune = evaluate(final_ranker, final_regressor, best_alpha, rows, 'tune')

    joblib.dump({
        'version': 'mzand-gnu-v6-bootstrap',
        'ranker': final_ranker,
        'equityRegressor': final_regressor,
        'rankBlendAlpha': best_alpha,
        'teacher': 'GNU Backgammon 3-ply Huge/pruning',
        'candidateScope': 'GNU Huge-filter candidates, up to configured maxHints',
    }, MODEL)

    report = {
        'model': 'mzand-gnu-v6-bootstrap',
        'phase': 'bootstrap before true-rollout neural distillation',
        'teacher': 'GNU Backgammon 3-ply Huge/pruning',
        'teacherRolloutExecuted': False,
        'selectedBy': 'tune only; dev untouched until final refit/evaluation',
        'rankBlendAlpha': best_alpha,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
        'devUsedForModelSelection': False,
        'metricScope': 'rerank within GNU Huge-filter returned candidates; not exhaustive legal move coverage yet',
        'splitCounts': counts,
        'trials': trials,
        'train': {k: v for k, v in train.items() if k != 'details'},
        'tuneAfterRefit': {k: v for k, v in tune.items() if k != 'details'},
        'dev': {k: v for k, v in dev.items() if k != 'details'},
        'devDetails': dev['details'],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2) + '\n')
    REPORT_TXT.write_text('\n'.join([
        'MODEL: mzand-gnu-v6-bootstrap',
        'PHASE: 3PLY_HUGE_BOOTSTRAP_BEFORE_TRUE_ROLLOUT',
        f'RANK_BLEND_ALPHA: {best_alpha:.2f}',
        f"TRAIN_POSITION_SAMPLES: {counts['train']}",
        f"TUNE_POSITION_SAMPLES: {counts['tune']}",
        f"DEV_POSITION_SAMPLES: {counts['dev']}",
        f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",
        f"DEV_TOP2: {dev['top2']:.6f}",
        f"DEV_TOP3: {dev['top3']:.6f}",
        f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",
        f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",
        f"DEV_HARD_SAMPLES: {dev['hardSamples']}",
        f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",
        'TEACHER_ROLLOUT_EXECUTED: False',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
    ]) + '\n')
    print(REPORT_TXT.read_text())


if __name__ == '__main__':
    main()
