#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def rank_map(items, key="move"):
    return {item[key]: i + 1 for i, item in enumerate(items)}


def spearman_no_ties(xs, ys):
    n = len(xs)
    if n < 2:
        return 1.0
    d2 = sum((a - b) ** 2 for a, b in zip(xs, ys))
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def pairwise_order_accuracy(order_a, order_b, moves):
    ra, rb = rank_map(order_a), rank_map(order_b)
    good = total = 0
    for i in range(len(moves)):
        for j in range(i + 1, len(moves)):
            a, b = moves[i], moves[j]
            total += 1
            if (ra[a] < ra[b]) == (rb[a] < rb[b]):
                good += 1
    return good / total if total else 1.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input_dir", type=Path)
    p.add_argument("teacher", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    files = sorted(args.input_dir.rglob("xg-v18-candidate-*-xgrpp.json"))
    if len(files) != 5:
        raise SystemExit(f"expected 5 screening records, found {len(files)}")
    records = [load(f) for f in files]
    teacher = load(args.teacher)
    xgids = {r["xgid"] for r in records} | {teacher["xgid"]}
    if len(xgids) != 1:
        raise SystemExit(f"XGID mismatch: {xgids}")

    by_rank = {int(r["original_analysis_rank"]): r for r in records}
    if sorted(by_rank) != [1,2,3,4,5]:
        raise SystemExit(f"screening original ranks incomplete: {sorted(by_rank)}")
    sitems=[]
    method_mix={}
    reused_count=0
    for rank in range(1,6):
        r=by_rank[rank]; c=dict(r["candidate"])
        method=r.get("screening_method") or c.get("analysis_method")
        if method not in {"XG Roller++", "Rollout"}:
            raise SystemExit(f"rank {rank} screening method too weak: {method!r}")
        if method == "Rollout":
            provenance=c.get("provenance","")
            import re
            m=re.search(r"\b(\d+)\s+Games rolled\b", provenance, re.I)
            if not m or int(m.group(1)) < 1296:
                raise SystemExit(f"rank {rank} reused rollout is below 1296: {provenance!r}")
        method_mix[method]=method_mix.get(method,0)+1
        reused=bool(r.get("reused_existing",False))
        reused_count += int(reused)
        c["original_analysis_rank"]=rank
        c["screening_method"]=method
        c["screening_reused_existing"]=reused
        c["screening_elapsed_seconds"]=int(r.get("elapsed_seconds",0))
        sitems.append(c)
    sitems.sort(key=lambda c: float(c["equity"]), reverse=True)
    screening_best=float(sitems[0]["equity"])
    for i,c in enumerate(sitems,1):
        c["rank"]=i
        c["screening_rank"]=i
        c["equity_delta"]=round(float(c["equity"])-screening_best,6)
        c["source"]=c["screening_method"]
        c["analysis_method"]=c["screening_method"]

    titems=sorted((dict(c) for c in teacher["candidates"]), key=lambda c:int(c["rollout_rank"]))
    teacher_best=float(titems[0]["equity"])
    for i,c in enumerate(titems,1):
        c["rank"]=i
        c["rollout_rank"]=i
        c["equity_delta"]=round(float(c["equity"])-teacher_best,6)
        c["equity_delta_from_best"]=c["equity_delta"]
        c["source"]="Rollout"
        c["analysis_method"]="Rollout"

    tmoves=[c["move"] for c in titems]
    smoves=[c["move"] for c in sitems]
    if set(tmoves) != set(smoves):
        raise SystemExit(f"candidate set mismatch teacher={tmoves} screening={smoves}")
    sr=rank_map(sitems); tr=rank_map(titems)
    ss=[sr[m] for m in tmoves]; ts=[tr[m] for m in tmoves]
    out={
        "schema":"mzand.xg.screening-coverage-audit.v2",
        "xgid":teacher["xgid"],
        "screening_priority":"deep Rollout >=1296 > existing XG Roller++ > fresh XG Roller++",
        "teacher_best_move":teacher["best_move"],
        "screening_best_move":sitems[0]["move"],
        "top1_match":sitems[0]["move"]==teacher["best_move"],
        "candidate_set_match":True,
        "spearman_rank_correlation":spearman_no_ties(ss,ts),
        "pairwise_order_accuracy":pairwise_order_accuracy(sitems,titems,tmoves),
        "method_mix":method_mix,
        "reused_existing_count":reused_count,
        "fresh_xgrpp_count":method_mix.get("XG Roller++",0)-sum(1 for c in sitems if c["screening_method"]=="XG Roller++" and c["screening_reused_existing"]),
        "screening_candidates":sitems,
        "teacher_candidates":titems,
    }
    args.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(f"teacher_best_move={out['teacher_best_move']}")
    print(f"screening_best_move={out['screening_best_move']}")
    print(f"top1_match={out['top1_match']}")
    print(f"spearman_rank_correlation={out['spearman_rank_correlation']:.6f}")
    print(f"pairwise_order_accuracy={out['pairwise_order_accuracy']:.6f}")
    print(f"method_mix={out['method_mix']}")
    print(f"reused_existing_count={out['reused_existing_count']}")
    print(f"fresh_xgrpp_count={out['fresh_xgrpp_count']}")
    for c in sitems:
        print(f"screening_rank={c['screening_rank']} original_rank={c['original_analysis_rank']} move={c['move']} equity={c['equity']:+.6f} method={c['screening_method']} reused={c['screening_reused_existing']} elapsed={c['screening_elapsed_seconds']}s")


if __name__ == "__main__":
    main()
