#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: compare_xgrpp_to_teacher.py <xgrpp.json> <teacher.json> <out.json>")
    xgrpp_path, teacher_path, out_path = map(Path, sys.argv[1:])
    xgrpp = json.loads(xgrpp_path.read_text(encoding="utf-8-sig"))
    teacher = json.loads(teacher_path.read_text(encoding="utf-8-sig"))
    if xgrpp.get("xgid") != teacher.get("xgid"):
        raise SystemExit(f"XGID mismatch: xgrpp={xgrpp.get('xgid')} teacher={teacher.get('xgid')}")
    candidates = xgrpp.get("candidates") or []
    if not candidates:
        raise SystemExit("XGR++ parsed export has no candidates")
    top = candidates[0]
    top_move = top.get("move")
    expected = teacher["best_move"]
    teacher_moves = [c["move"] for c in teacher["candidates"]]
    teacher_rank = teacher_moves.index(top_move) + 1 if top_move in teacher_moves else None
    result = {
        "schema": "mzand.xg.xgrpp-teacher-comparison.v1",
        "xgid": xgrpp["xgid"],
        "xgrpp_top_move": top_move,
        "xgrpp_top_equity": top.get("equity"),
        "xgrpp_analysis_method": top.get("analysis_method"),
        "xgrpp_provenance": top.get("provenance"),
        "teacher_best_move": expected,
        "teacher_best_equity": teacher["best_equity"],
        "top1_match": top_move == expected,
        "xgrpp_top_teacher_rank": teacher_rank,
        "teacher_top5_coverage": all(m in [c.get("move") for c in candidates] for m in teacher_moves),
        "xgrpp_candidate_count": len(candidates),
        "teacher_candidate_count": len(teacher_moves),
    }
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"xgrpp_top_move={top_move}")
    print(f"teacher_best_move={expected}")
    print(f"top1_match={result['top1_match']}")
    print(f"xgrpp_top_teacher_rank={teacher_rank}")
    print(f"teacher_top5_coverage={result['teacher_top5_coverage']}")
    print(f"xgrpp_candidate_count={len(candidates)}")
    if top.get("analysis_method") != "XG Roller++":
        raise SystemExit(f"expected XG Roller++ top analysis method, got {top.get('analysis_method')!r}")


if __name__ == "__main__":
    main()
