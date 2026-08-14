#!/usr/bin/env python3
"""MZand v7 foundation: from-scratch unique-position multi-task value net + adaptive 2-ply search.

Scientific contract:
- Train only on fresh GNU v7 train rows.
- Select epoch, rank/equity blend, and adaptive-search policy on fresh GNU v7 tune rows.
- Open the preserved official GNU dev rows exactly once after policy freeze.
- No pristine data. No XG labels. No dev mining or model selection.
- v33 remains an untouched checkpoint/baseline; this script never overwrites it.
"""
from __future__ import annotations

import argparse, copy, hashlib, importlib.util, json, math, os, random, sys, time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE=Path(__file__).resolve().parent
START=time.perf_counter()
SEED=7701
random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)
torch.set_num_threads(max(1, min(8, os.cpu_count() or 2)))


def load_module(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None: raise RuntimeError(f'cannot import {path}')
    m=importlib.util.module_from_spec(s); sys.modules[name]=m; s.loader.exec_module(m); return m
enc=load_module('mzand_v7_afterstate',HERE/'mzand-afterstate-v27.py')
engine=load_module('mzand_v7_engine',HERE/'mzand-engine-v27.py')

PROB_KEYS=('win','winGammon','winBackgammon','loseGammon','loseBackgammon')
DICE_OUTCOMES=engine.DICE_OUTCOMES

class ValueNet(nn.Module):
    def __init__(self,nin:int):
        super().__init__()
        self.fc1=nn.Linear(nin,256)
        self.fc2=nn.Linear(256,256)
        self.fc3=nn.Linear(256,128)
        self.prob=nn.Linear(128,5)
        self.eq=nn.Linear(128,1)
        self.cub=nn.Linear(128,1)
        self.rank=nn.Linear(128,1)
    def trunk(self,x):
        x=F.silu(self.fc1(x)); x=F.silu(self.fc2(x)); return F.silu(self.fc3(x))
    def forward(self,x):
        h=self.trunk(x)
        return self.prob(h),self.eq(h).squeeze(-1),self.cub(h).squeeze(-1),self.rank(h).squeeze(-1)


def read_jsonl(path:Path):
    with path.open() as f:
        for line in f:
            if line.strip(): yield json.loads(line)

def load_rows(fresh:Path, dev:Path):
    fresh_rows=list(read_jsonl(fresh)); dev_rows=list(read_jsonl(dev))
    for i,r in enumerate(fresh_rows):
        if r.get('split') not in ('train','tune'): raise SystemExit(f'fresh row bad split {i}: {r.get("split")}')
        if r.get('pristine') is not False: raise SystemExit(f'fresh pristine row {i}')
        if r.get('xgLabel') not in (False,None) or r.get('xgLabelUsed') is True: raise SystemExit(f'fresh XG row {i}')
        if r.get('devUsed') is True: raise SystemExit(f'fresh devUsed row {i}')
    for i,r in enumerate(dev_rows):
        if r.get('split')!='dev': raise SystemExit(f'official dev row bad split {i}')
        if r.get('pristine') is not False: raise SystemExit(f'official dev pristine row {i}')
        if r.get('xgLabel') not in (False,None) or r.get('xgLabelUsed') is True: raise SystemExit(f'official dev XG row {i}')
    return fresh_rows,dev_rows

def valid_rows(rows,split): return [r for r in rows if r.get('split')==split and len(r.get('hints') or [])>=2]

def pos_key(r):
    p=r.get('positionId')
    if p: return str(p)
    b=r['board']; return json.dumps([b['own'],b['opp'],b.get('barOwn',0),b.get('barOpp',0),b.get('offOwn',0),b.get('offOpp',0)],separators=(',',':'))

def phase_of(r):
    return str(r.get('phase') or 'unknown')

def make_train_arrays(rows):
    X=[]; probs=[]; eq=[]; cub=[]; cubmask=[]; pairs=[]; pairw=[]
    for r in rows:
        hints=r.get('hints') or []
        if len(hints)<2: continue
        start=len(X)
        eqs=[]
        for h in hints:
            X.append(enc.afterstate_features(r,h))
            e=h.get('evaluation') or {}
            probs.append([float(e.get(k,0.0) or 0.0) for k in PROB_KEYS])
            ev=float(h.get('equity',e.get('equity',0.0)) or 0.0); eq.append(ev); eqs.append(ev)
            c=e.get('cubefulEquity')
            cub.append(float(c) if isinstance(c,(int,float)) else 0.0); cubmask.append(1.0 if isinstance(c,(int,float)) else 0.0)
        ranks=[int(h.get('rank',999)) for h in hints]; top_local=int(np.argmin(ranks)); top_eq=eqs[top_local]
        for j in range(len(hints)):
            if j==top_local: continue
            gap=max(0.0, top_eq-eqs[j])
            w=0.25+1.75*min(1.0,gap/0.08)
            if r.get('teacherRolloutExecuted'): w*=3.0
            pairs.append((start+top_local,start+j)); pairw.append(w)
    return (np.asarray(X,np.float32),np.asarray(probs,np.float32),np.asarray(eq,np.float32),
            np.asarray(cub,np.float32),np.asarray(cubmask,np.float32),np.asarray(pairs,np.int64),np.asarray(pairw,np.float32))

def compute_norm(X):
    mu=X.mean(0).astype(np.float32); sd=X.std(0).astype(np.float32); sd=np.where(sd<1e-4,1.0,sd).astype(np.float32); return mu,sd

def zscore(a):
    a=np.asarray(a,float)
    if len(a)<=1:return np.zeros_like(a)
    s=float(a.std()); return a-a.mean() if s<1e-9 else (a-a.mean())/s

@torch.no_grad()
def predict_np(model,X,mu,sd,batch=8192):
    out_eq=[]; out_rank=[]; out_prob=[]; out_cub=[]
    for i in range(0,len(X),batch):
        xb=torch.from_numpy(((X[i:i+batch]-mu)/sd).astype(np.float32))
        p,e,c,r=model(xb)
        out_prob.append(torch.sigmoid(p).cpu().numpy()); out_eq.append(e.cpu().numpy()); out_cub.append(c.cpu().numpy()); out_rank.append(r.cpu().numpy())
    return np.concatenate(out_prob),np.concatenate(out_eq),np.concatenate(out_cub),np.concatenate(out_rank)

@torch.no_grad()
def score_row(model,row,mu,sd,alpha):
    hs=row.get('hints') or []
    X=np.stack([enc.afterstate_features(row,h) for h in hs]).astype(np.float32)
    _,eq,_,rank=predict_np(model,X,mu,sd,batch=256)
    blend=alpha*zscore(rank)+(1-alpha)*zscore(eq)
    return blend,eq,rank

def metrics_from_picks(rows,picks):
    n=t1=t2=t3=hn=ht=0; loss=[]; byphase={}
    for r,p in zip(rows,picks):
        hs=r.get('hints') or []
        if len(hs)<2: continue
        p=int(p); rr=int(hs[p].get('rank',999)); top=float(hs[0].get('equity',0)); got=float(hs[p].get('equity',0))
        n+=1; t1+=rr==1; t2+=rr<=2; t3+=rr<=3; loss.append(max(0.0,top-got))
        if r.get('hard'): hn+=1; ht+=rr==1
        ph=phase_of(r); a=byphase.setdefault(ph,[0,0]); a[0]+=1; a[1]+=rr==1
    return {'samples':n,'strictTop1':t1/n if n else 0.0,'top2':t2/n if n else 0.0,'top3':t3/n if n else 0.0,
            'meanEquityLoss':float(np.mean(loss)) if loss else None,'hardSamples':hn,'hardStrictTop1':ht/hn if hn else None,
            'phaseTop1':{k:v[1]/v[0] for k,v in sorted(byphase.items())},'phaseSamples':{k:v[0] for k,v in sorted(byphase.items())}}

def direct_eval(model,rows,mu,sd,alpha,return_details=False):
    picks=[]; margins=[]; scores=[]
    for r in rows:
        b,_,_=score_row(model,r,mu,sd,alpha); order=np.argsort(-b); picks.append(int(order[0])); margins.append(float(b[order[0]]-b[order[1]]) if len(order)>1 else 99.0); scores.append(b)
    m=metrics_from_picks(rows,picks)
    if return_details: return m,picks,np.asarray(margins,float),scores
    return m

def board_key(b):
    return (tuple(map(int,b['own'])),tuple(map(int,b['opp'])),int(b.get('barOwn',0)),int(b.get('barOpp',0)),int(b.get('offOwn',0)),int(b.get('offOpp',0)))

class Searcher:
    def __init__(self,model,mu,sd):
        self.model=model; self.mu=mu; self.sd=sd; self.cache={}; self.value_cache={}
    @torch.no_grad()
    def values(self,boards):
        if not boards:return np.empty(0,float)
        X=np.stack([enc.afterstate_features_from_board(b) for b in boards]).astype(np.float32)
        _,eq,_,_=predict_np(self.model,X,self.mu,self.sd,batch=4096); return eq
    def board_value(self,b):
        k=board_key(b)
        if k not in self.value_cache:self.value_cache[k]=float(self.values([b])[0])
        return self.value_cache[k]
    def decision_value(self,b,dice):
        k=(board_key(b),tuple(dice))
        if k in self.cache:return self.cache[k]
        cs=engine.generate_legal_candidates(b,dice)
        if len(cs)==1 and cs[0].get('forcedPass'):
            v=self.board_value(b); self.cache[k]=v; return v
        vals=[]; boards=[]
        for c in cs:
            after=engine.apply_candidate(b,c); term=engine.terminal_points_for_mover(after)
            vals.append(float(term) if term is not None else None); boards.append(after)
        need=[boards[i] for i,v in enumerate(vals) if v is None]
        pred=iter(self.values(need))
        for i,v in enumerate(vals):
            if v is None: vals[i]=float(next(pred))
        best=max(vals) if vals else self.board_value(b); self.cache[k]=best; return best
    def root_value(self,row,hint):
        after=enc.afterstate_from_hint(row['board'],hint); term=engine.terminal_points_for_mover(after)
        if term is not None:return float(term)
        opp=engine.flip_board(after)
        return -sum(prob*self.decision_value(opp,dice) for dice,prob in DICE_OUTCOMES)

def precompute_search(model,rows,mu,sd,alpha,margins,scores,max_fraction=0.70,root_k=6):
    if not rows:return {},None
    threshold=float(np.quantile(margins,max_fraction)); searcher=Searcher(model,mu,sd); found={}; selected=0
    for i,(r,margin,b) in enumerate(zip(rows,margins,scores)):
        if margin>threshold: continue
        order=np.argsort(-b)[:min(root_k,len(b))]; vals=[]
        for j in order: vals.append(searcher.root_value(r,r['hints'][int(j)]))
        found[i]=(np.asarray(order,int),np.asarray(vals,float)); selected+=1
        if selected%100==0: print(f'search-precompute {selected}',flush=True)
    return found,threshold

def apply_policy(rows,direct_picks,margins,scores,search_map,threshold,beta):
    picks=list(direct_picks); overrides=0
    if threshold<=0:return picks,overrides
    for i in range(len(rows)):
        if margins[i]>threshold or i not in search_map: continue
        order,sv=search_map[i]
        ds=np.asarray(scores[i],float)[order]
        final=(1-beta)*zscore(ds)+beta*zscore(sv)
        p=int(order[int(np.argmax(final))]); overrides+=p!=picks[i]; picks[i]=p
    return picks,overrides

def choose_search_policy(rows,direct_picks,margins,scores,search_map):
    base=metrics_from_picks(rows,direct_picks); best=((base['strictTop1'],-base['meanEquityLoss'],base['top2']),0.0,0.0,base,0)
    for frac in (0.10,0.20,0.35,0.50,0.70):
        th=float(np.quantile(margins,frac))
        for beta in (0.50,0.75,1.00):
            picks,ov=apply_policy(rows,direct_picks,margins,scores,search_map,th,beta); m=metrics_from_picks(rows,picks); key=(m['strictTop1'],-m['meanEquityLoss'],m['top2'])
            if key>best[0]:best=(key,th,beta,m,ov)
    return {'threshold':best[1],'beta':best[2],'metrics':best[3],'overrides':best[4],'base':base}

def train_model(train_rows,tune_rows,epochs=18):
    X,P,E,C,CM,Pairs,PW=make_train_arrays(train_rows); mu,sd=compute_norm(X)
    model=ValueNet(X.shape[1]); opt=torch.optim.AdamW(model.parameters(),lr=1.5e-3,weight_decay=1e-4)
    n=len(X); npair=len(Pairs); best=None; bad=0
    for epoch in range(1,epochs+1):
        model.train(); perm=np.random.permutation(n); losses=[]
        for st in range(0,n,4096):
            ix=perm[st:st+4096]; xb=torch.from_numpy(((X[ix]-mu)/sd).astype(np.float32)); pt=torch.from_numpy(P[ix]); et=torch.from_numpy(E[ix]); ct=torch.from_numpy(C[ix]); mt=torch.from_numpy(CM[ix])
            pl,ep,cp,_=model(xb); lp=F.binary_cross_entropy_with_logits(pl,pt); le=F.smooth_l1_loss(ep,et,beta=0.03)
            if float(mt.sum())>0: lc=(F.smooth_l1_loss(cp,ct,beta=0.03,reduction='none')*mt).sum()/mt.sum()
            else: lc=ep.sum()*0.0
            loss=lp+3.0*le+0.7*lc; opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),5.0); opt.step(); losses.append(float(loss))
        pperm=np.random.permutation(npair)
        for st in range(0,npair,4096):
            ii=pperm[st:st+4096]; pa=Pairs[ii]; inds=np.unique(pa.reshape(-1)); mp={int(v):j for j,v in enumerate(inds)}; xb=torch.from_numpy(((X[inds]-mu)/sd).astype(np.float32)); _,_,_,rs=model(xb)
            top=torch.stack([rs[mp[int(a)]] for a in pa[:,0]]); oth=torch.stack([rs[mp[int(b)]] for b in pa[:,1]]); ww=torch.from_numpy(PW[ii])
            l=(F.softplus(-(top-oth))*ww).mean(); opt.zero_grad(); (1.4*l).backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),5.0); opt.step()
        model.eval(); tm=direct_eval(model,tune_rows,mu,sd,0.65); key=(tm['strictTop1'],-tm['meanEquityLoss'],tm['top2'])
        print(f'EPOCH={epoch} LOSS={np.mean(losses):.6f} TUNE_TOP1={tm["strictTop1"]:.6f} TUNE_TOP2={tm["top2"]:.6f} TUNE_LOSS={tm["meanEquityLoss"]:.6f}',flush=True)
        if best is None or key>best[0]: best=(key,copy.deepcopy(model.state_dict()),epoch,tm); bad=0
        else: bad+=1
        if bad>=4 and epoch>=8:break
    model.load_state_dict(best[1]); return model,mu,sd,{'bestEpoch':best[2],'earlyTune':best[3],'candidateSamples':n,'pairSamples':npair}

def export_npz(model,mu,sd,path):
    d={'input_mean':mu,'input_std':sd}
    for k,v in model.state_dict().items():d[k.replace('.','__')]=v.detach().cpu().numpy()
    np.savez_compressed(path,**d)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--fresh',default='gnu-v7-fresh.jsonl'); ap.add_argument('--dev',default='gnu-v7-official-dev.jsonl'); ap.add_argument('--epochs',type=int,default=18); args=ap.parse_args()
    fresh,dev=load_rows(Path(args.fresh),Path(args.dev)); tr=valid_rows(fresh,'train'); tu=valid_rows(fresh,'tune'); dv=valid_rows(dev,'dev')
    trpos=len({pos_key(r) for r in tr}); tupos=len({pos_key(r) for r in tu}); dvpos=len({pos_key(r) for r in dv})
    if trpos<5000: raise SystemExit(f'insufficient unique train positions {trpos}')
    if tupos<800: raise SystemExit(f'insufficient unique tune positions {tupos}')
    overlap={pos_key(r) for r in tr}&{pos_key(r) for r in tu}
    if overlap: raise SystemExit(f'train/tune position leakage {len(overlap)}')
    model,mu,sd,trainmeta=train_model(tr,tu,args.epochs)
    alpha_trials=[]; best=None
    for a in (0.35,0.50,0.65,0.80,0.95):
        m=direct_eval(model,tu,mu,sd,a); alpha_trials.append({'alpha':a,'metrics':m}); k=(m['strictTop1'],-m['meanEquityLoss'],m['top2'])
        if best is None or k>best[0]:best=(k,a,m)
    alpha=float(best[1]); tune_direct,tune_picks,tune_margins,tune_scores=direct_eval(model,tu,mu,sd,alpha,True)
    smap,_=precompute_search(model,tu,mu,sd,alpha,tune_margins,tune_scores,0.70,6)
    policy=choose_search_policy(tu,tune_picks,tune_margins,tune_scores,smap)
    frozen={'alpha':alpha,'searchThreshold':float(policy['threshold']),'searchBeta':float(policy['beta']),'rootK':6}
    print('FROZEN_POLICY',json.dumps(frozen),flush=True)

    # Sealed dev opens only here, after every choice is frozen.
    dev_direct,dev_picks,dev_margins,dev_scores=direct_eval(model,dv,mu,sd,alpha,True)
    if frozen['searchThreshold']>0:
        # Only compute dev search where the already-frozen threshold requests it.
        dsearcher=Searcher(model,mu,sd); dmap={}; count=0
        for i,(r,m,b) in enumerate(zip(dv,dev_margins,dev_scores)):
            if m>frozen['searchThreshold']:continue
            order=np.argsort(-b)[:min(frozen['rootK'],len(b))]; vals=np.asarray([dsearcher.root_value(r,r['hints'][int(j)]) for j in order],float); dmap[i]=(np.asarray(order,int),vals); count+=1
            if count%100==0:print(f'dev-search {count}',flush=True)
        dev_final_picks,dev_overrides=apply_policy(dv,dev_picks,dev_margins,dev_scores,dmap,frozen['searchThreshold'],frozen['searchBeta'])
    else: dev_final_picks=list(dev_picks); dev_overrides=0
    dev_final=metrics_from_picks(dv,dev_final_picks)

    torch.save({'state_dict':model.state_dict(),'inputMean':mu,'inputStd':sd,'featureCount':int(len(mu)),'policy':frozen,'version':'mzand-v7-foundation'},'mzand-v7-foundation.pt')
    export_npz(model,mu,sd,'mzand-v7-foundation-portable.npz')
    out={
      'model':'mzand-v7-foundation','architecture':'FRESH_UNIQUE_MULTI_TASK_VALUE_NET_PLUS_ADAPTIVE_2PLY','seed':SEED,
      'freshCounts':{'trainRows':len(tr),'tuneRows':len(tu),'trainUniquePositions':trpos,'tuneUniquePositions':tupos},
      'officialDev':{'rows':len(dv),'uniquePositions':dvpos},'trainMeta':trainmeta,'alphaTrials':alpha_trials,'selectedAlpha':alpha,
      'tuneDirect':tune_direct,'tuneSearchPolicy':policy,'frozenPolicy':frozen,'devDirect':dev_direct,'dev':dev_final,'devOverrides':dev_overrides,
      'baselineV33Top1':0.819506,'deltaTop1VsV33':dev_final['strictTop1']-0.819506,
      'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False,'xgTrainingEligible':False,
      'elapsedSeconds':time.perf_counter()-START,
    }
    Path('mzand-v7-foundation-report.json').write_text(json.dumps(out,indent=2)+'\n')
    lines=[
      'MODEL: mzand-v7-foundation','ARCHITECTURE: FRESH_UNIQUE_MULTI_TASK_VALUE_NET_PLUS_ADAPTIVE_2PLY',
      f'TRAIN_ROWS: {len(tr)}',f'TUNE_ROWS: {len(tu)}',f'TRAIN_UNIQUE_POSITIONS: {trpos}',f'TUNE_UNIQUE_POSITIONS: {tupos}',f'OFFICIAL_DEV_ROWS: {len(dv)}',f'OFFICIAL_DEV_UNIQUE_POSITIONS: {dvpos}',
      f'BEST_EPOCH: {trainmeta["bestEpoch"]}',f'SELECTED_ALPHA: {alpha:.2f}',f'SELECTED_SEARCH_THRESHOLD: {frozen["searchThreshold"]:.6f}',f'SELECTED_SEARCH_BETA: {frozen["searchBeta"]:.2f}',
      f'TUNE_DIRECT_TOP1: {tune_direct["strictTop1"]:.6f}',f'TUNE_SEARCH_TOP1: {policy["metrics"]["strictTop1"]:.6f}',
      f'DEV_DIRECT_TOP1: {dev_direct["strictTop1"]:.6f}',f'DEV_STRICT_TOP1: {dev_final["strictTop1"]:.6f}',f'DEV_TOP2: {dev_final["top2"]:.6f}',f'DEV_TOP3: {dev_final["top3"]:.6f}',
      f'DEV_MEAN_EQUITY_LOSS: {dev_final["meanEquityLoss"]:.6f}',f'DEV_HARD_SAMPLES: {dev_final["hardSamples"]}',f'DEV_HARD_STRICT_TOP1: {dev_final["hardStrictTop1"]:.6f}',f'DEV_OVERRIDES: {dev_overrides}',f'DELTA_TOP1_VS_V33: {out["deltaTop1VsV33"]:+.6f}',
      'DEV_USED_FOR_MODEL_SELECTION: False','DEV_ROWS_MINED: 0','PRISTINE_DATA_USED: False','XG_LABELS_USED: False','XG_TRAINING_ELIGIBLE: False',f'TOTAL_SECONDS: {out["elapsedSeconds"]:.3f}'
    ]
    Path('mzand-v7-foundation-report.txt').write_text('\n'.join(lines)+'\n'); print(Path('mzand-v7-foundation-report.txt').read_text(),flush=True)

if __name__=='__main__': main()
