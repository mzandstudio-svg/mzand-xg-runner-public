#!/usr/bin/env python3
"""GNU v34: hard-disagreement residual ranker on top of frozen v33 predictions.

Selection uses train/tune only. Dev is evaluated once after beta is frozen.
XG/pristine rows are rejected and dev is never mined.
"""
from __future__ import annotations
import importlib.util, json, os, sys
from pathlib import Path
import joblib, numpy as np
from xgboost import XGBRanker

HERE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('GNU_V34_BATCH_OUT','gnu-teacher-v34-scaled.jsonl'))
V33_MODEL=Path(os.environ.get('GNU_V34_V33_MODEL','v33/mzand-gnu-v33-phase-experts.joblib'))
REPORT=Path('mzand-gnu-v34-hard-residual-report.txt')
REPORT_JSON=Path('mzand-gnu-v34-hard-residual-report.json')
MODEL=Path('mzand-gnu-v34-hard-residual.joblib')

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); sys.modules[name]=m; s.loader.exec_module(m); return m
v27=load('v27_v34',HERE/'train-mzand-gnu-v27.py'); enc=v27.enc
v33=load('v33_v34',HERE/'train-mzand-gnu-v33-phase-experts.py')

def base_scores(art,row):
    p=v33.phase(row); spec=art['phaseExperts'][p]
    b,eq,rs=v27.score_row(spec['ranker'],spec['reg'],float(spec['alpha']),row)
    return np.asarray(b,float),np.asarray(eq,float),np.asarray(rs,float)

def candidate_features(art,row):
    hints=row.get('hints') or []
    b,eq,rs=base_scores(art,row)
    bz=v27.zscore(b); ez=v27.zscore(eq); rz=v27.zscore(rs)
    out=[]
    for i,h in enumerate(hints):
        out.append(np.concatenate([enc.afterstate_features(row,h),np.asarray([bz[i],ez[i],rz[i]],np.float32)]))
    return np.stack(out)

def mined_flag(art,row):
    hints=row.get('hints') or []
    if len(hints)<2: return False
    b,_,_=base_scores(art,row); ix=int(np.argmax(b)); wrong=int(hints[ix].get('rank',999))!=1
    m=row.get('teacherMargin'); low=isinstance(m,(int,float)) and m<0.03
    return bool(wrong or low or row.get('hard'))

def dataset(art,rows,splits):
    wanted=set(splits); X=[]; y=[]; q=[]; gw=[]; gid=0; mined=0; wrong=0
    for row in rows:
        if row.get('split') not in wanted: continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        feats=candidate_features(art,row); n=len(hints); eqs=[float(h.get('equity',0)) for h in hints]; lo=min(eqs)
        b,_,_=base_scores(art,row); iswrong=int(hints[int(np.argmax(b))].get('rank',999))!=1
        hard=mined_flag(art,row); mined+=int(hard); wrong+=int(iswrong)
        w=max(v27.base_weight(row),16.0 if hard else 0.0); gw.append(w)
        for f,h,eq in zip(feats,hints,eqs):
            rank=int(h.get('rank',n)); gap=min(24,max(0,int(round((eq-lo)*60.0))))
            X.append(f); y.append(float((n-rank+1)+(10 if rank==1 else 0)+gap)); q.append(gid)
        gid+=1
    return np.stack(X),np.asarray(y,np.float32),np.asarray(q,np.int32),np.asarray(gw,np.float32),{'groups':gid,'minedRows':mined,'baseWrongRows':wrong}

def train(art,rows,splits,seed):
    X,y,q,w,stats=dataset(art,rows,splits)
    r=XGBRanker(objective='rank:pairwise',eval_metric='ndcg@1',n_estimators=2200,max_depth=8,learning_rate=.015,min_child_weight=3,subsample=.95,colsample_bytree=.95,reg_alpha=.03,reg_lambda=4.0,tree_method='hist',n_jobs=-1,random_state=seed)
    r.fit(X,y,qid=q,sample_weight=w); return r,stats

def evaluate(art,residual,beta,rows,split):
    total=t1=t2=t3=hardn=hardt=0; losses=[]
    for row in rows:
        if row.get('split')!=split: continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        b,_,_=base_scores(art,row); rr=np.asarray(residual.predict(candidate_features(art,row)),float)
        s=(1-beta)*v27.zscore(b)+beta*v27.zscore(rr); ix=int(np.argmax(s)); rank=int(hints[ix].get('rank',999))
        top=float(hints[0].get('equity',0)); got=float(hints[ix].get('equity',0)); losses.append(max(0.,top-got))
        total+=1; t1+=rank==1; t2+=rank<=2; t3+=rank<=3
        if row.get('hard'): hardn+=1; hardt+=rank==1
    return {'samples':total,'strictTop1':t1/total,'top2':t2/total,'top3':t3/total,'meanEquityLoss':float(np.mean(losses)),'hardSamples':hardn,'hardStrictTop1':hardt/hardn if hardn else None}

def mkey(m): return (m['strictTop1'],m['hardStrictTop1'] or 0.,-m['meanEquityLoss'],m['top2'])

def main():
    rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    for i,r in enumerate(rows):
        if r.get('pristine') is not False: raise SystemExit(f'forbidden pristine row {i}')
        if r.get('xgLabel') not in (False,None) or r.get('xgLabelUsed') is True: raise SystemExit(f'forbidden XG row {i}')
    art=joblib.load(V33_MODEL)
    if art.get('pristineDataUsed') is not False or art.get('xgLabelsUsed') is not False or art.get('devUsedForModelSelection') is not False: raise SystemExit('v33 provenance invalid')
    counts={s:sum(r.get('split')==s and len(r.get('hints') or [])>=2 for r in rows) for s in ('train','tune','dev')}
    r0,stats=train(art,rows,['train'],3401)
    trials=[]; best=None
    for beta in (0.20,0.35,0.50,0.65,0.80,1.0):
        m=evaluate(art,r0,beta,rows,'tune'); trials.append({'beta':beta,'tune':m}); k=mkey(m)
        if best is None or k>best[0]: best=(k,beta)
    beta=best[1]
    # Configuration frozen. Refit on train+tune, then open dev once.
    rf,finalstats=train(art,rows,['train','tune'],3491)
    dev=evaluate(art,rf,beta,rows,'dev')
    out={'model':'mzand-gnu-v34','architecture':'V33_PLUS_HARD_DISAGREEMENT_RESIDUAL_RANKER','counts':counts,'selectedBeta':beta,'trainMining':stats,'finalMining':finalstats,'tuneTrials':trials,'dev':dev,'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False}
    joblib.dump({'version':'mzand-gnu-v34','baseV33':art,'residualRanker':rf,'beta':beta,'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False},MODEL)
    REPORT_JSON.write_text(json.dumps(out,indent=2)+'\n')
    REPORT.write_text('\n'.join([
        'MODEL: mzand-gnu-v34','ARCHITECTURE: V33_PLUS_HARD_DISAGREEMENT_RESIDUAL_RANKER',f'SELECTED_BETA: {beta:.2f}',f'TRAIN_MINED_ROWS: {stats["minedRows"]}',f'TRAIN_BASE_WRONG_ROWS: {stats["baseWrongRows"]}',f'FINAL_MINED_ROWS: {finalstats["minedRows"]}',f'TRAIN_POSITION_SAMPLES: {counts["train"]}',f'TUNE_POSITION_SAMPLES: {counts["tune"]}',f'DEV_POSITION_SAMPLES: {counts["dev"]}',f'DEV_STRICT_TOP1: {dev["strictTop1"]:.6f}',f'DEV_TOP2: {dev["top2"]:.6f}',f'DEV_TOP3: {dev["top3"]:.6f}',f'DEV_MEAN_EQUITY_LOSS: {dev["meanEquityLoss"]:.6f}',f'DEV_HARD_SAMPLES: {dev["hardSamples"]}',f'DEV_HARD_STRICT_TOP1: {dev["hardStrictTop1"]:.6f}','DEV_USED_FOR_MODEL_SELECTION: False','DEV_ROWS_MINED: 0','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
    print(REPORT.read_text())
if __name__=='__main__': main()
