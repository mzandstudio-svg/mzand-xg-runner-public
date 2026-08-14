#!/usr/bin/env python3
import argparse, csv, json, re
from pathlib import Path

PCT = r'([+-]?\d+(?:\.\d+)?)%'
NUM = r'([+-]?\d+(?:\.\d+)?)'

def f(x):
    return None if x is None else float(x)

def parse_chances(text, label):
    # Handles one or two evaluation columns, e.g.
    # Player Winning Chances: 73.18% (G:51.87% B:0.60%) 73.19% (G:52.39% B:0.59%)
    pat = rf'{re.escape(label)}\s*Winning Chances:\s*{PCT}\s*\(G:{PCT}\s*B:{PCT}\)(?:\s*{PCT}\s*\(G:{PCT}\s*B:{PCT}\))?'
    m = re.search(pat, text, re.I | re.S)
    if not m:
        return [None] * 6
    vals = list(m.groups())
    return [f(v) / 100.0 if v is not None else None for v in vals]

def grab(text, pat):
    m = re.search(pat, text, re.I | re.M)
    return f(m.group(1)) if m else None

def parse_case(meta, text):
    p = parse_chances(text, 'Player')
    o = parse_chances(text, 'Opponent')
    cubeless = re.search(r'Cubeless Equities\s*' + NUM + r'(?:\s+' + NUM + r')?', text, re.I)
    best = re.search(r'^\s*Best Cube action:\s*(.+?)\s*$', text, re.I | re.M)
    source = re.search(r'Analyzed in\s+(.+?)\s+(?:No double|Double/Take|Double/Pass)', text, re.I)
    wrong_take = re.search(r'Percentage of wrong take needed to make the double decision right:\s*' + PCT, text, re.I)

    row = {
        **meta,
        'analysis_source': source.group(1).strip() if source else None,
        'player_win_nd': p[0], 'player_gammon_nd': p[1], 'player_backgammon_nd': p[2],
        'player_win_dt': p[3], 'player_gammon_dt': p[4], 'player_backgammon_dt': p[5],
        'opp_win_nd': o[0], 'opp_gammon_nd': o[1], 'opp_backgammon_nd': o[2],
        'opp_win_dt': o[3], 'opp_gammon_dt': o[4], 'opp_backgammon_dt': o[5],
        'cubeless_equity_nd': f(cubeless.group(1)) if cubeless else None,
        'cubeless_equity_dt': f(cubeless.group(2)) if cubeless and cubeless.lastindex and cubeless.lastindex >= 2 and cubeless.group(2) is not None else None,
        'no_double_equity': grab(text, r'No double:\s*' + NUM),
        'double_take_equity': grab(text, r'Double/Take:\s*' + NUM),
        'double_pass_equity': grab(text, r'Double/Pass:\s*' + NUM),
        'best_cube_action': best.group(1).strip() if best else None,
        'wrong_take_needed': f(wrong_take.group(1)) / 100.0 if wrong_take else None,
        'raw_has_cube_section': bool(re.search(r'Cubeful Equities|Best Cube action:', text, re.I)),
        'raw_length': len(text),
    }
    required = ['no_double_equity', 'best_cube_action']
    row['parse_complete'] = all(row.get(k) is not None for k in required)
    return row

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', required=True)
    ap.add_argument('--raw-dir', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding='utf-8-sig'))
    raw_dir = Path(args.raw_dir)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cases:
        p = raw_dir / f"{c['case_id']}.txt"
        text = p.read_text(encoding='utf-8-sig', errors='replace') if p.exists() else ''
        meta = {k: c[k] for k in ['case_id','group','xgid','match_length','score_self','score_opp','crawford','cube_value','cube_owner']}
        rows.append(parse_case(meta, text))

    (out/'xg-oracle.jsonl').write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows), encoding='utf-8')
    fields = list(rows[0].keys()) if rows else []
    with (out/'xg-oracle.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
    summary = {
        'schema':'zand-xg-cube-parity-oracle-v1',
        'requested':len(rows),
        'raw_cube_sections':sum(bool(r['raw_has_cube_section']) for r in rows),
        'parse_complete':sum(bool(r['parse_complete']) for r in rows),
        'training_eligible':False,
        'purpose':'runtime differential parity only',
        'numeric_space':'XG exported normalized equity/probability space; do not compare to MWC fields without conversion',
    }
    (out/'oracle-summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
