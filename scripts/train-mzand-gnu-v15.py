#!/usr/bin/env python3
import importlib.util,json,os
from pathlib import Path
import joblib
V7=Path(__file__).with_name('train-mzand-gnu-v7.py')
spec=importlib.util.spec_from_file_location('mzv7',V7); v7=importlib.util.module_from_spec(spec); spec.loader.exec_module(v7)
DATA=Path(os.environ.get('GNU_V15_BATCH_OUT','gnu-teacher-v15-refined.jsonl'))
rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
_orig=v7.base_weight
def w(row):
    if row.get('teacherRolloutExecuted'):
        trials=int(row.get('rolloutTrials') or 1296); margin=float(row.get('teacherMargin') or 0.0)
        base=48.0 if trials>=5184 else 32.0
        if margin<0.012: base*=1.5
        return base
    return _orig(row)
v7.base_weight=w
counts={s:sum(1 for r in rows if r.get('split')==s and len(r.get('hints') or [])>=2) for s in ('train','tune','dev')}
if min(counts.values())<100: raise SystemExit(f'insufficient split sizes {counts}')
tr=[]; best=None
for depth in (7,9,11,13):
    r,g=v7.train(rows,['train'],depth,20261500+depth)
    for a in (.35,.50,.65,.80,1.0):
        met=v7.evaluate(r,g,a,rows,'tune'); k=v7.key(met); tr.append({'depth':depth,'alpha':a,'tune':{x:y for x,y in met.items() if x!='details'}})
        if best is None or k>best[0]: best=(k,depth,a)
_,depth,alpha=best
r,g=v7.train(rows,['train','tune'],depth,20261531); dev=v7.evaluate(r,g,alpha,rows,'dev',True)
joblib.dump({'version':'mzand-gnu-v15','ranker':r,'equityRegressor':g,'rankBlendAlpha':alpha,'depth':depth,'teacher':'GNU true rollout disagreement refined','xgLabelsUsed':False,'pristineDataUsed':False},'mzand-gnu-v15.joblib')
report={'model':'mzand-gnu-v15','selectedBy':'tune only; dev untouched until final','splitCounts':counts,'rolloutRefinedRows':sum(bool(x.get('teacherRolloutExecuted')) for x in rows),'selectedDepth':depth,'rankBlendAlpha':alpha,'trials':tr,'dev':{k:v for k,v in dev.items() if k!='details'},'devDetails':dev['details'],'devUsedForModelSelection':False,'pristineDataUsed':False,'xgLabelsUsed':False}
Path('mzand-gnu-v15-report.json').write_text(json.dumps(report,indent=2)+'\n')
Path('mzand-gnu-v15-report.txt').write_text('\n'.join(['MODEL: mzand-gnu-v15','PHASE: GNU_TRUE_ROLLOUT_ACTUAL_TOP1_DISAGREEMENTS',f"ROLLOUT_REFINED_ROWS: {report['rolloutRefinedRows']}",f'SELECTED_DEPTH: {depth}',f'RANK_BLEND_ALPHA: {alpha:.2f}',f"TRAIN_POSITION_SAMPLES: {counts['train']}",f"TUNE_POSITION_SAMPLES: {counts['tune']}",f"DEV_POSITION_SAMPLES: {counts['dev']}",f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",f"DEV_TOP2: {dev['top2']:.6f}",f"DEV_TOP3: {dev['top3']:.6f}",f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",f"DEV_HARD_SAMPLES: {dev['hardSamples']}",f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",'DEV_USED_FOR_MODEL_SELECTION: False','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
print(Path('mzand-gnu-v15-report.txt').read_text())
