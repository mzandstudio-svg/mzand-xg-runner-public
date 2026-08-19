#!/usr/bin/env python3
import argparse
import json
import math
import re
from pathlib import Path


def load_json(path):
    # PowerShell Out-File may emit a UTF-8 BOM on Windows runners.
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def norm_move(s: str) -> str:
    return " ".join((s or "").split()).upper()


def decode_xgid(xgid: str):
    s=xgid[5:] if xgid.startswith("XGID=") else xgid
    parts=s.split(":")
    if len(parts)!=10 or len(parts[0])!=26:
        raise ValueError("unexpected XGID shape")
    pos=parts[0]
    f=[int(x) for x in parts[1:]]
    own=[0]*25
    opp=[0]*25
    def count(c): return ord(c.lower())-ord('a')+1
    for i in range(1,25):
        c=pos[i]
        if c=='-':
            continue
        if c.islower(): own[24-i]=count(c)
        else: opp[i-1]=count(c)
    for idx in (25,0):
        c=pos[idx]
        if c=='-':
            continue
        if c.islower(): own[24]=count(c)
        else: opp[24]=count(c)
    if f[2]==-1:
        own,opp=opp,own
    return own,opp


def final_board_signature(xgid: str, notation: str):
    own,opp=decode_xgid(xgid)
    off=15-sum(own)
    expanded=[]
    for token in notation.split():
        m=re.fullmatch(r"([^()]+)(?:\((\d+)\))?",token)
        if not m:
            raise ValueError(f"bad move token {token}")
        expanded.extend([m.group(1)]*int(m.group(2) or 1))
    for token in expanded:
        starred='*' in token
        token=token.replace('*','')
        if '/' not in token:
            raise ValueError(f"bad move token {token}")
        a,b=token.split('/',1)
        if a.lower()=='bar':
            if own[24]<=0: raise ValueError("move from empty bar")
            own[24]-=1
        else:
            fr=int(a)
            if not 1<=fr<=24 or own[fr-1]<=0: raise ValueError(f"bad from point {fr}")
            own[fr-1]-=1
        if b.lower()=='off':
            off+=1
            continue
        to=int(b)
        if not 1<=to<=24: raise ValueError(f"bad to point {to}")
        oi=24-to
        # Infer hits from the actual board; '*' is only presentation metadata.
        if opp[oi]==1:
            opp[oi]=0
            opp[24]+=1
        elif starred:
            raise ValueError("hit marker without opponent blot")
        own[to-1]+=1
    return tuple(own),tuple(opp),off


def candidates(obj):
    rows=obj.get("candidates") or obj.get("moves") or []
    xgid=obj.get("xgid") or obj.get("XGID")
    out=[]
    for i,row in enumerate(rows):
        move=row.get("move") or row.get("notation") or ""
        eq=row.get("equity")
        if eq is None:
            eq=row.get("context_value")
        sig=None
        if xgid and move:
            try:
                sig=final_board_signature(xgid,move)
            except Exception:
                sig=None
        out.append({
            "rank": int(row.get("rank",i+1)),
            "move": norm_move(move),
            "equity": None if eq is None else float(eq),
            "signature": sig,
            # MZand rank/search scores are not automatically on XG's normalized
            # equity scale.  Only compare numeric equity when the producer marks
            # that value as comparable (e.g. exact local Book records).
            "equity_comparable": bool(row.get("equity_comparable_to_xg",obj.get("equity_comparable_to_xg",False))),
        })
    return out


def candidate_key(row):
    if row["signature"] is not None:
        return ("board",row["signature"])
    return ("text",row["move"])


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("xg")
    ap.add_argument("mzand")
    ap.add_argument("--out",default="gt724-xg-diff.json")
    args=ap.parse_args()
    xg=load_json(args.xg)
    mz=load_json(args.mzand)
    xr,mr=candidates(xg),candidates(mz)
    if not xr or not mr:
        raise SystemExit("both labels must contain candidates/moves")
    xmap={candidate_key(r):r for r in xr}
    mmap={candidate_key(r):r for r in mr}
    shared=set(xmap)&set(mmap)
    top1=candidate_key(xr[0])==candidate_key(mr[0])
    top2=candidate_key(mr[0]) in {candidate_key(r) for r in xr[:2]}
    top5=candidate_key(mr[0]) in {candidate_key(r) for r in xr[:5]}
    deltas=[]
    for k in shared:
        a,b=xmap[k],mmap[k]
        if not b["equity_comparable"]:
            continue
        if a["equity"] is not None and b["equity"] is not None and math.isfinite(a["equity"]) and math.isfinite(b["equity"]):
            deltas.append(abs(a["equity"]-b["equity"]))
    report={
        "schema":"gt724.xg.differential.v2",
        "comparison_key":"final-board when XGID is available; notation fallback otherwise",
        "xg_top1":xr[0]["move"],
        "mzand_top1":mr[0]["move"],
        "top1_agree":top1,
        "mzand_top1_in_xg_top2":top2,
        "mzand_top1_in_xg_top5":top5,
        "shared_final_boards":len(shared),
        "comparable_equity_rows":len(deltas),
        "shared_equity_mae":(sum(deltas)/len(deltas)) if deltas else None,
        "shared_equity_max_abs":max(deltas) if deltas else None,
    }
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
