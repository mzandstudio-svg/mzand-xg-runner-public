#!/usr/bin/env python3
"""Build a GNU-only true-rollout queue from MZand Top-1 mistakes.

Strict guardrails:
- mine train/tune only; never mine dev
- no pristine data
- no XG labels
- this script only PRIORITIZES rollout work; it does not claim rollout was run
"""
import importlib.util
import json
import os
from pathlib import Path

import numpy as np

V7 = Path(__file__).with_name('train-mzand-gnu-v7.py')
spec = importlib.util.spec_from_file_location('mzv7', V7)
v7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v7)

DATA = Path(os.environ.get('GNU_V8_BATCH_OUT', 'gnu-teacher-v8.jsonl'))
QUEUE = Path(os.environ.get('GNU_V8_ROLLOUT_QUEUE', 'gnu-v8-top1-rollout-queue.jsonl'))
REPORT = Path('gnu-v8-top1-rollout-queue-report.txt')


def compact_moves(hint):
    return hint.get('moves') or []


def main():
    with DATA.open() as f:
        rows = [json.loads(line) for line in f if line.strip()]

    counts = {
        s: sum(1 for r in rows if r.get('split') == s and len(r.get('hints') or []) >= 2)
        for s in ('train', 'tune', 'dev')
    }
    if min(counts['train'], counts['tune']) < 100:
        raise SystemExit(f'insufficient train/tune rows for v8 mining: {counts}')

    # Train-only preliminary student. Tune chooses the blend. Dev is never evaluated here.
    ranker, reg = v7.train(rows, ['train'], 9, 20261001)
    alpha = max(
        (.50, .65, .80, 1.0),
        key=lambda a: v7.key(v7.evaluate(ranker, reg, a, rows, 'tune')),
    )

    queue = []
    eligible = wrong = rank2 = strong_wrong = near_tie = 0
    for row_index, row in enumerate(rows):
        split = row.get('split')
        if split not in ('train', 'tune'):
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        eligible += 1

        X = v7.candidate_matrix(row)
        rank_score = v7.zscore(ranker.predict(X))
        equity_score = v7.zscore(reg.predict(X))
        score = alpha * rank_score + (1.0 - alpha) * equity_score
        pick = int(np.argmax(score))
        picked_rank = int(hints[pick].get('rank', 999))
        if picked_rank == 1:
            continue

        wrong += 1
        if picked_rank == 2:
            rank2 += 1

        top_equity = float(hints[0].get('equity', 0.0))
        picked_equity = float(hints[pick].get('equity', 0.0))
        equity_loss = max(0.0, top_equity - picked_equity)
        teacher_margin = row.get('teacherMargin')
        margin = float(teacher_margin) if isinstance(teacher_margin, (int, float)) else None
        model_preference_gap = float(score[pick] - score[0])

        is_near_tie = margin is not None and margin <= 0.012
        is_strong_wrong = model_preference_gap >= 0.25
        near_tie += int(is_near_tie)
        strong_wrong += int(is_strong_wrong)

        # Top-1 priority: rank-2 mistakes first, then confident mistakes and close teacher calls.
        priority = 0.0
        priority += 50.0 if picked_rank == 2 else max(5.0, 30.0 - 3.0 * picked_rank)
        priority += min(30.0, max(0.0, model_preference_gap) * 20.0)
        priority += min(20.0, equity_loss * 200.0)
        if is_near_tie:
            priority += 25.0

        suggested_trials = 5184 if is_near_tie else 1296
        if is_near_tie and margin is not None and margin <= 0.005:
            suggested_trials = 10368

        queue.append({
            'queueVersion': 'gnu-v8-top1-errors',
            'teacher': 'GNU Backgammon 3-ply Huge/pruning bootstrap',
            'teacherRolloutExecuted': False,
            'pristine': False,
            'xgLabelUsed': False,
            'sourceSplit': split,
            'sourceRowIndex': row_index,
            'gameIndex': row.get('gameIndex'),
            'turn': row.get('turn'),
            'positionId': row.get('positionId'),
            'dice': row.get('dice'),
            'board': row.get('board'),
            'teacherMargin': margin,
            'teacherTopEquity': top_equity,
            'pickedEquity': picked_equity,
            'equityLoss': equity_loss,
            'pickedRank': picked_rank,
            'modelPreferenceGap': model_preference_gap,
            'priority': priority,
            'suggestedRolloutTrials': suggested_trials,
            'teacherBestMoves': compact_moves(hints[0]),
            'studentPickedMoves': compact_moves(hints[pick]),
            'candidateHints': hints,
        })

    queue.sort(key=lambda x: (-x['priority'], x['sourceSplit'], x['gameIndex'] or -1, x['turn'] or -1))
    QUEUE.write_text(''.join(json.dumps(x, separators=(',', ':')) + '\n' for x in queue))

    report_lines = [
        'QUEUE: gnu-v8-top1-errors',
        f"TRAIN_POSITION_SAMPLES: {counts['train']}",
        f"TUNE_POSITION_SAMPLES: {counts['tune']}",
        f"SEALED_DEV_POSITION_SAMPLES: {counts['dev']}",
        f'ELIGIBLE_TRAIN_TUNE_ROWS: {eligible}',
        f'TOP1_ERROR_ROWS: {wrong}',
        f'PICKED_RANK2_ROWS: {rank2}',
        f'STRONG_WRONG_ROWS: {strong_wrong}',
        f'NEAR_TIE_ERROR_ROWS: {near_tie}',
        f'ROLLOUT_QUEUE_ROWS: {len(queue)}',
        f'RANK_BLEND_ALPHA: {alpha:.2f}',
        'DEV_ROWS_MINED: 0',
        'TEACHER_ROLLOUT_EXECUTED: False',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
    ]
    REPORT.write_text('\n'.join(report_lines) + '\n')
    print(REPORT.read_text())


if __name__ == '__main__':
    main()
