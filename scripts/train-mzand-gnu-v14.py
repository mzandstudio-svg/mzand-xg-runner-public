#!/usr/bin/env python3
import importlib.util, json, os
from pathlib import Path
import joblib

V7=Path(__file__).with_name('train-mzand-gnu-v7.py')
spec=importlib.util.spec_from_file_location('mzv7',V7); v7=importlib.util.module_from_spec(spec); spec.loader.exec_module(v7)
DATA=Path(os.environ.get('GNU_V14_BATCH_OUT','gnu-teacher-v14-refined.jsonl'))
MODEL=Path('mzand-gnu-v14.joblib'); REPORT=Path('mzand-gnu-v14-report.txt'); REPORT_JSON=Path('mzand-gnu-v14-report.json')
rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]

_orig=v7.base_weight
def rollout_weight(row):
    if row.get('teacherRolloutExecuted'):
        trials=int(row.get('rolloutTrials') or 1296)
        return 32.0 if trials>=5184 else 24.0
    return _orig(row)
v7.base_weight=rollout_weight

counts={s:sum(1 for r in rows if r.get('split')==s and len(r.get('hints') or [])>=2) for s in ('train','tune','dev')}
if min(counts.values())<100: raise SystemExit(f'insufficient split sizes: {counts}')

# Tune only. The held-out dev split is opened exactly once after all selection is frozen.
trials=[]; best=None
for depth in (7,9,11,13):
    r,g=v7.train(rows,['train'],depth,20261400+depth)
    for alpha in (.35,.50,.65,.80,1.0):
        met=v7.evaluate(r,g,alpha,rows,'tune'); k=v7.key(met)
        trials.append({'depth':depth,'alpha':alpha,'tune':{x:y for x,y in met.items() if x!='details'}})
        if best is None or k>best[0]: best=(k,depth,alpha)
_,depth,alpha=best
ranker,reg=v7.train(rows,['train','tune'],depth,20261431)
dev=v7.evaluate(ranker,reg,alpha,rows,'dev',True)
joblib.dump({'version':'mzand-gnu-v14','ranker':ranker,'equityRegressor':reg,'rankBlendAlpha':alpha,'depth':depth,'teacher':'GNU Backgammon adaptive true-rollout refined','xgLabelsUsed':False,'pristineDataUsed':False},MODEL)
refined=sum(1 for r in rows if r.get('teacherRolloutExecuted'))
report={'model':'mzand-gnu-v14','selectedBy':'tune only; dev untouched until final','splitCounts':counts,'rolloutRefinedRows':refined,'selectedDepth':depth,'rankBlendAlpha':alpha,'trials':trials,'dev':{k:v for k,v in dev.items() if k!='details'},'devDetails':dev['details'],'devUsedForModelSelection':False,'pristineDataUsed':False,'xgLabelsUsed':False}
REPORT_JSON.write_text(json.dumps(report,indent=2)+'\n')
REPORT.write_text('\n'.join([
 'MODEL: mzand-gnu-v14','PHASE: GNU_ADAPTIVE_TRUE_ROLLOUT_TOP1_REFINEMENT',f'ROLLOUT_REFINED_ROWS: {refined}',f'SELECTED_DEPTH: {depth}',f'RANK_BLEND_ALPHA: {alpha:.2f}',
 f"TRAIN_POSITION_SAMPLES: {counts['train']}",f"TUNE_POSITION_SAMPLES: {counts['tune']}",f"DEV_POSITION_SAMPLES: {counts['dev']}",
 f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",f"DEV_TOP2: {dev['top2']:.6f}",f"DEV_TOP3: {dev['top3']:.6f}",f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",f"DEV_HARD_SAMPLES: {dev['hardSamples']}",f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",
 'DEV_USED_FOR_MODEL_SELECTION: False','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
print(REPORT.read_text())
