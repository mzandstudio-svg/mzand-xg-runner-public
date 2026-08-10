#!/usr/bin/env python3
import importlib.util, json, os
from pathlib import Path
import joblib
import numpy as np
from xgboost import XGBRanker

spec=importlib.util.spec_from_file_location('mzv2',Path(__file__).with_name('train-mzand-gnu-v2.py'))
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rows=m.load_rows()


def make_rank_dataset(rows, splits):
    wanted=set(splits); X=[]; y=[]; qid=[]; group_w=[]; g=0
    for row in rows:
        if row.get('split') not in wanted: continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        margin=row.get('teacherMargin')
        hard=bool(row.get('hard')) or (isinstance(margin,(int,float)) and margin < 0.03)
        # Group weights focus teacher-ambiguous positions without touching dev labels.
        group_w.append(5.0 if hard else 1.0)
        n=len(hints)
        for h in hints:
            X.append(m.candidate_features(row,h))
            rank=int(h.get('rank', n))
            # Strongly optimize ordering of the best move while preserving full top-N order.
            y.append(float(max(0, n-rank+1)))
            qid.append(g)
        g+=1
    if not X: raise RuntimeError('empty ranking dataset')
    return np.stack(X),np.asarray(y,dtype=np.float32),np.asarray(qid,dtype=np.int32),np.asarray(group_w,dtype=np.float32)


def evaluate(model, rows, split):
    total=strict=top2=hard_total=hard_strict=0; losses=[]; details=[]
    for row in rows:
        if row.get('split')!=split: continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        feats=np.stack([m.candidate_features(row,h) for h in hints])
        pred=np.asarray(model.predict(feats),dtype=float)
        pick=int(np.argmax(pred)); rank=int(hints[pick].get('rank',99))
        top_eq=float(hints[0].get('equity',0.0)); picked_eq=float(hints[pick].get('equity',0.0)); loss=max(0.0,top_eq-picked_eq)
        hard=bool(row.get('hard'))
        total+=1; strict+=int(rank==1); top2+=int(rank<=2); losses.append(loss)
        if hard: hard_total+=1; hard_strict+=int(rank==1)
        details.append({'gameIndex':row.get('gameIndex'),'turn':row.get('turn'),'dice':row.get('dice'),'teacherMargin':row.get('teacherMargin'),'hard':hard,'pickedRank':rank,'equityLoss':loss})
    a=np.asarray(losses,dtype=float)
    return {'samples':total,'strictTop1':strict/total if total else 0.0,'top2':top2/total if total else 0.0,'meanEquityLoss':float(np.mean(a)) if total else None,'p95EquityLoss':float(np.quantile(a,.95)) if total else None,'hardSamples':hard_total,'hardStrictTop1':hard_strict/hard_total if hard_total else None,'details':details}


def factory(depth,eta,child,seed):
    return XGBRanker(objective='rank:pairwise',eval_metric='ndcg@1',n_estimators=1600,max_depth=depth,learning_rate=eta,min_child_weight=child,subsample=.92,colsample_bytree=.92,reg_alpha=.01,reg_lambda=2.5,tree_method='hist',n_jobs=-1,random_state=seed)

rows=m.load_rows(); counts={s:sum(1 for r in rows if r.get('split')==s) for s in ('train','tune','dev')}
if min(counts.values())<2000: raise SystemExit(f'insufficient v5 split sizes: {counts}')
X,y,qid,gw=make_rank_dataset(rows,['train'])
trials=[]; best=None
for name,args in [('rank-d6',(6,.035,3,20260815)),('rank-d8',(8,.025,4,20260816)),('rank-d10',(10,.02,5,20260817))]:
    model=factory(*args); model.fit(X,y,qid=qid,sample_weight=gw)
    tune=evaluate(model,rows,'tune'); trials.append({'name':name,'tune':{k:v for k,v in tune.items() if k!='details'}})
    key=(tune['strictTop1'],-tune['meanEquityLoss'],tune['top2'])
    if best is None or key>best[0]: best=(key,name,args)
_,best_name,best_args=best
Xf,yf,qf,gwf=make_rank_dataset(rows,['train','tune']); final=factory(*best_args); final.fit(Xf,yf,qid=qf,sample_weight=gwf)
dev=evaluate(final,rows,'dev'); tune=evaluate(final,rows,'tune'); train=evaluate(final,rows,'train')
joblib.dump({'model':final,'version':'mzand-gnu-v5','architecture':best_name,'candidateScoring':'xgb-rank-pairwise'},'mzand-gnu-v5.joblib')
report={'model':'mzand-gnu-v5','architecture':best_name,'teacher':'GNU Backgammon board-based all-dice','selectedBy':'tune only; dev untouched until final selection','pristineDataUsed':False,'xgLabelsUsed':False,'hardPositionWeight':5.0,'hardMarginFocus':0.03,'metricScope':'rerank within GNU-provided top-N candidates; not full legal candidate coverage','splitCounts':counts,'trials':trials,'train':{k:v for k,v in train.items() if k!='details'},'tuneAfterRefit':{k:v for k,v in tune.items() if k!='details'},'dev':{k:v for k,v in dev.items() if k!='details'},'devDetails':dev['details']}
Path('mzand-gnu-v5-report.json').write_text(json.dumps(report,indent=2)+'\n')
Path('mzand-gnu-v5-report.txt').write_text('\n'.join(['MODEL: mzand-gnu-v5',f'ARCHITECTURE: {best_name}','OBJECTIVE: RANK_PAIRWISE','HARD_POSITION_WEIGHT: 5.0','HARD_MARGIN_FOCUS: 0.03',f"TRAIN_POSITION_SAMPLES: {counts['train']}",f"TUNE_POSITION_SAMPLES: {counts['tune']}",f"DEV_POSITION_SAMPLES: {counts['dev']}",f"DEV_STRICT_TOP1: {dev['strictTop1']:.6f}",f"DEV_TOP2: {dev['top2']:.6f}",f"DEV_MEAN_EQUITY_LOSS: {dev['meanEquityLoss']:.6f}",f"DEV_P95_EQUITY_LOSS: {dev['p95EquityLoss']:.6f}",f"DEV_HARD_SAMPLES: {dev['hardSamples']}",f"DEV_HARD_STRICT_TOP1: {dev['hardStrictTop1'] if dev['hardStrictTop1'] is not None else 'NA'}",'DEV_USED_FOR_MODEL_SELECTION: False','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
print(Path('mzand-gnu-v5-report.txt').read_text())
