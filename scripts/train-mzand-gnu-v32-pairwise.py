#!/usr/bin/env python3
"""MZand v32: direct pairwise top-1 comparator + equity blend.

Uses only train/tune for fitting and model selection. Dev is opened exactly once
only after the blend is frozen. XG/pristine rows are rejected.
"""
from __future__ import annotations
import importlib.util, json, math, os, sys
from pathlib import Path
from typing import Dict, Sequence
import joblib
import numpy as np
from xgboost import XGBClassifier, XGBRegressor

HERE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('GNU_V32_BATCH_OUT','gnu-teacher-v32-scaled.jsonl'))
MODEL=Path(os.environ.get('MZAND_V32_MODEL_OUT','mzand-gnu-v32-pairwise.joblib'))
REPORT_TXT=Path(os.environ.get('MZAND_V32_REPORT_TXT','mzand-gnu-v32-pairwise-report.txt'))
REPORT_JSON=Path(os.environ.get('MZAND_V32_REPORT_JSON','mzand-gnu-v32-pairwise-report.json'))


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod; spec.loader.exec_module(mod); return mod
enc=load_module('mzand_afterstate_v32',HERE/'mzand-afterstate-v27.py')


def load_rows():
    rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    for i,r in enumerate(rows):
        if r.get('pristine') is not False: raise SystemExit(f'forbidden pristine row {i}')
        if r.get('xgLabel') not in (False,None) or r.get('xgLabelUsed') is True: raise SystemExit(f'forbidden XG row {i}')
        if r.get('teacherRolloutExecuted') and r.get('split')=='dev': raise SystemExit(f'forbidden dev rollout row {i}')
    return rows


def weight(r):
    if r.get('teacherRolloutExecuted'):
        return 20.0 if int(r.get('rolloutTrials') or 1296)<5184 else 28.0
    m=r.get('teacherMargin')
    if isinstance(m,(int,float)) and m<.012: return 8.0
    if r.get('hard') or (isinstance(m,(int,float)) and m<.03): return 5.0
    return 1.0


def pair_dataset(rows,splits):
    wanted=set(splits); X=[]; y=[]; w=[]; groups=0
    for r in rows:
        if r.get('split') not in wanted: continue
        hs=r.get('hints') or []
        if len(hs)<2: continue
        fs=[enc.afterstate_features(r,h) for h in hs]
        top=fs[0]; ww=weight(r)
        # Directly teach GNU top-1 against every available rival, plus reverse pair.
        for j in range(1,len(fs)):
            d=(top-fs[j]).astype(np.float32)
            X.append(d); y.append(1); w.append(ww)
            X.append(-d); y.append(0); w.append(ww)
        groups+=1
    if not X: raise RuntimeError('empty pair dataset')
    return np.stack(X),np.asarray(y,np.int8),np.asarray(w,np.float32),groups


def equity_dataset(rows,splits):
    wanted=set(splits); X=[]; y=[]; w=[]
    for r in rows:
        if r.get('split') not in wanted: continue
        hs=r.get('hints') or []; ww=weight(r)
        for h in hs:
            X.append(enc.afterstate_features(r,h)); y.append(float(h.get('equity',0))); w.append(ww)
    return np.stack(X),np.asarray(y,np.float32),np.asarray(w,np.float32)


def make_models(seed):
    cmp=XGBClassifier(objective='binary:logistic',eval_metric='logloss',n_estimators=1800,max_depth=9,
        learning_rate=.018,min_child_weight=3,subsample=.94,colsample_bytree=.94,reg_alpha=.03,reg_lambda=4.0,
        tree_method='hist',n_jobs=-1,random_state=seed)
    reg=XGBRegressor(objective='reg:squarederror',n_estimators=1800,max_depth=9,learning_rate=.018,
        min_child_weight=3,subsample=.94,colsample_bytree=.94,reg_alpha=.03,reg_lambda=4.0,
        tree_method='hist',n_jobs=-1,random_state=seed+1)
    return cmp,reg


def train(rows,splits,seed):
    X,y,w,g=pair_dataset(rows,splits); cmp,reg=make_models(seed); cmp.fit(X,y,sample_weight=w)
    Xe,ye,we=equity_dataset(rows,splits); reg.fit(Xe,ye,sample_weight=we)
    return cmp,reg,{'pairSamples':len(y),'positionGroups':g,'equitySamples':len(ye)}


def z(a):
    a=np.asarray(a,float); s=float(np.std(a)); return a-float(np.mean(a)) if s<1e-9 else (a-float(np.mean(a)))/s


def scores(cmp,reg,row,alpha):
    hs=row.get('hints') or []; F=np.stack([enc.afterstate_features(row,h) for h in hs]); n=len(hs)
    borda=np.zeros(n,float)
    diffs=[]; pairs=[]
    for i in range(n):
        for j in range(i+1,n): diffs.append(F[i]-F[j]); pairs.append((i,j))
    if diffs:
        ps=cmp.predict_proba(np.stack(diffs))[:,1]
        for p,(i,j) in zip(ps,pairs): borda[i]+=float(p); borda[j]+=1.0-float(p)
        borda/=max(1,n-1)
    eq=np.asarray(reg.predict(F),float)
    return alpha*z(borda)+(1-alpha)*z(eq),eq,borda


def evaluate(cmp,reg,alpha,rows,split,details=False):
    total=top1=top2=top3=hardn=hardt=0; losses=[]; sq=[]; ae=[]; out=[]; cand=0
    for r in rows:
        if r.get('split')!=split: continue
        hs=r.get('hints') or []
        if len(hs)<2: continue
        s,eq,b=scores(cmp,reg,r,alpha); p=int(np.argmax(s)); rank=int(hs[p].get('rank',999))
        best=float(hs[0].get('equity',0)); got=float(hs[p].get('equity',0)); loss=max(0.,best-got)
        tgt=np.asarray([float(h.get('equity',0)) for h in hs]); sq.extend(((eq-tgt)**2).tolist()); ae.extend(np.abs(eq-tgt).tolist()); cand+=len(hs)
        total+=1; top1+=rank==1; top2+=rank<=2; top3+=rank<=3; losses.append(loss)
        if r.get('hard'): hardn+=1; hardt+=rank==1
        if details: out.append({'gameIndex':r.get('gameIndex'),'turn':r.get('turn'),'dice':r.get('dice'),'hard':bool(r.get('hard')),'teacherMargin':r.get('teacherMargin'),'pickedRank':rank,'equityLoss':loss})
    a=np.asarray(losses,float)
    return {'samples':total,'strictTop1':top1/total,'top2':top2/total,'top3':top3/total,
        'meanEquityLoss':float(np.mean(a)),'p95EquityLoss':float(np.quantile(a,.95)),'hardSamples':hardn,
        'hardStrictTop1':hardt/hardn if hardn else None,'equityCandidateSamples':cand,
        'equityRMSE':math.sqrt(float(np.mean(sq))) if sq else None,'equityMAE':float(np.mean(ae)) if ae else None,'details':out}


def key(m): return (m['strictTop1'],-m['meanEquityLoss'],m['top2'],m['hardStrictTop1'] or 0.)


def main():
    rows=load_rows(); counts={s:sum(r.get('split')==s and len(r.get('hints') or [])>=2 for r in rows) for s in ('train','tune','dev')}
    if min(counts.values())<100: raise SystemExit(f'insufficient splits {counts}')
    roll=sum(bool(r.get('teacherRolloutExecuted')) for r in rows)
    # Train-only model; tune alone freezes blend. Dev remains unopened here.
    c0,r0,stat0=train(rows,['train'],20263201)
    trials=[]; best=None
    for a in (.40,.50,.60,.70,.80,.90,1.0):
        m=evaluate(c0,r0,a,rows,'tune'); compact={k:v for k,v in m.items() if k!='details'}
        trials.append({'pairwiseBlendAlpha':a,'tune':compact})
        if best is None or key(m)>best[0]: best=(key(m),a)
    alpha=best[1]
    # Frozen: refit on train+tune, then open dev exactly once.
    cmp,reg,trainstat=train(rows,['train','tune'],20263277)
    dev=evaluate(cmp,reg,alpha,rows,'dev',True); tune_after=evaluate(cmp,reg,alpha,rows,'tune')
    artifact={'version':'mzand-gnu-v32','architecture':'DIRECT_PAIRWISE_BORDA_PLUS_EQUITY','featureSchema':'mzand.afterstate.v27',
        'featureCount':enc.feature_count(),'pairwiseComparator':cmp,'equityRegressor':reg,'pairwiseBlendAlpha':alpha,
        'teacher':'GNU Backgammon','rolloutRefinedRows':roll,'devUsedForModelSelection':False,'devRowsMined':0,
        'xgLabelsUsed':False,'pristineDataUsed':False,'classifierUsedAsMoveClass':False}
    joblib.dump(artifact,MODEL)
    report={'model':'mzand-gnu-v32','architecture':artifact['architecture'],'selectedBy':'tune only; sealed dev opened after freeze',
        'splitCounts':counts,'rolloutRefinedRows':roll,'selectedAlpha':alpha,'trainStats':trainstat,'tuneTrials':trials,
        'tuneAfterRefit':{k:v for k,v in tune_after.items() if k!='details'},'dev':{k:v for k,v in dev.items() if k!='details'},
        'devDetails':dev['details'],'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False}
    REPORT_JSON.write_text(json.dumps(report,indent=2)+'\n')
    def f(x): return 'NA' if x is None else f'{x:.6f}'
    REPORT_TXT.write_text('\n'.join([
        'MODEL: mzand-gnu-v32','ARCHITECTURE: DIRECT_PAIRWISE_BORDA_PLUS_EQUITY',f'FEATURE_COUNT: {enc.feature_count()}',
        f'ROLLOUT_REFINED_ROWS: {roll}',f'PAIRWISE_BLEND_ALPHA: {alpha:.2f}',f'PAIR_TRAIN_SAMPLES: {trainstat["pairSamples"]}',
        f'TRAIN_POSITION_SAMPLES: {counts["train"]}',f'TUNE_POSITION_SAMPLES: {counts["tune"]}',f'DEV_POSITION_SAMPLES: {counts["dev"]}',
        f'DEV_STRICT_TOP1: {dev["strictTop1"]:.6f}',f'DEV_TOP2: {dev["top2"]:.6f}',f'DEV_TOP3: {dev["top3"]:.6f}',
        f'DEV_MEAN_EQUITY_LOSS: {dev["meanEquityLoss"]:.6f}',f'DEV_P95_EQUITY_LOSS: {dev["p95EquityLoss"]:.6f}',
        f'DEV_HARD_SAMPLES: {dev["hardSamples"]}',f'DEV_HARD_STRICT_TOP1: {f(dev["hardStrictTop1"])}',
        f'DEV_EQUITY_RMSE: {f(dev["equityRMSE"])}',f'DEV_EQUITY_MAE: {f(dev["equityMAE"])}',
        'DEV_USED_FOR_MODEL_SELECTION: False','DEV_ROWS_MINED: 0','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
    print(REPORT_TXT.read_text())

if __name__=='__main__': main()
