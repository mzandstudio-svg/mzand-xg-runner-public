#!/usr/bin/env python3
"""GNU v35: confidence-gated residual ranker over frozen v33.

The original single-process v35 exceeded the 6-hour hosted-runner ceiling while
performing two exact XGBRanker fits. This script preserves the algorithm and
sealed-dev policy but supports two bounded stages:
  select: train residual on train only; select beta+gate on tune only.
  final:  refit residual on train+tune with frozen beta+gate; open dev once.
No dev mining/model selection, pristine, or XG data.
"""
from __future__ import annotations
import importlib.util, json, os, sys
from pathlib import Path
import joblib, numpy as np

HERE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('GNU_V35_BATCH_OUT','gnu-teacher-v35-scaled.jsonl'))
V33_MODEL=Path(os.environ.get('GNU_V35_V33_MODEL','v33/mzand-gnu-v33-phase-experts.joblib'))
STAGE=os.environ.get('GNU_V35_STAGE','all').strip().lower()
SELECTION=Path(os.environ.get('GNU_V35_SELECTION','mzand-gnu-v35-selection.json'))
SELECTION_REPORT=Path('mzand-gnu-v35-selection-report.txt')
REPORT=Path('mzand-gnu-v35-confidence-gated-report.txt')
REPORT_JSON=Path('mzand-gnu-v35-confidence-gated-report.json')
MODEL=Path('mzand-gnu-v35-confidence-gated.joblib')

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); sys.modules[name]=m; s.loader.exec_module(m); return m
v27=load('v27_v35',HERE/'train-mzand-gnu-v27.py')
v34=load('v34_v35',HERE/'train-mzand-gnu-v34-hard-residual.py')

def base_gap(art,row):
    b,_,_=v34.base_scores(art,row)
    z=np.sort(v27.zscore(b))
    return float(z[-1]-z[-2]) if len(z)>=2 else 99.0

def evaluate(art,residual,beta,gate,rows,split):
    total=t1=t2=t3=hardn=hardt=gated=0; losses=[]
    for row in rows:
        if row.get('split')!=split: continue
        hints=row.get('hints') or []
        if len(hints)<2: continue
        b,_,_=v34.base_scores(art,row); score=np.asarray(b,float)
        gap=base_gap(art,row)
        if beta>0 and gap<=gate:
            rr=np.asarray(residual.predict(v34.candidate_features(art,row)),float)
            score=(1-beta)*v27.zscore(b)+beta*v27.zscore(rr); gated+=1
        ix=int(np.argmax(score)); rank=int(hints[ix].get('rank',999))
        top=float(hints[0].get('equity',0)); got=float(hints[ix].get('equity',0)); losses.append(max(0.,top-got))
        total+=1; t1+=rank==1; t2+=rank<=2; t3+=rank<=3
        if row.get('hard'): hardn+=1; hardt+=rank==1
    return {'samples':total,'strictTop1':t1/total,'top2':t2/total,'top3':t3/total,'meanEquityLoss':float(np.mean(losses)),'hardSamples':hardn,'hardStrictTop1':hardt/hardn if hardn else None,'gatedRows':gated}

def mkey(m):
    return (m['strictTop1'], -m['meanEquityLoss'], m['hardStrictTop1'] or 0., m['top2'])

def load_inputs():
    rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
    for i,r in enumerate(rows):
        if r.get('pristine') is not False: raise SystemExit(f'forbidden pristine row {i}')
        if r.get('xgLabel') not in (False,None) or r.get('xgLabelUsed') is True: raise SystemExit(f'forbidden XG row {i}')
    art=joblib.load(V33_MODEL)
    if art.get('pristineDataUsed') is not False or art.get('xgLabelsUsed') is not False or art.get('devUsedForModelSelection') is not False:
        raise SystemExit('v33 provenance invalid')
    counts={s:sum(r.get('split')==s and len(r.get('hints') or [])>=2 for r in rows) for s in ('train','tune','dev')}
    return rows,art,counts

def select_stage(rows,art,counts):
    r0,stats=v34.train(art,rows,['train'],3501)
    trials=[]; best=None
    for beta in (0.0,0.20,0.35,0.50,0.65,0.80):
        gates=(0.0,) if beta==0 else (0.10,0.20,0.35,0.50,0.75,1.00,1.50,2.50,9.00)
        for gate in gates:
            m=evaluate(art,r0,beta,gate,rows,'tune'); trials.append({'beta':beta,'gate':gate,'tune':m}); k=mkey(m)
            if best is None or k>best[0]: best=(k,beta,gate)
    beta,gate=best[1],best[2]
    out={'model':'mzand-gnu-v35','stage':'select','architecture':'V33_PLUS_CONFIDENCE_GATED_HARD_RESIDUAL','counts':counts,'selectedBeta':beta,'selectedGate':gate,'trainMining':stats,'tuneTrials':trials,'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False}
    SELECTION.write_text(json.dumps(out,indent=2)+'\n')
    SELECTION_REPORT.write_text('\n'.join([
        'MODEL: mzand-gnu-v35','STAGE: SELECT_TRAIN_TUNE_ONLY',f'SELECTED_BETA: {beta:.2f}',f'SELECTED_GATE: {gate:.2f}',f'TRAIN_MINED_ROWS: {stats["minedRows"]}',f'TRAIN_BASE_WRONG_ROWS: {stats["baseWrongRows"]}',f'TRAIN_POSITION_SAMPLES: {counts["train"]}',f'TUNE_POSITION_SAMPLES: {counts["tune"]}','DEV_OPENED: False','DEV_USED_FOR_MODEL_SELECTION: False','DEV_ROWS_MINED: 0','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
    print(SELECTION_REPORT.read_text())

def final_stage(rows,art,counts):
    sel=json.loads(SELECTION.read_text())
    if sel.get('devUsedForModelSelection') is not False or sel.get('devRowsMined') != 0 or sel.get('pristineDataUsed') is not False or sel.get('xgLabelsUsed') is not False:
        raise SystemExit('selection provenance invalid')
    beta=float(sel['selectedBeta']); gate=float(sel['selectedGate'])
    rf,finalstats=v34.train(art,rows,['train','tune'],3591)
    dev=evaluate(art,rf,beta,gate,rows,'dev')
    out={'model':'mzand-gnu-v35','stage':'final','architecture':'V33_PLUS_CONFIDENCE_GATED_HARD_RESIDUAL','counts':counts,'selectedBeta':beta,'selectedGate':gate,'trainMining':sel['trainMining'],'finalMining':finalstats,'tuneTrials':sel['tuneTrials'],'dev':dev,'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False}
    joblib.dump({'version':'mzand-gnu-v35','baseV33':art,'residualRanker':rf,'beta':beta,'gate':gate,'devUsedForModelSelection':False,'devRowsMined':0,'pristineDataUsed':False,'xgLabelsUsed':False},MODEL)
    REPORT_JSON.write_text(json.dumps(out,indent=2)+'\n')
    REPORT.write_text('\n'.join([
        'MODEL: mzand-gnu-v35','ARCHITECTURE: V33_PLUS_CONFIDENCE_GATED_HARD_RESIDUAL',f'SELECTED_BETA: {beta:.2f}',f'SELECTED_GATE: {gate:.2f}',f'TRAIN_MINED_ROWS: {sel["trainMining"]["minedRows"]}',f'TRAIN_BASE_WRONG_ROWS: {sel["trainMining"]["baseWrongRows"]}',f'FINAL_MINED_ROWS: {finalstats["minedRows"]}',f'TRAIN_POSITION_SAMPLES: {counts["train"]}',f'TUNE_POSITION_SAMPLES: {counts["tune"]}',f'DEV_POSITION_SAMPLES: {counts["dev"]}',f'DEV_STRICT_TOP1: {dev["strictTop1"]:.6f}',f'DEV_TOP2: {dev["top2"]:.6f}',f'DEV_TOP3: {dev["top3"]:.6f}',f'DEV_MEAN_EQUITY_LOSS: {dev["meanEquityLoss"]:.6f}',f'DEV_HARD_SAMPLES: {dev["hardSamples"]}',f'DEV_HARD_STRICT_TOP1: {dev["hardStrictTop1"]:.6f}',f'DEV_GATED_ROWS: {dev["gatedRows"]}','DEV_USED_FOR_MODEL_SELECTION: False','DEV_ROWS_MINED: 0','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
    print(REPORT.read_text())

def main():
    rows,art,counts=load_inputs()
    if STAGE=='select': select_stage(rows,art,counts)
    elif STAGE=='final': final_stage(rows,art,counts)
    elif STAGE=='all':
        select_stage(rows,art,counts)
        final_stage(rows,art,counts)
    else: raise SystemExit(f'unknown GNU_V35_STAGE={STAGE!r}')
if __name__=='__main__': main()
