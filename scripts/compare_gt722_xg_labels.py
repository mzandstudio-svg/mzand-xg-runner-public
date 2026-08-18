#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path


def norm_move(s: str) -> str:
    return " ".join((s or "").replace("*", "").split()).upper()


def candidates(obj):
    rows = obj.get("candidates") or obj.get("moves") or []
    out = []
    for i, row in enumerate(rows):
        move = row.get("move") or row.get("notation") or ""
        eq = row.get("equity")
        if eq is None:
            eq = row.get("context_value")
        out.append({
            "rank": int(row.get("rank", i + 1)),
            "move": norm_move(move),
            "equity": None if eq is None else float(eq),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xg")
    ap.add_argument("mzand")
    ap.add_argument("--out", default="gt722-xg-diff.json")
    args = ap.parse_args()
    xg = json.loads(Path(args.xg).read_text())
    mz = json.loads(Path(args.mzand).read_text())
    xr, mr = candidates(xg), candidates(mz)
    if not xr or not mr:
        raise SystemExit("both labels must contain candidates/moves")
    xmap = {r["move"]: r for r in xr}
    mmap = {r["move"]: r for r in mr}
    shared = sorted(set(xmap) & set(mmap))
    top1 = xr[0]["move"] == mr[0]["move"]
    top2 = mr[0]["move"] in {r["move"] for r in xr[:2]}
    top5 = mr[0]["move"] in {r["move"] for r in xr[:5]}
    deltas = []
    for move in shared:
        a, b = xmap[move]["equity"], mmap[move]["equity"]
        if a is not None and b is not None and math.isfinite(a) and math.isfinite(b):
            deltas.append(abs(a-b))
    report = {
        "schema": "gt722.xg.differential.v1",
        "xg_top1": xr[0]["move"],
        "mzand_top1": mr[0]["move"],
        "top1_agree": top1,
        "mzand_top1_in_xg_top2": top2,
        "mzand_top1_in_xg_top5": top5,
        "shared_moves": len(shared),
        "shared_equity_mae": (sum(deltas)/len(deltas)) if deltas else None,
        "shared_equity_max_abs": max(deltas) if deltas else None,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
