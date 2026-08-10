#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from pathlib import Path

TEACHER_SCHEMAS = {"mzand.xg.teacher-label.v2", "mzand.xg.teacher-reference.v1"}
SCREENING_SCHEMA = "mzand.xg.screening-label.v1"
OUTPUT_SCHEMA = "mzand.xg.screening-coverage-audit.v2"
MIN_ROLLOUT_GAMES = 1296


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sensitive_token(text):
    value = str(text or "").lower()
    # Development artifacts deliberately use the phrase "non-pristine". Strip
    # that explicit allow-list phrase before checking for benchmark-sensitive words.
    value = value.replace("non-pristine", "").replace("non_pristine", "")
    if "pristine" in value:
        return "pristine"
    if re.search(r"\bblind\b", value):
        return "blind"
    return None


def reject_sensitive(path: Path, data):
    token = sensitive_token(path.name)
    if token:
        raise ValueError(f"blocked benchmark token {token!r} in filename: {path.name}")
    for key in ("scope", "split", "dataset_split", "benchmark", "benchmark_name"):
        value = data.get(key)
        if isinstance(value, str):
            token = sensitive_token(value)
            if token:
                raise ValueError(f"blocked benchmark token {token!r} in {path.name} field {key}: {value}")


def rollout_games(teacher, candidate):
    value = candidate.get("rollout_games")
    if value is not None:
        return int(value)
    texts = [
        str(candidate.get("provenance") or ""),
        str((teacher.get("teacher") or {}).get("label_method") or ""),
        str(teacher.get("teacher_method") or ""),
    ]
    for text in texts:
        match = re.search(r"\b(\d+)\s*(?:-game|Games rolled)\b", text, re.I)
        if match:
            return int(match.group(1))
    return None


def teacher_items(teacher):
    items = [dict(item) for item in teacher.get("candidates") or []]
    if len(items) < 2:
        raise ValueError("teacher has fewer than two candidates")
    if all(item.get("rollout_rank") is not None for item in items):
        items.sort(key=lambda item: int(item["rollout_rank"]))
    else:
        items.sort(key=lambda item: float(item["equity"]), reverse=True)
    moves = [item["move"] for item in items]
    if len(moves) != len(set(moves)):
        raise ValueError(f"duplicate teacher moves: {moves}")
    for rank, item in enumerate(items, 1):
        games = rollout_games(teacher, item)
        if games is None or games < MIN_ROLLOUT_GAMES:
            raise ValueError(f"teacher move {item.get('move')} below {MIN_ROLLOUT_GAMES} rollout games: {games}")
        item["rollout_games"] = games
        item["rollout_rank"] = rank
        item["rank"] = rank
        item["source"] = "Rollout"
        item["analysis_method"] = "Rollout"
    if teacher.get("best_move") and items[0]["move"] != teacher["best_move"]:
        raise ValueError(f"teacher best_move mismatch: {items[0]['move']} != {teacher['best_move']}")
    return items


def screening_items(screening):
    items = [dict(item) for item in screening.get("candidates") or []]
    if len(items) < 2:
        raise ValueError("screening has fewer than two candidates")
    if all(item.get("screening_rank") is not None for item in items):
        items.sort(key=lambda item: int(item["screening_rank"]))
    else:
        items.sort(key=lambda item: float(item["equity"]), reverse=True)
    moves = [item["move"] for item in items]
    if len(moves) != len(set(moves)):
        raise ValueError(f"duplicate screening moves: {moves}")
    best_equity = float(items[0]["equity"])
    for rank, item in enumerate(items, 1):
        method = item.get("screening_method") or item.get("analysis_method") or item.get("source")
        if method not in {"XG Roller++", "Rollout"}:
            raise ValueError(f"screening move {item.get('move')} has unsupported method: {method!r}")
        item["screening_method"] = method
        item["screening_rank"] = rank
        item["rank"] = rank
        item["source"] = method
        item["analysis_method"] = method
        item["equity_delta"] = round(float(item["equity"]) - best_equity, 6)
    if screening.get("best_move") and items[0]["move"] != screening["best_move"]:
        raise ValueError(f"screening best_move mismatch: {items[0]['move']} != {screening['best_move']}")
    return items


def rank_map(items):
    return {item["move"]: index + 1 for index, item in enumerate(items)}


def spearman_no_ties(order_a, order_b, moves):
    n = len(moves)
    if n < 2:
        return 1.0
    ra, rb = rank_map(order_a), rank_map(order_b)
    d2 = sum((ra[move] - rb[move]) ** 2 for move in moves)
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def pairwise_order_accuracy(order_a, order_b, moves):
    ra, rb = rank_map(order_a), rank_map(order_b)
    correct = total = 0
    for i in range(len(moves)):
        for j in range(i + 1, len(moves)):
            a, b = moves[i], moves[j]
            total += 1
            correct += int((ra[a] < ra[b]) == (rb[a] < rb[b]))
    return correct / total if total else 1.0


def main():
    parser = argparse.ArgumentParser(
        description="Compare an aggregated non-pristine XGR++ screening label with a rollout teacher"
    )
    parser.add_argument("screening_json", type=Path)
    parser.add_argument("teacher_json", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()

    screening = load(args.screening_json)
    teacher = load(args.teacher_json)
    reject_sensitive(args.screening_json, screening)
    reject_sensitive(args.teacher_json, teacher)

    if screening.get("schema") != SCREENING_SCHEMA:
        raise SystemExit(f"unsupported screening schema: {screening.get('schema')!r}")
    if teacher.get("schema") not in TEACHER_SCHEMAS:
        raise SystemExit(f"unsupported teacher schema: {teacher.get('schema')!r}")
    scope = str(screening.get("scope") or "").lower()
    if "non-pristine" not in scope or "development" not in scope:
        raise SystemExit(f"screening scope must explicitly be non-pristine development: {screening.get('scope')!r}")
    if screening.get("xgid") != teacher.get("xgid"):
        raise SystemExit(f"XGID mismatch: screening={screening.get('xgid')} teacher={teacher.get('xgid')}")

    sitems = screening_items(screening)
    titems = teacher_items(teacher)
    smoves = [item["move"] for item in sitems]
    tmoves = [item["move"] for item in titems]
    if set(smoves) != set(tmoves):
        raise SystemExit(f"candidate set mismatch: screening={smoves} teacher={tmoves}")

    method_mix = Counter(item["screening_method"] for item in sitems)
    declared_mix = screening.get("screening_method_mix")
    if declared_mix is not None and dict(method_mix) != {str(k): int(v) for k, v in declared_mix.items()}:
        raise SystemExit(f"screening method mix mismatch: candidates={dict(method_mix)} declared={declared_mix}")

    reused_count = int(screening.get("reused_existing_count", sum(bool(item.get("screening_reused_existing")) for item in sitems)))
    fresh_xgrpp_count = int(
        screening.get(
            "fresh_xgrpp_count",
            sum(item["screening_method"] == "XG Roller++" and not bool(item.get("screening_reused_existing")) for item in sitems),
        )
    )

    result = {
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
        "teacher_min_rollout_games": min(item["rollout_games"] for item in titems),
        "screening_candidates": sitems,
        "teacher_candidates": titems,
    }
    for key in ("source_run_id", "source_commit", "source_artifact_id"):
        if key in screening:
            result[key] = screening[key]
    if "source_run_id" in teacher:
        result["teacher_source_run_id"] = teacher["source_run_id"]
    if "source_artifact_id" in teacher:
        result["teacher_source_artifact_id"] = teacher["source_artifact_id"]

    args.output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"xgid={result['xgid']}")
    print(f"teacher_best_move={result['teacher_best_move']}")
    print(f"screening_best_move={result['screening_best_move']}")
    print(f"top1_match={result['top1_match']}")
    print(f"candidate_set_match={result['candidate_set_match']}")
    print(f"spearman_rank_correlation={result['spearman_rank_correlation']:.6f}")
    print(f"pairwise_order_accuracy={result['pairwise_order_accuracy']:.6f}")
    print(f"teacher_min_rollout_games={result['teacher_min_rollout_games']}")


if __name__ == "__main__":
    main()
