#!/usr/bin/env python3
import argparse, csv, json, math
from pathlib import Path

NUM_FIELDS = [
    'player_win_nd','player_gammon_nd','player_backgammon_nd',
    'player_win_dt','player_gammon_dt','player_backgammon_dt',
    'cubeless_equity_nd','cubeless_equity_dt',
    'no_double_equity','double_take_equity','double_pass_equity',
]

def load_jsonl(p):
    rows={}
    for line in Path(p).read_text(encoding='utf-8-sig').splitlines():
        if not line.strip(): continue
        r=json.loads(line); rows[r['case_id']]=r
    return rows

def norm_action(s):
    if s is None: return None
    s=' '.join(str(s).upper().replace('_',' ').replace('-',' ').split())
    aliases={
        'NO DOUBLE':'NO_DOUBLE', 'NO DOUBLE / TAKE':'NO_DOUBLE',
        'DOUBLE TAKE':'DOUBLE_TAKE', 'DOUBLE / TAKE':'DOUBLE_TAKE',
        'DOUBLE PASS':'DOUBLE_PASS', 'DOUBLE / PASS':'DOUBLE_PASS',
        'TOO GOOD TO DOUBLE / PASS':'TOO_GOOD_PASS',
        'TOO GOOD TO DOUBLE PASS':'TOO_GOOD_PASS',
        'TOO GOOD TO DOUBLE / TAKE':'TOO_GOOD_TAKE',
    }
    return aliases.get(s, s.replace(' ','_'))

def classify_diff(d, tight, close):
    if d <= tight: return 'PARITY_PROVEN'
    if d <= close: return 'CLOSE_BUT_NOT_PROVEN'
    return 'MISMATCH'

def main():
    ap=argparse.ArgumentParser(description='Compare standardized Zand parity JSONL against XG oracle JSONL.')
    ap.add_argument('--xg', required=True)
    ap.add_argument('--zand', required=True, help='JSONL with case_id and XG-space normalized equity/probability keys')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--prob-tight', type=float, default=1e-5)
    ap.add_argument('--prob_close', type=float, default=5e-4)
    ap.add_argument('--eq-tight', type=float, default=1e-5)
    ap.add_argument('--eq_close', type=float, default=5e-4)
    args=ap.parse_args()
    xg=load_jsonl(args.xg); zd=load_jsonl(args.zand)
    out=Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    details=[]; case_summ=[]
    for cid,x in xg.items():
        z=zd.get(cid)
        counts={'PARITY_PROVEN':0,'CLOSE_BUT_NOT_PROVEN':0,'MISMATCH':0,'MISSING':0}
        for field in NUM_FIELDS:
            xv=x.get(field); zv=None if z is None else z.get(field)
            if xv is None or zv is None:
                status='MISSING'; diff=None
            else:
                try: diff=abs(float(xv)-float(zv))
                except Exception: diff=math.inf
                is_prob='win_' in field or 'gammon_' in field or 'backgammon_' in field
                status=classify_diff(diff, args.prob_tight if is_prob else args.eq_tight, args.prob_close if is_prob else args.eq_close)
            counts[status]+=1
            details.append({'case_id':cid,'field':field,'xg':xv,'zand':zv,'abs_diff':diff,'status':status})
        xa=norm_action(x.get('best_cube_action')); za=norm_action(None if z is None else z.get('best_cube_action', z.get('action')))
        astat='MISSING' if xa is None or za is None else ('PARITY_PROVEN' if xa==za else 'MISMATCH')
        counts[astat]+=1
        details.append({'case_id':cid,'field':'best_cube_action','xg':xa,'zand':za,'abs_diff':None,'status':astat})
        overall='PARITY_PROVEN'
        if counts['MISMATCH']: overall='MISMATCH'
        elif counts['MISSING']: overall='INCOMPLETE'
        elif counts['CLOSE_BUT_NOT_PROVEN']: overall='CLOSE_BUT_NOT_PROVEN'
        case_summ.append({'case_id':cid,'overall':overall,**counts})

    with (out/'parity_report.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['case_id','field','xg','zand','abs_diff','status']);w.writeheader();w.writerows(details)
    (out/'parity_report.json').write_text(json.dumps({'details':details,'cases':case_summ},indent=2)+'\n',encoding='utf-8')
    summary={
        'schema':'zand-xg-cube-parity-report-v1',
        'cases_total':len(case_summ),
        'cases_parity_proven':sum(c['overall']=='PARITY_PROVEN' for c in case_summ),
        'cases_close':sum(c['overall']=='CLOSE_BUT_NOT_PROVEN' for c in case_summ),
        'cases_mismatch':sum(c['overall']=='MISMATCH' for c in case_summ),
        'cases_incomplete':sum(c['overall']=='INCOMPLETE' for c in case_summ),
        'warning':'Only compare standardized Zand values converted into the same normalized-equity/probability space as the XG oracle. MWC is not normalized equity.',
    }
    (out/'parity_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
