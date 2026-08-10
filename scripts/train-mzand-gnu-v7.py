#!/usr/bin/env python3
"""MZand v7 GNU-only disagreement mining.

Uses no pristine or XG labels. Dev is held out until the final frozen evaluation.
The first-pass GNU model is used only to identify difficult training/tune rows;
those rows are then up-weighted for a second-pass rank+equity ensemble.
"""
import importlib.util
import json
import os
from pathlib import Path

import joblib
import numpy as np
from xgboost import XGBRanker, XGBRegressor

V6 = Path(__file__).with_name('train-mzand-gnu-v6.py')
spec = importlib.util.spec_from_file_location('mzv6', V6)
v6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v6)
m = v6.m

DATA = Path(os.environ.get('GNU_V7_BATCH_OUT', 'gnu-teacher-v7.jsonl'))
MODEL = Path(os.environ.get('MZAND_V7_MODEL_OUT', 'mzand-gnu-v7.joblib'))
REPORT_JSON = Path('mzand-gnu-v7-report.json')
REPORT_TXT = Path('mzand-gnu-v7-report.txt')


def load_rows():
    with DATA.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def zscore(a):
    a = np.asarray(a, dtype=float)
    if len(a) <= 1:
        return np.zeros_like(a)
    s = float(np.std(a))
    return a - float(np.mean(a)) if s < 1e-9 else (a - float(np.mean(a))) / s


def base_weight(row):
    margin = row.get('teacherMargin')
    if row.get('rolloutCandidate'):
        return 8.0
    if row.get('hard') or (isinstance(margin, (int, float)) and margin < 0.03):
        return 5.0
    return 1.0


def candidate_matrix(row):
    hints = row.get('hints') or []
    return np.stack([m.candidate_features(row, h) for h in hints])


def preliminary_disagreement(rows, ranker, regressor, alpha):
    flags = set()
    total = disagree = low_margin = 0
    for i, row in enumerate(rows):
        if row.get('split') not in ('train', 'tune'):
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        total += 1
        X = candidate_matrix(row)
        score = alpha * zscore(ranker.predict(X)) + (1.0-alpha) * zscore(regressor.predict(X))
        pick = int(np.argmax(score))
        picked_rank = int(hints[pick].get('rank', 999))
        margin = row.get('teacherMargin')
        hard_margin = isinstance(margin, (int, float)) and margin < 0.03
        wrong = picked_rank != 1
        if wrong:
            disagree += 1
        if hard_margin:
            low_margin += 1
        if wrong or hard_margin:
            flags.add(i)
    return flags, {'eligible': total, 'disagreementRows': disagree, 'lowMarginRows': low_margin, 'minedRows': len(flags)}


def make_rank_dataset(rows, splits, mined=None):
    wanted = set(splits); mined = mined or set()
    X=[]; y=[]; qid=[]; weights=[]; g=0
    for i,row in enumerate(rows):
        if row.get('split') not in wanted:
            continue
        hints=row.get('hints') or []
        if len(hints)<2:
            continue
        w=base_weight(row)
        if i in mined:
            w=max(w,12.0)
        weights.append(w)
        n=len(hints)
        for h in hints:
            X.append(m.candidate_features(row,h))
            rank=int(h.get('rank',n))
            # top-heavy relevance while preserving full teacher order
            y.append(float((n-rank+1) + (4 if rank==1 else 0)))
            qid.append(g)
        g+=1
    if not X: raise RuntimeError('empty v7 rank dataset')
    return np.stack(X),np.asarray(y,np.float32),np.asarray(qid,np.int32),np.asarray(weights,np.float32)


def make_equity_dataset(rows,splits,mined=None):
    wanted=set(splits); mined=mined or set(); X=[]; y=[]; w=[]
    for i,row in enumerate(rows):
        if row.get('split') not in wanted: continue
        hints=row.get('hints') or []
        if not hints: continue
        ww=base_weight(row)
        if i in mined: ww=max(ww,12.0)
        for h in hints:
            X.append(m.candidate_features(row,h)); y.append(float(h.get('equity',0.0))); w.append(ww)
    if not X: raise RuntimeError('empty v7 equity dataset')
    return np.stack(X),np.asarray(y,np.float32),np.asarray(w,np.float32)


def factories(depth, seed):
    ranker=XGBRanker(objective='rank:pairwise',eval_metric='ndcg@1',n_estimators=2200,max_depth=depth,
        learning_rate=.018,min_child_weight=3,subsample=.94,colsample_bytree=.94,reg_alpha=.015,reg_lambda=3.0,
        tree_method='hist',n_jobs=-1,random_state=seed)
    reg=XGBRegressor(objective='reg:squarederror',n_estimators=2200,max_depth=depth,learning_rate=.018,
        min_child_weight=3,subsample=.94,colsample_bytree=.94,reg_alpha=.015,reg_lambda=3.0,
        tree_method='hist',n_jobs=-1,random_state=seed+1)
    return ranker,reg


def train(rows,splits,depth,seed,mined=None):
    X,y,qid,gw=make_rank_dataset(rows,splits,mined)
    ranker,reg=factories(depth,seed); ranker.fit(X,y,qid=qid,sample_weight=gw)
    Xe,ye,ew=make_equity_dataset(rows,splits,mined); reg.fit(Xe,ye,sample_weight=ew)
    return ranker,reg


def evaluate(ranker,reg,alpha,rows,split,details=False):
    total=strict=top2=top3=hard_total=hard_strict=0; losses=[]; out=[]
    for row in rows:
        if row.get('split')!=split: continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        X=candidate_matrix(row)
        score=alpha*zscore(ranker.predict(X))+(1-alpha)*zscore(reg.predict(X))
        pick=int(np.argmax(score)); rank=int(hints[pick].get('rank',999))
        top=float(hints[0].get('equity',0)); got=float(hints[pick].get('equity',0)); loss=max(0.,top-got)
        total+=1; strict+=rank==1; top2+=rank<=2; top3+=rank<=3; losses.append(loss)
        if row.get('hard'):
            hard_total+=1; hard_strict+=rank==1
        if details: out.append({'gameIndex':row.get('gameIndex'),'turn':row.get('turn'),'dice':row.get('dice'),'teacherMargin':row.get('teacherMargin'),'hard':bool(row.get('hard')),'pickedRank':rank,'equityLoss':loss})
    a=np.asarray(losses,float)
    return {'samples':total,'strictTop1':strict/total if total else 0.,'top2':top2/total if total else 0.,'top3':top3/total if total else 0.,'meanEquityLoss':float(np.mean(a)) if total else None,'p95EquityLoss':float(np.quantile(a,.95)) if total else None,'hardSamples':hard_total,'hardStrictTop1':hard_strict/hard_total if hard_total else None,'details':out}


def key(x): return (x['strictTop1'],-x['meanEquityLoss'],x['top2'],x['hardStrictTop1'] or 0.)


def main():
    rows=load_rows(); counts={s:sum(1 for r in rows if r.get('split')==s and len(r.get('hints') or [])>=2) for s in ('train','tune','dev')}
    if min(counts.values())<300: raise SystemExit(f'insufficient v7 split sizes: {counts}')

    # First pass is train-only. Tune picks blend/depth; dev remains untouched.
    p_rank,p_reg=train(rows,['train'],8,20260831)
    best_alpha=max((.50,.65,.80,1.0),key=lambda a:key(evaluate(p_rank,p_reg,a,rows,'tune')))
    mined,mining=preliminary_disagreement(rows,p_rank,p_reg,best_alpha)

    trials=[]; best=None
    for depth in (7,9,11):
        r,g=train(rows,['train'],depth,20260900+depth,mined)
        for alpha in (.50,.65,.80,1.0):
            tune=evaluate(r,g,alpha,rows,'tune'); compact={k:v for k,v in tune.items() if k!='details'}
            trials.append({'depth':depth,'alpha':alpha,'tune':compact})
            k=key(tune)
            if best is None or k>best[0]: best=(k,depth,alpha)
    _,depth,alpha=best

    final_r,final_g=train(rows,['train','tune'],depth,20260920,mined)
    dev=evaluate(final_r,final_g,alpha,rows,'dev',True); tune=evaluate(final_r,final_g,alpha,rows,'tune')
    joblib.dump({'version':'mzand-gnu-v7','ranker':final_r,'equityRegressor':final_g,'rankBlendAlpha':alpha,'depth':depth,'teacher':'GNU Backgammon 3-ply Huge/pruning','xgLabelsUsed':False,'pristineDataUsed':False},MODEL)
    report={'model':'mzand-gnu-v7','teacher':'GNU Backgammon 3-ply Huge/pruning','teacherRolloutExecuted':False,'selectedBy':'tune only; dev untouched until final','pristineDataUsed':False,'xgLabelsUsed':False,'devUsedForModelSelection':False,'metricScope':'GNU Huge-filter candidate rerank','splitCounts':counts,'mining':mining,'selectedDepth':depth,'rankBlendAlpha':alpha,'trials':trials,'tuneAfterRefit':{k:v for k,v in tune.items() if k!='details'},'dev':{k:v for k,v in dev.items() if k!='details'},'devDetails':dev['details']}
    REPORT_JSON.write_text(json.dumps(report,indent=2)+'\n')
    REPORT_TXT.write_text('\n'.join(['MODEL: mzand-gnu-v7','PHASE: GNU_3PLY_HUGE_DISAGREEMENT_MINING',f'SELECTED_DEPTH: {depth}',f'RANK_BLEND_ALPHA: {alpha:.2f}',f"TRAIN_POSITION_SAMPLES: {counts['train']}",f"TUNE_POSITION_SAMPLES: {counts['tune']}",f"DEV_POSITION_SAMPLES: {counts['dev']}",f"MINED_ROWS: {mining['minedRows']}",f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",f"DEV_TOP2: {dev['top2']:.6f}",f"DEV_TOP3: {dev['top3']:.6f}",f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",f"DEV_HARD_SAMPLES: {dev['hardSamples']}",f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",'TEACHER_ROLLOUT_EXECUTED: False','DEV_USED_FOR_MODEL_SELECTION: False','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
    print(REPORT_TXT.read_text())

if __name__=='__main__': main()
