#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def confidence_pm(candidate):
    value = (candidate.get("confidence") or {}).get("plus_minus_equity")
    if value is None:
        value = candidate.get("confidence_pm")
    return None if value is None else float(value)


def teacher_items(data):
    items = list(data["teacher_candidates"])
    if all("rollout_rank" in item for item in items):
        return sorted(items, key=lambda item: int(item["rollout_rank"]))
    return sorted(items, key=lambda item: float(item["equity"]), reverse=True)


def screening_items(data):
    items = list(data["screening_candidates"])
    if all("screening_rank" in item for item in items):
        return sorted(items, key=lambda item: int(item["screening_rank"]))
    return sorted(items, key=lambda item: float(item["equity"]), reverse=True)


def sign(value, tolerance=0.0):
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def audit_position(path: Path, data, margin: float, screening_tie_tolerance: float):
    teacher = teacher_items(data)
    screening = screening_items(data)
    tmoves = [item["move"] for item in teacher]
    smoves = [item["move"] for item in screening]
    if set(tmoves) != set(smoves):
        raise ValueError(f"candidate set mismatch in {path}: teacher={tmoves} screening={smoves}")

    by_teacher = {item["move"]: item for item in teacher}
    by_screening = {item["move"]: item for item in screening}
    decisive_pairs = []
    ambiguous_pairs = []
    hard_reasons = []

    for i in range(len(tmoves)):
        for j in range(i + 1, len(tmoves)):
            a, b = tmoves[i], tmoves[j]
            ta, tb = by_teacher[a], by_teacher[b]
            ea, eb = float(ta["equity"]), float(tb["equity"])
            ca, cb = confidence_pm(ta), confidence_pm(tb)
            teacher_gap = abs(ea - eb)
            threshold = None if ca is None or cb is None else ca + cb + margin
            record = {
                "move_a": a,
                "move_b": b,
                "teacher_equity_a": ea,
                "teacher_equity_b": eb,
                "teacher_gap": teacher_gap,
                "teacher_confidence_pm_a": ca,
                "teacher_confidence_pm_b": cb,
                "decision_threshold": threshold,
            }
            if threshold is None or teacher_gap <= threshold:
                record["reason"] = "confidence_missing" if threshold is None else "teacher_uncertainty_overlap_or_small_gap"
                ambiguous_pairs.append(record)
                continue

            sa = float(by_screening[a]["equity"])
            sb = float(by_screening[b]["equity"])
            teacher_sign = sign(ea - eb)
            screening_sign = sign(sa - sb, screening_tie_tolerance)
            if screening_sign == 0:
                outcome = "screening_tie"
            elif screening_sign == teacher_sign:
                outcome = "correct"
            else:
                outcome = "wrong"
            record.update(
                {
                    "screening_equity_a": sa,
                    "screening_equity_b": sb,
                    "screening_gap": abs(sa - sb),
                    "outcome": outcome,
                }
            )
            decisive_pairs.append(record)
            if outcome != "correct":
                hard_reasons.append(f"decisive_pair_{outcome}:{a} vs {b}")

    top1_match = bool(data.get("top1_match", screening[0]["move"] == teacher[0]["move"]))
    if not top1_match:
        hard_reasons.append("top1_mismatch")

    best, second = teacher[:2]
    c1, c2 = confidence_pm(best), confidence_pm(second)
    top1_gap = float(best["equity"]) - float(second["equity"])
    top1_threshold = None if c1 is None or c2 is None else c1 + c2 + margin
    top1_teacher_decisive = top1_threshold is not None and top1_gap > top1_threshold

    method_mix = Counter()
    for candidate in screening:
        method = candidate.get("screening_method") or candidate.get("analysis_method") or "Unknown"
        method_mix[method] += 1

    decisive_correct = sum(pair["outcome"] == "correct" for pair in decisive_pairs)
    decisive_ties = sum(pair["outcome"] == "screening_tie" for pair in decisive_pairs)
    decisive_wrong = sum(pair["outcome"] == "wrong" for pair in decisive_pairs)
    decisive_accuracy = decisive_correct / len(decisive_pairs) if decisive_pairs else None

    return {
        "source_file": path.name,
        "xgid": data["xgid"],
        "teacher_best_move": teacher[0]["move"],
        "screening_best_move": screening[0]["move"],
        "top1_match": top1_match,
        "candidate_set_match": set(tmoves) == set(smoves),
        "candidate_count": len(tmoves),
        "teacher_top1_gap": top1_gap,
        "teacher_top1_decision_threshold": top1_threshold,
        "teacher_top1_decisive": top1_teacher_decisive,
        "decisive_pair_count": len(decisive_pairs),
        "decisive_pair_correct": decisive_correct,
        "decisive_pair_screening_ties": decisive_ties,
        "decisive_pair_wrong": decisive_wrong,
        "decisive_pair_accuracy": decisive_accuracy,
        "ambiguous_teacher_pair_count": len(ambiguous_pairs),
        "hard_position": bool(hard_reasons),
        "hard_reasons": hard_reasons,
        "screening_method_mix": dict(method_mix),
        "decisive_pairs": decisive_pairs,
        "ambiguous_teacher_pairs": ambiguous_pairs,
    }


def main():
    parser = argparse.ArgumentParser(description="Aggregate non-pristine development XGR++ coverage audits")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--margin", type=float, default=0.005)
    parser.add_argument("--screening-tie-tolerance", type=float, default=0.0005)
    args = parser.parse_args()

    files = sorted(args.input_dir.glob("xg-v*-coverage.json"))
    if not files:
        raise SystemExit("no frozen development coverage audits found")

    positions = []
    seen_xgids = set()
    for path in files:
        data = load(path)
        if data.get("schema") != "mzand.xg.screening-coverage-audit.v2":
            continue
        xgid = data.get("xgid")
        if xgid in seen_xgids:
            raise SystemExit(f"duplicate XGID in coverage corpus: {xgid}")
        seen_xgids.add(xgid)
        positions.append(audit_position(path, data, args.margin, args.screening_tie_tolerance))

    if not positions:
        raise SystemExit("no v2 coverage audits found")

    total_pairs = sum(p["decisive_pair_count"] for p in positions)
    correct_pairs = sum(p["decisive_pair_correct"] for p in positions)
    method_mix = Counter()
    for position in positions:
        method_mix.update(position["screening_method_mix"])

    top1_hits = sum(p["top1_match"] for p in positions)
    candidate_set_hits = sum(p["candidate_set_match"] for p in positions)
    hard_positions = [
        {"xgid": p["xgid"], "source_file": p["source_file"], "reasons": p["hard_reasons"]}
        for p in positions
        if p["hard_position"]
    ]
    result = {
        "schema": "mzand.xg.development-coverage-corpus.v1",
        "scope": "non-pristine development positions only; not a blind benchmark",
        "position_count": len(positions),
        "candidate_count": sum(p["candidate_count"] for p in positions),
        "top1_hits": top1_hits,
        "development_top1_accuracy": top1_hits / len(positions),
        "candidate_set_hits": candidate_set_hits,
        "candidate_set_accuracy": candidate_set_hits / len(positions),
        "teacher_top1_decisive_count": sum(p["teacher_top1_decisive"] for p in positions),
        "decisive_pair_count": total_pairs,
        "decisive_pair_correct": correct_pairs,
        "decisive_pair_accuracy": correct_pairs / total_pairs if total_pairs else None,
        "decisive_pair_screening_ties": sum(p["decisive_pair_screening_ties"] for p in positions),
        "decisive_pair_wrong": sum(p["decisive_pair_wrong"] for p in positions),
        "ambiguous_teacher_pair_count": sum(p["ambiguous_teacher_pair_count"] for p in positions),
        "screening_method_mix": dict(method_mix),
        "hard_position_count": len(hard_positions),
        "hard_positions": hard_positions,
        "confidence_margin": args.margin,
        "screening_tie_tolerance": args.screening_tie_tolerance,
        "positions": positions,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"development_positions={result['position_count']}")
    print(f"development_candidates={result['candidate_count']}")
    print(f"development_top1_accuracy={result['development_top1_accuracy']:.6f}")
    print(f"candidate_set_accuracy={result['candidate_set_accuracy']:.6f}")
    print(f"decisive_pair_accuracy={result['decisive_pair_accuracy']:.6f}")
    print(f"decisive_pairs={result['decisive_pair_correct']}/{result['decisive_pair_count']}")
    print(f"ambiguous_teacher_pairs={result['ambiguous_teacher_pair_count']}")
    print(f"hard_positions={result['hard_position_count']}")
    print(f"screening_method_mix={result['screening_method_mix']}")


if __name__ == "__main__":
    main()
