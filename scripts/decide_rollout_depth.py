#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

LEVELS = (1296, 5184, 10368, 20736, 46656)


def confidence_pm(candidate):
    value = (candidate.get("confidence") or {}).get("plus_minus_equity")
    if value is None:
        value = candidate.get("confidence_pm")
    return None if value is None else float(value)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("teacher_json", type=Path)
    p.add_argument("--current-games", type=int, default=1296)
    p.add_argument("--margin", type=float, default=0.005)
    p.add_argument("--out", type=Path)
    args = p.parse_args()

    data = json.loads(args.teacher_json.read_text(encoding="utf-8-sig"))
    candidates = sorted(data["candidates"], key=lambda c: float(c["equity"]), reverse=True)
    if len(candidates) < 2:
        raise SystemExit("need at least two candidates")

    best, second = candidates[:2]
    gap = float(best["equity"]) - float(second["equity"])
    c1, c2 = confidence_pm(best), confidence_pm(second)
    if c1 is None or c2 is None:
        accept = False
        threshold = None
        reason = "confidence_missing"
    else:
        threshold = c1 + c2 + args.margin
        accept = gap > threshold
        reason = "decisive_gap" if accept else "uncertainty_overlap_or_small_gap"

    try:
        idx = LEVELS.index(args.current_games)
    except ValueError:
        raise SystemExit(f"current games must be one of {LEVELS}")
    next_games = args.current_games if accept or idx == len(LEVELS) - 1 else LEVELS[idx + 1]

    result = {
        "schema": "mzand.xg.rollout-depth-decision.v1",
        "xgid": data.get("xgid"),
        "best_move": best["move"],
        "second_move": second["move"],
        "best_equity": float(best["equity"]),
        "second_equity": float(second["equity"]),
        "gap": gap,
        "best_confidence_pm": c1,
        "second_confidence_pm": c2,
        "margin": args.margin,
        "decision_threshold": threshold,
        "current_games": args.current_games,
        "accept_current_depth": accept,
        "next_games": next_games,
        "reason": reason,
    }
    text = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
