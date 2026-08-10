#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-games", type=int, default=1296)
    args = parser.parse_args()
    if args.expected_games <= 0:
        raise SystemExit("expected games must be positive")

    files = sorted(args.input_dir.rglob("xg-v16-candidate-*-rollout.json"))
    if len(files) != 5:
        raise SystemExit(f"expected 5 rollout candidate files, found {len(files)}: {files}")

    records = [load(p) for p in files]
    xgids = {r["xgid"] for r in records}
    if len(xgids) != 1:
        raise SystemExit(f"candidate XGIDs disagree: {xgids}")

    by_original_rank = {}
    moves = set()
    for record in records:
        rank = int(record["original_rank"])
        if rank in by_original_rank:
            raise SystemExit(f"duplicate original rank {rank}")
        games = int(record["rollout_games"])
        if games != args.expected_games:
            raise SystemExit(
                f"rank {rank} rollout games mismatch: got {games}, expected {args.expected_games}"
            )
        candidate = record["candidate"]
        if candidate.get("analysis_method") != "Rollout":
            raise SystemExit(f"rank {rank} method is not Rollout")
        provenance = candidate.get("provenance", "")
        if not re.search(rf"\b{args.expected_games}\s+Games rolled\b", provenance, re.I):
            raise SystemExit(
                f"rank {rank} lacks completed {args.expected_games} provenance: {provenance!r}"
            )
        move = candidate["move"]
        if move in moves:
            raise SystemExit(f"duplicate move across candidate rollouts: {move}")
        moves.add(move)
        by_original_rank[rank] = record

    if sorted(by_original_rank) != [1, 2, 3, 4, 5]:
        raise SystemExit(f"original ranks incomplete: {sorted(by_original_rank)}")

    rolled = []
    for rank in range(1, 6):
        record = by_original_rank[rank]
        item = dict(record["candidate"])
        item["original_analysis_rank"] = rank
        item["rollout_games"] = args.expected_games
        item["checker_preset"] = record["checker_preset"]
        item["cube_preset"] = record["cube_preset"]
        item["variance_reduction"] = bool(record["variance_reduction"])
        item["elapsed_seconds"] = int(record["elapsed_seconds"])
        rolled.append(item)

    rolled.sort(key=lambda x: x["equity"], reverse=True)
    best_equity = rolled[0]["equity"]
    for i, item in enumerate(rolled, start=1):
        delta = round(item["equity"] - best_equity, 6)
        # Candidate exports preserve the row rank and equity delta from the
        # pre-rollout Analyze Position table. Once five independent rollouts
        # are merged, those fields are stale and can even contain duplicate
        # ranks. Canonical teacher labels must describe rollout ordering.
        item["rank"] = i
        item["source"] = "Rollout"
        item["analysis_method"] = "Rollout"
        item["equity_delta"] = delta
        item["rollout_rank"] = i
        item["equity_delta_from_best"] = delta

    first = records[0]
    out = {
        "schema": "mzand.xg.teacher-label.v2",
        "xgid": first["xgid"],
        "xgid_payload": first["xgid_payload"],
        "score": first["score"],
        "cube": first["cube"],
        "on_roll": first["on_roll"],
        "dice": first["dice"],
        "xg_version": first.get("xg_version"),
        "teacher": {
            "candidate_generation": "XG Analyze Position Top-5",
            "label_method": f"Independent {args.expected_games}-game rollout per candidate",
            "rollout_games": args.expected_games,
            "checker_preset": "Moves 3-ply",
            "cube_preset": "XG Roller",
            "variance_reduction": True,
        },
        "candidate_count": 5,
        "best_move": rolled[0]["move"],
        "best_equity": rolled[0]["equity"],
        "candidates": rolled,
    }
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"xgid={out['xgid']}")
    print(f"rollout_games={args.expected_games}")
    print(f"best_move={out['best_move']}")
    print(f"best_equity={out['best_equity']:+.6f}")
    for c in rolled:
        conf = c.get("confidence", {}).get("plus_minus_equity")
        print(
            f"rank={c['rollout_rank']} original_rank={c['original_analysis_rank']} "
            f"move={c['move']} equity={c['equity']:+.6f} delta={c['equity_delta_from_best']:+.6f} "
            f"confidence_pm={conf}"
        )


if __name__ == "__main__":
    main()
