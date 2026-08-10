#!/usr/bin/env python3
import json, os
from pathlib import Path

DATA=Path(os.environ.get('GNU_V13_BATCH_IN','gnu-teacher-v13.jsonl'))
SELECTED=Path(os.environ.get('GNU_V13_SELECTED','gnu-v13-selected.jsonl'))
EVIDENCE=Path(os.environ.get('GNU_V13_EVIDENCE','gnu-v13-rollout-evidence.json'))
OUT=Path(os.environ.get('GNU_V13_BATCH_OUT','gnu-teacher-v13-refined.jsonl'))
REPORT=Path('gnu-v13-refinement-report.txt')

rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
selected=[json.loads(x) for x in SELECTED.read_text().splitlines() if x.strip()]
evidence=json.loads(EVIDENCE.read_text())
by_idx={int(x['sourceRowIndex']):x for x in evidence}
changed=flips=0
for s in selected:
    idx=int(s['sourceRowIndex'])
    if s.get('sourceSplit') not in ('train','tune'): raise SystemExit('dev row selected')
    if s.get('pristine') is not False or s.get('xgLabelUsed') is not False: raise SystemExit('provenance violation')
    ev=by_idx.get(idx)
    if not ev: raise SystemExit(f'missing evidence for row {idx}')
    row=rows[idx]
    if row.get('split') not in ('train','tune') or row.get('pristine') is not False or row.get('xgLabel') is not False:
        raise SystemExit(f'unsafe source row {idx}')
    h1=next((h for h in row.get('hints',[]) if int(h.get('rank',999))==1),None)
    h2=next((h for h in row.get('hints',[]) if int(h.get('rank',999))==2),None)
    if h1 is None or h2 is None: raise SystemExit(f'missing top2 hints {idx}')
    e1=float(ev['rank1Equity']); e2=float(ev['rank2Equity'])
    h1['equity']=e1; h2['equity']=e2
    h1.setdefault('evaluation',{})['equity']=e1; h2.setdefault('evaluation',{})['equity']=e2
    if e2>e1:
        h1['rank'],h2['rank']=2,1; flips+=1
    else:
        h1['rank'],h2['rank']=1,2
    row['hints']=sorted(row['hints'],key=lambda h:int(h.get('rank',999)))
    margin=abs(e1-e2)
    row['teacher']='GNU Backgammon true marked-move rollout refined'
    row['teacherRolloutExecuted']=True
    row['rolloutTrials']=int(ev['trials'])
    row['rolloutRefinedRanks']=[1,2]
    row['teacherMargin']=margin
    row['hard']=margin<0.03
    row['rolloutCandidate']=margin<0.012
    row['pristine']=False; row['xgLabel']=False
    changed+=1
OUT.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
REPORT.write_text('\n'.join([
    'REFINEMENT: GNU_TRUE_ROLLOUT_TOP1_ERRORS',
    f'ROWS_REFINED: {changed}',
    f'ROLLOUT_RANK_FLIPS: {flips}',
    'DEV_ROWS_REFINED: 0',
    'PRISTINE_DATA_USED: False',
    'XG_LABELS_USED: False',
])+'\n')
print(REPORT.read_text())
