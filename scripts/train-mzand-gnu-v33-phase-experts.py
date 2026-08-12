#!/usr/bin/env python3
"""GNU v33: phase-specialized afterstate rank/equity experts.

All model/alpha/expert-vs-global choices are made on train/tune only. Sealed dev
is evaluated exactly once after configuration freeze. XG/pristine rows are rejected.
"""
from __future__ import annotations
import importlib.util, json, os, sys
from pathlib import Path
import joblib, numpy as np

HERE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('GNU_V33_BATCH_OUT','gnu-teacher-v33-scaled.jsonl'))
MODEL=Path('mzand-gnu-v33-phase-experts.joblib')
REPORT=Path('mzand-gnu-v33-phase-experts-report.txt')
REPORT_JSON=Path('mzand-gnu-v33-phase-experts-report.json')

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); sys.modules[name]=m; s.loader.exec_module(m); return m
v27=load('v27_phase_base',HERE/'train-mzand-gnu-v27.py')
enc=v27.enc

def phase(row):
    b=row['board']; own=np.asarray(b['own']); opp=np.asarray(b['opp'])
    if int(b.get('barOwn',0))>0: return 'bar'
    own_out=np.where(own>0)[0]; opp_out=np.where(opp>0)[0]
    contact=bool(len(own_out) and len(opp_out) and int(np.max(own_out))>int(np.min(opp_out)))
    all_home=bool(np.sum(own[6:])==0 and int(b.get('barOwn',0))==0)
    if all_home: return 'bearoff'
    if not contact: return 'race'
    return 'contact'

def subset(rows,p): return [r for r in rows if phase(r)==p]

def eval_model(r,g,a,rows,split,p=None):
    use=[x for x in rows if (p is None or phase(x)==p)]
    return v27.evaluate(r,g,a,use,split)

def key(m): return v27.metric_key(m)

def train_fixed(rows,splits,seed): return v27.train(rows,splits,11,seed)

def choose_alpha(r,g,rows,p):
    best=None
    for a in (.20,.35,.50,.65,.80,1.0):
        m=eval_model(r,g,a,rows,'tune',p); k=key(m)
        if best is None or k>best[0]: best=(k,a,m)
    return best[1],best[2]

def score(r,g,a,row): return v27.score_row(r,g,a,row)[0]

def evaluate_bundle(bundle,rows,split):
    total=top1=top2=top3=hardn=hards=0; losses=[]; by={p:[0,0] for p in ('bar','bearoff','race','contact')}
    for row in rows:
        if row.get('split')!=split: continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        p=phase(row); spec=bundle[p]
        blend=score(spec['ranker'],spec['reg'],spec['alpha'],row)
        ix=int(np.argmax(blend)); rank=int(hints[ix].get('rank',999))
        te=float(hints[0].get('equity',0)); ge=float(hints[ix].get('equity',0)); loss=max(0.,te-ge)
        total+=1; top1+=rank==1; top2+=rank<=2; top3+=rank<=3; losses.append(loss); by[p][0]+=1; by[p][1]+=rank==1
        if row.get('hard'): hardn+=1; hards+=rank==1
    return {'samples':total,'strictTop1':top1/total,'top2':top2/total,'top3':top3/total,'meanEquityLoss':float(np.mean(losses)),'hardSamples':hardn,'hardStrictTop1':hards/hardn if hardn else None,'phaseTop1':{p:(v[1]/v[0] if v[0] else None) for p,v in by.items()},'phaseSamples':{p:v[0] for p,v in by.items()}}

def main():
    rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    for i,r in enumerate(rows):
        if r.get('pristine') is not False: raise SystemExit(f'forbidden pristine row {i}')
        if r.get('xgLabel') not in (False,None) or r.get('xgLabelUsed') is True: raise SystemExit(f'forbidden XG row {i}')
    counts={s:sum(r.get('split')==s and len(r.get('hints') or [])>=2 for r in rows) for s in ('train','tune','dev')}
    rollout=sum(bool(r.get('teacherRolloutExecuted')) for r in rows)
    if rollout!=2: raise SystemExit(f'expected 2 verified GNU rollout rows, got {rollout}')

    # Global baseline chosen only on tune.
    gr0,gg0=train_fixed(rows,['train'],3301); ga,gm=choose_alpha(gr0,gg0,rows,None)
    choices={}; tune_report={}
    phase_rows={p:subset(rows,p) for p in ('bar','bearoff','race','contact')}
    for j,p in enumerate(('bar','bearoff','race','contact')):
        tr=sum(r.get('split')=='train' and len(r.get('hints') or [])>=2 for r in phase_rows[p]); tu=sum(r.get('split')=='tune' and len(r.get('hints') or [])>=2 for r in phase_rows[p])
        if tr<250 or tu<75:
            choices[p]={'kind':'global','alpha':ga,'train':tr,'tune':tu}; continue
        er,eg=train_fixed(phase_rows[p],['train'],3310+j); ea,em=choose_alpha(er,eg,phase_rows[p],None)
        gpm=eval_model(gr0,gg0,ga,rows,'tune',p)
        use_expert=key(em)>key(gpm)
        choices[p]={'kind':'expert' if use_expert else 'global','alpha':ea if use_expert else ga,'train':tr,'tune':tu}
        tune_report[p]={'expert':em,'global':gpm,'selected':choices[p]['kind']}

    # Freeze choices. Refit global and selected experts on train+tune; only then open dev.
    gr,gg=train_fixed(rows,['train','tune'],3390)
    bundle={}
    for j,p in enumerate(('bar','bearoff','race','contact')):
        c=choices[p]
        if c['kind']=='expert':
            er,eg=train_fixed(phase_rows[p],['train','tune'],3400+j); bundle[p]={'ranker':er,'reg':eg,'alpha':c['alpha'],'kind':'expert'}
        else: bundle[p]={'ranker':gr,'reg':gg,'alpha':c['alpha'],'kind':'global'}
    dev=evaluate_bundle(bundle,rows,'dev')
    art={'version':'mzand-gnu-v33','architecture':'PHASE_SPECIALIZED_AFTERSTATE_RANK_EQUITY','featureCount':enc.feature_count(),'phaseExperts':bundle,'phaseChoices':choices,'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False,'rolloutRefinedRows':rollout}
    joblib.dump(art,MODEL)
    out={'model':'mzand-gnu-v33','counts':counts,'rolloutRefinedRows':rollout,'globalTuneAlpha':ga,'globalTune':gm,'phaseChoices':choices,'phaseTune':tune_report,'dev':dev,'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False}
    REPORT_JSON.write_text(json.dumps(out,indent=2)+'\n')
    lines=['MODEL: mzand-gnu-v33','ARCHITECTURE: PHASE_SPECIALIZED_AFTERSTATE_RANK_EQUITY',f'FEATURE_COUNT: {enc.feature_count()}',f'ROLLOUT_REFINED_ROWS: {rollout}',f'TRAIN_POSITION_SAMPLES: {counts["train"]}',f'TUNE_POSITION_SAMPLES: {counts["tune"]}',f'DEV_POSITION_SAMPLES: {counts["dev"]}',f'DEV_STRICT_TOP1: {dev["strictTop1"]:.6f}',f'DEV_TOP2: {dev["top2"]:.6f}',f'DEV_TOP3: {dev["top3"]:.6f}',f'DEV_MEAN_EQUITY_LOSS: {dev["meanEquityLoss"]:.6f}',f'DEV_HARD_SAMPLES: {dev["hardSamples"]}',f'DEV_HARD_STRICT_TOP1: {dev["hardStrictTop1"]:.6f}']
    for p in ('bar','bearoff','race','contact'):
        lines += [f'PHASE_{p.upper()}_CHOICE: {choices[p]["kind"]}',f'PHASE_{p.upper()}_DEV_SAMPLES: {dev["phaseSamples"][p]}',f'PHASE_{p.upper()}_DEV_TOP1: {dev["phaseTop1"][p] if dev["phaseTop1"][p] is not None else "NA"}']
    lines += ['DEV_USED_FOR_MODEL_SELECTION: False','DEV_ROWS_MINED: 0','PRISTINE_DATA_USED: False','XG_LABELS_USED: False']
    REPORT.write_text('\n'.join(lines)+'\n'); print(REPORT.read_text())
if __name__=='__main__': main()
