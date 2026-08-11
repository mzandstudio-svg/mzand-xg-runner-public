#!/usr/bin/env python3
"""GNU v19: restore v7 train/tune disagreement mining while preserving true-rollout rows.

No pristine data, no XG labels, and dev is never used for model selection.
The final dev evaluation happens only after tune-selected depth/blend are frozen.
"""
import importlib.util
import json
import os
from pathlib import Path

import joblib
import numpy as np

V7 = Path(__file__).with_name('train-mzand-gnu-v7.py')
spec = importlib.util.spec_from_file_location('mzv7', V7)
v7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v7)

DATA = Path(os.environ.get('GNU_V19_BATCH_OUT', 'gnu-teacher-v19-refined.jsonl'))
MODEL = Path(os.environ.get('MZAND_V19_MODEL_OUT', 'mzand-gnu-v19.joblib'))
REPORT_JSON = Path('mzand-gnu-v19-report.json')
REPORT_TXT = Path('mzand-gnu-v19-report.txt')

rows = [json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]

_orig_weight = v7.base_weight


def hybrid_weight(row):
    if row.get('teacherRolloutExecuted'):
        trials = int(row.get('rolloutTrials') or 1296)
        # Strong but bounded: rollout rows remain above mined-error weight (12),
        # without allowing two rows to dominate the entire corpus.
        return 24.0 if trials >= 5184 else 18.0
    return _orig_weight(row)


v7.base_weight = hybrid_weight


def compact(metric):
    return {k: v for k, v in metric.items() if k != 'details'}


def prediction_errors(ranker, regressor, alpha, wanted_splits):
    wanted = set(wanted_splits)
    out = []
    for source_row_index, row in enumerate(rows):
        split = row.get('split')
        if split not in wanted:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        X = v7.candidate_matrix(row)
        score = alpha * v7.zscore(ranker.predict(X)) + (1.0 - alpha) * v7.zscore(regressor.predict(X))
        pick = int(np.argmax(score))
        picked_rank = int(hints[pick].get('rank', 999))
        if picked_rank == 1:
            continue
        top_eq = float(hints[0].get('equity', 0.0))
        got_eq = float(hints[pick].get('equity', 0.0))
        out.append({
            'sourceRowIndex': source_row_index,
            'sourceSplit': split,
            'gameIndex': row.get('gameIndex'),
            'turn': row.get('turn'),
            'positionId': row.get('positionId'),
            'dice': row.get('dice'),
            'teacherMargin': row.get('teacherMargin'),
            'hard': bool(row.get('hard')),
            'pickedRank': picked_rank,
            'equityLoss': max(0.0, top_eq - got_eq),
            'pristine': False,
            'xgLabelUsed': False,
            'devUsed': False,
        })
    return out


def main():
    counts = {
        s: sum(1 for r in rows if r.get('split') == s and len(r.get('hints') or []) >= 2)
        for s in ('train', 'tune', 'dev')
    }
    if min(counts.values()) < 100:
        raise SystemExit(f'insufficient split sizes {counts}')

    rollout_refined = sum(bool(r.get('teacherRolloutExecuted')) for r in rows)
    if rollout_refined != 2:
        raise SystemExit(f'expected exactly 2 verified rollout-refined rows, got {rollout_refined}')
    if any(r.get('teacherRolloutExecuted') and r.get('split') == 'dev' for r in rows):
        raise SystemExit('dev rollout refinement is forbidden')

    # Reproduce the proven v7 mining structure: preliminary train-only model,
    # blend selected on tune, then mine only train/tune disagreements + low margins.
    p_rank, p_reg = v7.train(rows, ['train'], 8, 20261901)
    preliminary_alpha = max(
        (.50, .65, .80, 1.0),
        key=lambda a: v7.key(v7.evaluate(p_rank, p_reg, a, rows, 'tune')),
    )
    mined, mining = v7.preliminary_disagreement(rows, p_rank, p_reg, preliminary_alpha)
    if not mined:
        raise SystemExit('v19 disagreement miner produced zero rows')

    trials = []
    best = None
    for depth in (7, 9, 11):
        ranker, regressor = v7.train(rows, ['train'], depth, 20261920 + depth, mined)
        for alpha in (.50, .65, .80, 1.0):
            tune = v7.evaluate(ranker, regressor, alpha, rows, 'tune')
            k = v7.key(tune)
            trials.append({'depth': depth, 'alpha': alpha, 'tune': compact(tune)})
            if best is None or k > best[0]:
                best = (k, depth, alpha)

    _, depth, alpha = best

    # Freeze tune-selected hyperparameters, then fit train+tune and open dev once.
    final_ranker, final_regressor = v7.train(rows, ['train', 'tune'], depth, 20261960, mined)
    dev = v7.evaluate(final_ranker, final_regressor, alpha, rows, 'dev', True)
    tune_after_refit = v7.evaluate(final_ranker, final_regressor, alpha, rows, 'tune')
    train_tune_errors = prediction_errors(final_ranker, final_regressor, alpha, ('train', 'tune'))

    joblib.dump({
        'version': 'mzand-gnu-v19',
        'ranker': final_ranker,
        'equityRegressor': final_regressor,
        'rankBlendAlpha': alpha,
        'depth': depth,
        'teacher': 'GNU Backgammon 3-ply Huge/pruning + verified true-rollout refinements',
        'rolloutRefinedRows': rollout_refined,
        'disagreementMinedRows': mining['minedRows'],
        'xgLabelsUsed': False,
        'pristineDataUsed': False,
    }, MODEL)

    report = {
        'model': 'mzand-gnu-v19',
        'phase': 'GNU_TRUE_ROLLOUT_PLUS_V7_DISAGREEMENT_MINING',
        'selectedBy': 'tune only; dev untouched until final',
        'splitCounts': counts,
        'rolloutRefinedRows': rollout_refined,
        'preliminaryAlpha': preliminary_alpha,
        'mining': mining,
        'selectedDepth': depth,
        'rankBlendAlpha': alpha,
        'trials': trials,
        'tuneAfterRefit': compact(tune_after_refit),
        'dev': compact(dev),
        'devDetails': dev['details'],
        # Future rollout queue source: train/tune only, never dev.
        'trainTunePredictionErrors': train_tune_errors,
        'devUsedForModelSelection': False,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2) + '\n')

    REPORT_TXT.write_text('\n'.join([
        'MODEL: mzand-gnu-v19',
        'PHASE: GNU_TRUE_ROLLOUT_PLUS_V7_DISAGREEMENT_MINING',
        f'ROLLOUT_REFINED_ROWS: {rollout_refined}',
        f"MINED_ROWS: {mining['minedRows']}",
        f"MINED_DISAGREEMENT_ROWS: {mining['disagreementRows']}",
        f"MINED_LOW_MARGIN_ROWS: {mining['lowMarginRows']}",
        f'PRELIMINARY_ALPHA: {preliminary_alpha:.2f}',
        f'SELECTED_DEPTH: {depth}',
        f'RANK_BLEND_ALPHA: {alpha:.2f}',
        f"TRAIN_POSITION_SAMPLES: {counts['train']}",
        f"TUNE_POSITION_SAMPLES: {counts['tune']}",
        f"DEV_POSITION_SAMPLES: {counts['dev']}",
        f"TRAIN_TUNE_TOP1_ERRORS_EXPORTED: {len(train_tune_errors)}",
        f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",
        f"DEV_TOP2: {dev['top2']:.6f}",
        f"DEV_TOP3: {dev['top3']:.6f}",
        f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",
        f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",
        f"DEV_HARD_SAMPLES: {dev['hardSamples']}",
        f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'DEV_ROWS_MINED: 0',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
    ]) + '\n')
    print(REPORT_TXT.read_text())


if __name__ == '__main__':
    main()
