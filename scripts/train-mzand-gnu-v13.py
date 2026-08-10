#!/usr/bin/env python3
import importlib.util, json, os
from pathlib import Path
import joblib

V7=Path(__file__).with_name('train-mzand-gnu-v7.py')
spec=importlib.util.spec_from_file_location('mzv7',V7); v7=importlib.util.module_from_spec(spec); spec.loader.exec_module(v7)
DATA=Path(os.environ.get('GNU_V13_BATCH_OUT','gnu-teacher-v13-refined.jsonl'))
MODEL=Path('mzand-gnu-v13.joblib'); REPORT=Path('mzand-gnu-v13-report.txt'); REPORT_JSON=Path('mzand-gnu-v13-report.json')
rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]

def rollout_weight(row):
    if row.get('teacherRolloutExecuted'): return 20.0
    return v7.base_weight(row)
v7.base_weight=rollout_weight
counts={s:sum(1 for r in rows if r.get('split')==s and len(r.get('hints') or [])>=2) for s in ('train','tune','dev')}
if min(counts.values())<100: raise SystemExit(f'insufficient split sizes: {counts}')
# Tune chooses architecture/blend. Dev is untouched until final evaluation.
trials=[]; best=None
for depth in (7,9,11):
    r,g=v7.train(rows,['train'],depth,20261300+depth)
    for alpha in (.50,.65,.80,1.0):
        met=v7.evaluate(r,g,alpha,rows,'tune'); k=v7.key(met)
        trials.append({'depth':depth,'alpha':alpha,'tune':{x:y for x,y in met.items() if x!='details'}})
        if best is None or k>best[0]: best=(k,depth,alpha)
_,depth,alpha=best
ranker,reg=v7.train(rows,['train','tune'],depth,20261331)
dev=v7.evaluate(ranker,reg,alpha,rows,'dev',True)
joblib.dump({'version':'mzand-gnu-v13','ranker':ranker,'equityRegressor':reg,'rankBlendAlpha':alpha,'depth':depth,'teacher':'GNU Backgammon true-rollout refined','xgLabelsUsed':False,'pristineDataUsed':False},MODEL)
refined=sum(1 for r in rows if r.get('teacherRolloutExecuted'))
report={'model':'mzand-gnu-v13','selectedBy':'tune only; dev untouched until final','splitCounts':counts,'rolloutRefinedRows':refined,'selectedDepth':depth,'rankBlendAlpha':alpha,'dev':{k:v for k,v in dev.items() if k!='details'},'devDetails':dev['details'],'devUsedForModelSelection':False,'pristineDataUsed':False,'xgLabelsUsed':False}
REPORT_JSON.write_text(json.dumps(report,indent=2)+'\n')
REPORT.write_text('\n'.join([
 'MODEL: mzand-gnu-v13','PHASE: GNU_TRUE_ROLLOUT_TOP1_REFINEMENT',f'ROLLOUT_REFINED_ROWS: {refined}',f'SELECTED_DEPTH: {depth}',f'RANK_BLEND_ALPHA: {alpha:.2f}',
 f"TRAIN_POSITION_SAMPLES: {counts['train']}",f"TUNE_POSITION_SAMPLES: {counts['tune']}",f"DEV_POSITION_SAMPLES: {counts['dev']}",
 f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",f"DEV_TOP2: {dev['top2']:.6f}",f"DEV_TOP3: {dev['top3']:.6f}",f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",f"DEV_HARD_SAMPLES: {dev['hardSamples']}",f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",
 'DEV_USED_FOR_MODEL_SELECTION: False','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
print(REPORT.read_text())
