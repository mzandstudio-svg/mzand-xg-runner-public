#!/usr/bin/env python3
"""GNU-only pairwise tournament ranker for MZand v19.

Strictly uses train/tune for fitting and model selection. Dev is evaluated once
on the frozen tune-selected blend. No XG or pristine labels are accepted.
"""
import importlib.util, json, os
from pathlib import Path
import joblib
import numpy as np
from xgboost import XGBClassifier, XGBRanker

BASE=Path(__file__).with_name('train-mzand-gnu-v2.py')
spec=importlib.util.spec_from_file_location('mzv2',BASE); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
DATA=Path(os.environ.get('GNU_V19_BATCH_OUT','gnu-teacher-v19.jsonl'))


def rows_load():
    rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    for r in rows:
        if r.get('pristine') is not False or r.get('xgLabel') not in (False,None):
            raise SystemExit('forbidden pristine/XG row in GNU v19 corpus')
    return rows

def feats(r,h): return m.candidate_features(r,h)

def z(a):
    a=np.asarray(a,float); s=float(np.std(a)); return a-float(np.mean(a)) if s<1e-9 else (a-float(np.mean(a)))/s

def weight(r):
    margin=r.get('teacherMargin')
    if isinstance(margin,(int,float)) and margin<.012: return 8.0
    if r.get('hard') or (isinstance(margin,(int,float)) and margin<.03): return 4.0
    return 1.0

def rank_data(rows,splits):
    wanted=set(splits); X=[]; y=[]; q=[]; gw=[]; gid=0
    for r in rows:
        if r.get('split') not in wanted: continue
        hs=r.get('hints') or []
        if len(hs)<2: continue
        n=len(hs); gw.append(weight(r))
        for h in hs:
            X.append(feats(r,h)); rank=int(h.get('rank',n)); y.append(float((n-rank+1)+(6 if rank==1 else 0))); q.append(gid)
        gid+=1
    return np.stack(X),np.asarray(y,np.float32),np.asarray(q,np.int32),np.asarray(gw,np.float32)

def pair_data(rows,splits):
    wanted=set(splits); X=[]; y=[]; w=[]
    for r in rows:
        if r.get('split') not in wanted: continue
        hs=r.get('hints') or []
        if len(hs)<2: continue
        F=[feats(r,h) for h in hs]; pairs=[]
        # Focus supervision on best-vs-rest plus adjacent ordering, bounded for scale.
        for j in range(1,min(len(hs),8)): pairs.append((0,j))
        for j in range(min(len(hs)-1,7)): pairs.append((j,j+1))
        seen=set()
        for a,b in pairs:
            if (a,b) in seen: continue
            seen.add((a,b)); d=F[a]-F[b]; ww=weight(r)
            X.append(d); y.append(1); w.append(ww)
            X.append(-d); y.append(0); w.append(ww)
    return np.stack(X),np.asarray(y,np.int8),np.asarray(w,np.float32)

def train(rows,splits,depth,seed):
    X,y,q,gw=rank_data(rows,splits)
    ranker=XGBRanker(objective='rank:pairwise',eval_metric='ndcg@1',n_estimators=1800,max_depth=depth,learning_rate=.022,min_child_weight=3,subsample=.94,colsample_bytree=.94,reg_alpha=.02,reg_lambda=3.5,tree_method='hist',n_jobs=-1,random_state=seed)
    ranker.fit(X,y,qid=q,sample_weight=gw)
    P,py,pw=pair_data(rows,splits)
    pair=XGBClassifier(objective='binary:logistic',eval_metric='logloss',n_estimators=1400,max_depth=max(5,depth-2),learning_rate=.025,min_child_weight=3,subsample=.94,colsample_bytree=.94,reg_alpha=.02,reg_lambda=3.5,tree_method='hist',n_jobs=-1,random_state=seed+1)
    pair.fit(P,py,sample_weight=pw)
    return ranker,pair

def pair_scores(pair,F):
    n=len(F); s=np.zeros(n,float)
    for i in range(n):
        if n==1: break
        diffs=np.stack([F[i]-F[j] for j in range(n) if j!=i])
        s[i]=float(np.mean(pair.predict_proba(diffs)[:,1]))
    return s

def evaluate(ranker,pair,alpha,rows,split,details=False):
    total=strict=top2=top3=hardn=hards=0; losses=[]; out=[]
    for r in rows:
        if r.get('split')!=split: continue
        hs=r.get('hints') or []
        if len(hs)<2: continue
        F=np.stack([feats(r,h) for h in hs]); rs=z(ranker.predict(F)); ps=z(pair_scores(pair,F)); score=alpha*ps+(1-alpha)*rs
        p=int(np.argmax(score)); rank=int(hs[p].get('rank',999)); top=float(hs[0].get('equity',0)); got=float(hs[p].get('equity',0)); loss=max(0.,top-got)
        total+=1; strict+=rank==1; top2+=rank<=2; top3+=rank<=3; losses.append(loss)
        if r.get('hard'): hardn+=1; hards+=rank==1
        if details: out.append({'gameIndex':r.get('gameIndex'),'turn':r.get('turn'),'dice':r.get('dice'),'teacherMargin':r.get('teacherMargin'),'hard':bool(r.get('hard')),'pickedRank':rank,'equityLoss':loss})
    a=np.asarray(losses,float)
    return {'samples':total,'strictTop1':strict/total if total else 0.,'top2':top2/total if total else 0.,'top3':top3/total if total else 0.,'meanEquityLoss':float(np.mean(a)) if total else None,'p95EquityLoss':float(np.quantile(a,.95)) if total else None,'hardSamples':hardn,'hardStrictTop1':hards/hardn if hardn else None,'details':out}
def key(x): return (x['strictTop1'],-x['meanEquityLoss'],x['top2'],x['hardStrictTop1'] or 0.)

def main():
    rows=rows_load(); counts={s:sum(1 for r in rows if r.get('split')==s and len(r.get('hints') or [])>=2) for s in ('train','tune','dev')}
    if min(counts.values())<500: raise SystemExit(f'insufficient split sizes {counts}')
    trials=[]; best=None
    for depth in (7,9,11):
        ranker,pair=train(rows,['train'],depth,20261900+depth)
        for alpha in (.35,.50,.65,.80):
            met=evaluate(ranker,pair,alpha,rows,'tune'); trials.append({'depth':depth,'pairBlendAlpha':alpha,'tune':{k:v for k,v in met.items() if k!='details'}})
            k=key(met)
            if best is None or k>best[0]: best=(k,depth,alpha)
    _,depth,alpha=best
    ranker,pair=train(rows,['train','tune'],depth,20261931)
    dev=evaluate(ranker,pair,alpha,rows,'dev',True)
    joblib.dump({'version':'mzand-gnu-v19-pairwise','ranker':ranker,'pairwise':pair,'pairBlendAlpha':alpha,'depth':depth,'teacher':'GNU Backgammon 3-ply Huge/pruning','devUsedForModelSelection':False,'xgLabelsUsed':False,'pristineDataUsed':False},'mzand-gnu-v19.joblib')
    rep={'model':'mzand-gnu-v19-pairwise','selectedBy':'tune only; dev untouched until frozen evaluation','splitCounts':counts,'selectedDepth':depth,'pairBlendAlpha':alpha,'trials':trials,'dev':{k:v for k,v in dev.items() if k!='details'},'devDetails':dev['details'],'devUsedForModelSelection':False,'pristineDataUsed':False,'xgLabelsUsed':False}
    Path('mzand-gnu-v19-report.json').write_text(json.dumps(rep,indent=2)+'\n')
    Path('mzand-gnu-v19-report.txt').write_text('\n'.join(['MODEL: mzand-gnu-v19-pairwise',f'SELECTED_DEPTH: {depth}',f'PAIR_BLEND_ALPHA: {alpha:.2f}',f"TRAIN_POSITION_SAMPLES: {counts['train']}",f"TUNE_POSITION_SAMPLES: {counts['tune']}",f"DEV_POSITION_SAMPLES: {counts['dev']}",f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",f"DEV_TOP2: {dev['top2']:.6f}",f"DEV_TOP3: {dev['top3']:.6f}",f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",f"DEV_HARD_SAMPLES: {dev['hardSamples']}",f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",'DEV_USED_FOR_MODEL_SELECTION: False','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
    print(Path('mzand-gnu-v19-report.txt').read_text())
if __name__=='__main__': main()
