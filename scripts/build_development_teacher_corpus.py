#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

BLOCKED_TOKENS = ("pristine", "blind")
SUPPORTED_SCHEMAS = {"mzand.xg.teacher-label.v2", "mzand.xg.teacher-reference.v1"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def confidence_pm(candidate):
    value = (candidate.get("confidence") or {}).get("plus_minus_equity")
    if value is None:
        value = candidate.get("confidence_pm")
    return None if value is None else float(value)


def rollout_rank(candidate):
    value = candidate.get("rollout_rank")
    return int(value) if value is not None else None


def reject_sensitive(path: Path, data):
    name = path.name.lower()
    if any(token in name for token in BLOCKED_TOKENS):
        raise ValueError(f"blocked benchmark token in teacher filename: {path.name}")
    for key in ("scope", "split", "dataset_split", "benchmark", "benchmark_name"):
        value = data.get(key)
        if isinstance(value, str) and any(token in value.lower() for token in BLOCKED_TOKENS):
            raise ValueError(f"blocked benchmark token in {path.name} field {key}: {value}")


def normalize_teacher(path: Path, data):
    schema = data.get("schema")
    if schema not in SUPPORTED_SCHEMAS:
        return None
    reject_sensitive(path, data)
    candidates = list(data.get("candidates") or [])
    if len(candidates) < 2:
        raise ValueError(f"teacher {path.name} has fewer than two candidates")
    if all(rollout_rank(candidate) is not None for candidate in candidates):
        candidates.sort(key=rollout_rank)
    else:
        candidates.sort(key=lambda candidate: float(candidate["equity"]), reverse=True)
    moves = [candidate["move"] for candidate in candidates]
    if len(moves) != len(set(moves)):
        raise ValueError(f"duplicate moves in {path.name}: {moves}")
    if data.get("best_move") and moves[0] != data["best_move"]:
        raise ValueError(f"best move mismatch in {path.name}: {moves[0]} != {data['best_move']}")
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Build a training-ready corpus from frozen non-pristine rollout teachers")
    parser.add_argument("references", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--margin", type=float, default=0.005)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    teacher_files = sorted(args.references.glob("*teacher.json"))
    if not teacher_files:
        raise SystemExit("no frozen teacher references found")

    positions = []
    candidate_rows = []
    decisive_pairs = []
    ambiguous_pairs = []
    seen_xgids = set()

    for path in teacher_files:
        data = load(path)
        candidates = normalize_teacher(path, data)
        if candidates is None:
            continue
        xgid = data.get("xgid")
        if not isinstance(xgid, str) or not xgid.startswith("XGID="):
            raise ValueError(f"missing XGID in {path.name}")
        if xgid in seen_xgids:
            raise ValueError(f"duplicate teacher XGID: {xgid}")
        seen_xgids.add(xgid)

        best_equity = float(candidates[0]["equity"])
        position = {
            "source_file": path.name,
            "scope": "non-pristine development teacher",
            "xgid": xgid,
            "candidate_count": len(candidates),
            "best_move": candidates[0]["move"],
            "best_equity": best_equity,
        }
        positions.append(position)

        for rank, candidate in enumerate(candidates, 1):
            games = candidate.get("rollout_games")
            if games is None:
                provenance = candidate.get("provenance", "")
                games = 1296 if "1296 Games rolled" in provenance else None
            candidate_rows.append(
                {
                    "scope": "non-pristine development teacher",
                    "source_file": path.name,
                    "xgid": xgid,
                    "target_rank": rank,
                    "move": candidate["move"],
                    "equity": float(candidate["equity"]),
                    "equity_delta_from_best": float(candidate["equity"]) - best_equity,
                    "confidence_pm": confidence_pm(candidate),
                    "rollout_games": games,
                    "original_analysis_rank": candidate.get("original_analysis_rank"),
                }
            )

        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                a, b = candidates[i], candidates[j]
                ea, eb = float(a["equity"]), float(b["equity"])
                ca, cb = confidence_pm(a), confidence_pm(b)
                gap = ea - eb
                threshold = None if ca is None or cb is None else ca + cb + args.margin
                record = {
                    "scope": "non-pristine development teacher",
                    "source_file": path.name,
                    "xgid": xgid,
                    "better_move": a["move"],
                    "worse_move": b["move"],
                    "equity_gap": gap,
                    "better_confidence_pm": ca,
                    "worse_confidence_pm": cb,
                    "decision_threshold": threshold,
                }
                if threshold is not None and gap > threshold:
                    record["label"] = 1
                    decisive_pairs.append(record)
                else:
                    record["reason"] = "confidence_missing" if threshold is None else "uncertainty_overlap_or_small_gap"
                    ambiguous_pairs.append(record)

    if not positions:
        raise SystemExit("no supported non-pristine teachers found")

    def write_jsonl(path: Path, rows):
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")

    write_jsonl(args.output_dir / "teacher_positions.jsonl", positions)
    write_jsonl(args.output_dir / "teacher_candidates.jsonl", candidate_rows)
    write_jsonl(args.output_dir / "teacher_decisive_pairs.jsonl", decisive_pairs)
    write_jsonl(args.output_dir / "teacher_ambiguous_pairs.jsonl", ambiguous_pairs)

    summary = {
        "schema": "mzand.xg.development-teacher-corpus.v1",
        "scope": "non-pristine development teachers only; explicitly excludes pristine/blind benchmark data",
        "teacher_position_count": len(positions),
        "candidate_row_count": len(candidate_rows),
        "decisive_pair_count": len(decisive_pairs),
        "ambiguous_pair_count": len(ambiguous_pairs),
        "confidence_margin": args.margin,
        "source_files": [position["source_file"] for position in positions],
        "xgids": [position["xgid"] for position in positions],
    }
    (args.output_dir / "teacher_corpus_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"teacher_positions={summary['teacher_position_count']}")
    print(f"candidate_rows={summary['candidate_row_count']}")
    print(f"decisive_pairs={summary['decisive_pair_count']}")
    print(f"ambiguous_pairs={summary['ambiguous_pair_count']}")
    print(f"source_files={summary['source_files']}")


if __name__ == "__main__":
    main()
