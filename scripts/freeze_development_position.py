#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path

from compare_screening_label_to_teacher import (
    OUTPUT_SCHEMA,
    SCREENING_SCHEMA,
    TEACHER_SCHEMAS,
    load,
    pairwise_order_accuracy,
    reject_sensitive,
    screening_items,
    spearman_no_ties,
    teacher_items,
)

DEPTH_SCHEMA = "mzand.xg.rollout-depth-decision.v1"


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Freeze a decisive non-pristine teacher and its XGR++ coverage audit"
    )
    parser.add_argument("teacher_json", type=Path)
    parser.add_argument("depth_json", type=Path)
    parser.add_argument("screening_json", type=Path)
    parser.add_argument("teacher_output", type=Path)
    parser.add_argument("coverage_output", type=Path)
    parser.add_argument("--teacher-run-id", type=int)
    parser.add_argument("--teacher-commit")
    parser.add_argument("--teacher-artifact-id", type=int)
    parser.add_argument("--screening-run-id", type=int)
    parser.add_argument("--screening-commit")
    parser.add_argument("--screening-artifact-id", type=int)
    args = parser.parse_args()

    teacher = load(args.teacher_json)
    depth = load(args.depth_json)
    screening = load(args.screening_json)
    reject_sensitive(args.teacher_json, teacher)
    reject_sensitive(args.depth_json, depth)
    reject_sensitive(args.screening_json, screening)

    if teacher.get("schema") not in TEACHER_SCHEMAS:
        raise SystemExit(f"unsupported teacher schema: {teacher.get('schema')!r}")
    if depth.get("schema") != DEPTH_SCHEMA:
        raise SystemExit(f"unsupported depth schema: {depth.get('schema')!r}")
    if screening.get("schema") != SCREENING_SCHEMA:
        raise SystemExit(f"unsupported screening schema: {screening.get('schema')!r}")
    xgids = {teacher.get("xgid"), depth.get("xgid"), screening.get("xgid")}
    if len(xgids) != 1:
        raise SystemExit(f"XGID mismatch across evidence: {xgids}")
    scope = str(screening.get("scope") or "").lower()
    if "non-pristine" not in scope or "development" not in scope:
        raise SystemExit(f"screening scope must explicitly be non-pristine development: {screening.get('scope')!r}")

    titems = teacher_items(teacher)
    sitems = screening_items(screening)
    tmoves = [item["move"] for item in titems]
    smoves = [item["move"] for item in sitems]
    if set(tmoves) != set(smoves):
        raise SystemExit(f"candidate set mismatch: teacher={tmoves} screening={smoves}")

    current_games = int(depth.get("current_games") or 0)
    min_games = min(int(item["rollout_games"]) for item in titems)
    if current_games != min_games:
        raise SystemExit(f"depth/current rollout mismatch: depth={current_games} teacher_min={min_games}")
    if not bool(depth.get("accept_current_depth")):
        raise SystemExit(f"teacher is not decisive at {current_games} games: {depth.get('reason')}")
    threshold = depth.get("decision_threshold")
    gap = float(depth.get("gap") or 0.0)
    if threshold is None or gap <= float(threshold):
        raise SystemExit(f"teacher decisive flag is inconsistent: gap={gap} threshold={threshold}")
    if depth.get("best_move") != titems[0]["move"]:
        raise SystemExit(f"depth best move mismatch: {depth.get('best_move')} != {titems[0]['move']}")

    frozen_teacher = dict(teacher)
    frozen_teacher["candidates"] = titems
    frozen_teacher["candidate_count"] = len(titems)
    frozen_teacher["best_move"] = titems[0]["move"]
    frozen_teacher["best_equity"] = float(titems[0]["equity"])
    frozen_teacher["adaptive_depth"] = depth
    if args.teacher_run_id is not None:
        frozen_teacher["source_run_id"] = args.teacher_run_id
    if args.teacher_commit:
        frozen_teacher["source_commit"] = args.teacher_commit
    if args.teacher_artifact_id is not None:
        frozen_teacher["source_artifact_id"] = args.teacher_artifact_id

    method_mix = Counter(item["screening_method"] for item in sitems)
    declared_mix = screening.get("screening_method_mix")
    if declared_mix is not None and dict(method_mix) != {str(k): int(v) for k, v in declared_mix.items()}:
        raise SystemExit(f"screening method mix mismatch: candidates={dict(method_mix)} declared={declared_mix}")
    reused_count = int(screening.get("reused_existing_count", sum(bool(item.get("screening_reused_existing")) for item in sitems)))
    fresh_xgrpp_count = int(screening.get("fresh_xgrpp_count", sum(item["screening_method"] == "XG Roller++" and not bool(item.get("screening_reused_existing")) for item in sitems)))

    coverage = {
        "schema": OUTPUT_SCHEMA,
        "scope": "non-pristine development coverage audit; not a blind benchmark",
        "xgid": teacher["xgid"],
        "screening_priority": "deep Rollout >=1296 > existing XG Roller++ > fresh XG Roller++",
        "teacher_best_move": titems[0]["move"],
        "screening_best_move": sitems[0]["move"],
        "top1_match": sitems[0]["move"] == titems[0]["move"],
        "candidate_set_match": True,
        "spearman_rank_correlation": spearman_no_ties(sitems, titems, tmoves),
        "pairwise_order_accuracy": pairwise_order_accuracy(sitems, titems, tmoves),
        "method_mix": dict(method_mix),
        "reused_existing_count": reused_count,
        "fresh_xgrpp_count": fresh_xgrpp_count,
        "screening_candidates": sitems,
        "teacher_candidates": titems,
    }
    if args.screening_run_id is not None:
        coverage["source_run_id"] = args.screening_run_id
    if args.screening_commit:
        coverage["source_commit"] = args.screening_commit
    if args.screening_artifact_id is not None:
        coverage["source_artifact_id"] = args.screening_artifact_id
    if args.teacher_run_id is not None:
        coverage["teacher_source_run_id"] = args.teacher_run_id
    if args.teacher_commit:
        coverage["teacher_source_commit"] = args.teacher_commit
    if args.teacher_artifact_id is not None:
        coverage["teacher_source_artifact_id"] = args.teacher_artifact_id

    write_json(args.teacher_output, frozen_teacher)
    write_json(args.coverage_output, coverage)
    print(f"xgid={teacher['xgid']}")
    print(f"teacher_games={current_games}")
    print(f"teacher_best_move={coverage['teacher_best_move']}")
    print(f"screening_best_move={coverage['screening_best_move']}")
    print(f"top1_match={coverage['top1_match']}")
    print(f"candidate_set_match={coverage['candidate_set_match']}")
    print(f"spearman_rank_correlation={coverage['spearman_rank_correlation']:.6f}")
    print(f"pairwise_order_accuracy={coverage['pairwise_order_accuracy']:.6f}")


if __name__ == "__main__":
    main()
