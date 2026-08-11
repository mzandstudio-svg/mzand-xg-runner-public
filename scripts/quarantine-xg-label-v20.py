#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--expected-xgid', required=True)
    ap.add_argument('--id', required=True)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--gnu-margin', type=float, required=True)
    args = ap.parse_args()

    data = json.loads(args.input.read_text(encoding='utf-8'))
    if data.get('xgid') != args.expected_xgid:
        raise SystemExit(f"XGID mismatch: got={data.get('xgid')} expected={args.expected_xgid}")

    candidates = data.get('candidates') or []
    if len(candidates) < 2:
        raise SystemExit(f'insufficient candidates: {len(candidates)}')

    rollout_candidates = [c for c in candidates if c.get('analysis_method') == 'Rollout']
    if not rollout_candidates:
        raise SystemExit('no completed rollout candidate provenance found in XG export')

    data['schema'] = 'mzand.xg.quarantine-label.v1'
    data['quarantine'] = {
        'id': args.id,
        'quarantined': True,
        'training_eligible': False,
        'split': 'xg_quarantine',
        'pristine': False,
        'sealed_dev': False,
        'xg_labels_used_for_training': False,
        'source': 'independent deterministic non-pristine position pool',
        'generator_seed': args.seed,
        'gnu_screening_margin': args.gnu_margin,
        'rollout_candidate_count': len(rollout_candidates),
        'candidate_count': len(candidates),
    }

    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    report = args.output.with_suffix('.report.txt')
    report.write_text('\n'.join([
        f'QUARANTINE_ID: {args.id}',
        f'XGID: {args.expected_xgid}',
        f'CANDIDATE_COUNT: {len(candidates)}',
        f'ROLLOUT_CANDIDATE_COUNT: {len(rollout_candidates)}',
        f'BEST_MOVE: {candidates[0].get("move")}',
        f'BEST_EQUITY: {candidates[0].get("equity")}',
        f'BEST_METHOD: {candidates[0].get("analysis_method")}',
        f'GNU_SCREENING_MARGIN: {args.gnu_margin:.6f}',
        'QUARANTINED: True',
        'TRAINING_ELIGIBLE: False',
        'SEALED_DEV_USED: False',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED_FOR_TRAINING: False',
    ]) + '\n', encoding='utf-8')
    print(report.read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()
