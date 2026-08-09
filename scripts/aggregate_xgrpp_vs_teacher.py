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
        raise SystemExit(f"expected 5 XGR++ records, found {len(files)}")
    records = [load(f) for f in files]
    teacher = load(args.teacher)
    xgids = {r["xgid"] for r in records} | {teacher["xgid"]}
    if len(xgids) != 1:
        raise SystemExit(f"XGID mismatch: {xgids}")

    by_rank = {int(r["original_analysis_rank"]): r for r in records}
    if sorted(by_rank) != [1,2,3,4,5]:
        raise SystemExit(f"XGR++ original ranks incomplete: {sorted(by_rank)}")
    xitems=[]
    for rank in range(1,6):
        r=by_rank[rank]; c=dict(r["candidate"])
        if c.get("analysis_method") != "XG Roller++":
            raise SystemExit(f"rank {rank} method not XG Roller++: {c.get('analysis_method')}")
        c["original_analysis_rank"]=rank
        c["xgrpp_elapsed_seconds"]=int(r["elapsed_seconds"])
        xitems.append(c)
    xitems.sort(key=lambda c: float(c["equity"]), reverse=True)
    for i,c in enumerate(xitems,1): c["xgrpp_rank"]=i

    titems=sorted(teacher["candidates"], key=lambda c:int(c["rollout_rank"]))
    tmoves=[c["move"] for c in titems]
    xmoves=[c["move"] for c in xitems]
    if set(tmoves) != set(xmoves):
        raise SystemExit(f"candidate set mismatch teacher={tmoves} xgrpp={xmoves}")
    xr=rank_map(xitems); tr=rank_map(titems)
    xs=[xr[m] for m in tmoves]; ts=[tr[m] for m in tmoves]
    out={
        "schema":"mzand.xg.xgrpp-coverage-audit.v1",
        "xgid":teacher["xgid"],
        "teacher_best_move":teacher["best_move"],
        "xgrpp_best_move":xitems[0]["move"],
        "top1_match":xitems[0]["move"]==teacher["best_move"],
        "candidate_set_match":True,
        "spearman_rank_correlation":spearman_no_ties(xs,ts),
        "pairwise_order_accuracy":pairwise_order_accuracy(xitems,titems,tmoves),
        "xgrpp_candidates":xitems,
        "teacher_candidates":titems,
    }
    args.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(f"teacher_best_move={out['teacher_best_move']}")
    print(f"xgrpp_best_move={out['xgrpp_best_move']}")
    print(f"top1_match={out['top1_match']}")
    print(f"spearman_rank_correlation={out['spearman_rank_correlation']:.6f}")
    print(f"pairwise_order_accuracy={out['pairwise_order_accuracy']:.6f}")
    for c in xitems:
        print(f"xgrpp_rank={c['xgrpp_rank']} original_rank={c['original_analysis_rank']} move={c['move']} equity={c['equity']:+.6f} elapsed={c['xgrpp_elapsed_seconds']}s")


if __name__ == "__main__":
    main()
