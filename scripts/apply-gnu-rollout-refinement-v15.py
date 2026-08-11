#!/usr/bin/env python3
"""Refine GNU training rows with true rollouts of teacher-top vs the student's actual picked move.

Never touches dev, pristine, or XG-labelled rows.
"""
import json, os
from pathlib import Path

DATA=Path(os.environ.get('GNU_V15_BATCH_IN','gnu-teacher-v15.jsonl'))
SELECTED=Path(os.environ.get('GNU_V15_SELECTED','gnu-v15-selected.jsonl'))
EVIDENCE=Path(os.environ.get('GNU_V15_EVIDENCE','gnu-v15-rollout-evidence.json'))
OUT=Path(os.environ.get('GNU_V15_BATCH_OUT','gnu-teacher-v15-refined.jsonl'))
REPORT=Path('gnu-v15-refinement-report.txt')
rows=[json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
selected=[json.loads(x) for x in SELECTED.read_text().splitlines() if x.strip()]
ev_by_idx={int(x['sourceRowIndex']):x for x in json.loads(EVIDENCE.read_text())}
changed=flips=0
for s in selected:
    idx=int(s['sourceRowIndex']); split=s.get('sourceSplit'); picked=int(s['pickedRank'])
    if split not in ('train','tune') or s.get('pristine') is not False or s.get('xgLabelUsed') is not False:
        raise SystemExit(f'unsafe selected row {idx}')
    if picked<=1: raise SystemExit(f'not a Top-1 error row {idx}')
    row=rows[idx]
    if row.get('split') not in ('train','tune') or row.get('pristine') is not False or row.get('xgLabel') is not False:
        raise SystemExit(f'unsafe source row {idx}')
    ev=ev_by_idx.get(idx)
    if not ev or int(ev['pickedRank'])!=picked: raise SystemExit(f'evidence mismatch {idx}')
    hints=row.get('hints') or []
    top=next((h for h in hints if int(h.get('rank',999))==1),None)
    pick=next((h for h in hints if int(h.get('rank',999))==picked),None)
    if top is None or pick is None: raise SystemExit(f'missing compared candidates {idx}')
    et=float(ev['teacherTopEquity']); ep=float(ev['studentPickedEquity'])
    top['equity']=et; pick['equity']=ep
    top.setdefault('evaluation',{})['equity']=et; pick.setdefault('evaluation',{})['equity']=ep
    old_top_rank=int(top.get('rank',1)); old_pick_rank=int(pick.get('rank',picked))
    if ep>et:
        pick['rank']=1; top['rank']=2; flips+=1
        # shift any pre-existing ranks 2..picked-1 down one so ranks stay unique.
        for h in hints:
            if h is top or h is pick: continue
            r=int(h.get('rank',999))
            if 2<=r<picked: h['rank']=r+1
    else:
        top['rank']=1
        # Preserve the student's prior teacher rank; only the compared equities are authoritative.
        pick['rank']=old_pick_rank
    row['hints']=sorted(hints,key=lambda h:int(h.get('rank',999)))
    margin=abs(et-ep)
    row['teacher']='GNU Backgammon true rollout: teacher-top vs student-picked'
    row['teacherRolloutExecuted']=True
    row['rolloutTrials']=int(ev['trials'])
    row['rolloutRefinedRanks']=[old_top_rank,old_pick_rank]
    row['teacherMargin']=margin
    row['hard']=margin<0.03
    row['rolloutCandidate']=margin<0.012
    row['pristine']=False; row['xgLabel']=False
    changed+=1
OUT.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
REPORT.write_text('\n'.join([
    'REFINEMENT: GNU_TRUE_ROLLOUT_TEACHER_TOP_VS_STUDENT_PICK',
    f'ROWS_REFINED: {changed}',
    f'ROLLOUT_ORDER_FLIPS: {flips}',
    'DEV_ROWS_REFINED: 0','PRISTINE_DATA_USED: False','XG_LABELS_USED: False'])+'\n')
print(REPORT.read_text())
