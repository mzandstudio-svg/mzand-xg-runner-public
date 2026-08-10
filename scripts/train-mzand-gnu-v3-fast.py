#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import joblib

spec = importlib.util.spec_from_file_location('mzv2', Path(__file__).with_name('train-mzand-gnu-v2.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

rows = m.load_rows()
counts = {s: sum(1 for r in rows if r.get('split') == s) for s in ('train','tune','dev')}
if min(counts.values()) < 500:
    raise SystemExit(f'insufficient v3 split sizes: {counts}')

x, y, w = m.make_candidate_dataset(rows, ['train','tune'])
model = m.XGBRegressor(
    n_estimators=1100, max_depth=6, learning_rate=0.035,
    min_child_weight=3, subsample=0.90, colsample_bytree=0.90,
    reg_alpha=0.01, reg_lambda=2.0, objective='reg:squarederror',
    tree_method='hist', n_jobs=-1, random_state=20260810,
)
model.fit(x, y, sample_weight=w)
train = m.evaluate(model, rows, 'train')
tune = m.evaluate(model, rows, 'tune')
dev = m.evaluate(model, rows, 'dev')
joblib.dump({'model': model, 'version': 'mzand-gnu-v3-fast', 'architecture': 'xgb-d6-frozen-from-v2-tune'}, 'mzand-gnu-v3-fast.joblib')
report = {
  'model':'mzand-gnu-v3-fast',
  'architecture':'xgb-d6-frozen-from-v2-tune',
  'architectureSelectedWithoutV3Dev': True,
  'splitUnit':'whole game',
  'splitCounts': counts,
  'pristineDataUsed': False,
  'xgLabelsUsed': False,
  'metricScope':'rerank within GNU-provided top-N candidates; not full legal candidate coverage',
  'train': {k:v for k,v in train.items() if k!='details'},
  'tune': {k:v for k,v in tune.items() if k!='details'},
  'dev': {k:v for k,v in dev.items() if k!='details'},
  'devDetails': dev['details'],
}
Path('mzand-gnu-v3-fast-report.json').write_text(json.dumps(report,indent=2)+'\n')
Path('mzand-gnu-v3-fast-report.txt').write_text('\n'.join([
  'MODEL: mzand-gnu-v3-fast',
  'ARCHITECTURE: xgb-d6-frozen-from-v2-tune',
  'ARCHITECTURE_SELECTED_WITH_V3_DEV: False',
  f"TRAIN_POSITION_SAMPLES: {counts['train']}",
  f"TUNE_POSITION_SAMPLES: {counts['tune']}",
  f"DEV_POSITION_SAMPLES: {counts['dev']}",
  f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",
  f"DEV_TOP2: {dev['top2']:.6f}",
  f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",
  f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",
  f"DEV_HARD_SAMPLES: {dev['hardSamples']}",
  f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",
  'METRIC_SCOPE: GNU_TOPN_RERANK_ONLY_NOT_FULL_LEGAL_CANDIDATE_COVERAGE',
  'PRISTINE_DATA_USED: False',
  'XG_LABELS_USED: False',
])+'\n')
print(Path('mzand-gnu-v3-fast-report.txt').read_text())
