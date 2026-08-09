#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description="Aggregate five generic XGR++ screening records")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    files = sorted(args.input_dir.rglob("xg-v18-candidate-*-xgrpp.json"))
    if len(files) != 5:
        raise SystemExit(f"expected 5 XGR++ records, found {len(files)}")

    records = [load(path) for path in files]
    xgids = {record["xgid"] for record in records}
    if len(xgids) != 1:
        raise SystemExit(f"screening records disagree on XGID: {sorted(xgids)}")

    ranks = sorted(int(record["original_analysis_rank"]) for record in records)
    if ranks != [1, 2, 3, 4, 5]:
        raise SystemExit(f"original analysis ranks must be 1..5, got {ranks}")

    candidates = []
    methods = Counter()
    for record in records:
        candidate = dict(record["candidate"])
        candidate["original_analysis_rank"] = int(record["original_analysis_rank"])
        candidate["screening_method"] = record["screening_method"]
        candidate["screening_reused_existing"] = bool(record["reused_existing"])
        candidate["screening_elapsed_seconds"] = int(record["elapsed_seconds"])
        candidates.append(candidate)
        methods[record["screening_method"]] += 1

    moves = [candidate["move"] for candidate in candidates]
    if len(moves) != len(set(moves)):
        raise SystemExit(f"duplicate screened moves: {moves}")

    candidates.sort(key=lambda candidate: (-float(candidate["equity"]), int(candidate["original_analysis_rank"])))
    for rank, candidate in enumerate(candidates, 1):
        candidate["screening_rank"] = rank

    result = {
        "schema": "mzand.xg.screening-label.v1",
        "scope": "non-pristine development position",
        "xgid": records[0]["xgid"],
        "candidate_count": len(candidates),
        "best_move": candidates[0]["move"],
        "best_equity": float(candidates[0]["equity"]),
        "second_move": candidates[1]["move"],
        "second_equity": float(candidates[1]["equity"]),
        "top1_gap": float(candidates[0]["equity"]) - float(candidates[1]["equity"]),
        "screening_method_mix": dict(methods),
        "reused_existing_count": sum(bool(record["reused_existing"]) for record in records),
        "fresh_xgrpp_count": sum(record["screening_method"] == "XG Roller++" and not bool(record["reused_existing"]) for record in records),
        "candidates": candidates,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"xgid={result['xgid']}")
    print(f"best_move={result['best_move']}")
    print(f"best_equity={result['best_equity']:+.3f}")
    print(f"top1_gap={result['top1_gap']:+.3f}")
    print(f"method_mix={result['screening_method_mix']}")
    for candidate in candidates:
        print(
            f"screening_rank={candidate['screening_rank']} original_rank={candidate['original_analysis_rank']} "
            f"move={candidate['move']} equity={candidate['equity']:+.3f} method={candidate['screening_method']}"
        )


if __name__ == "__main__":
    main()
