#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description="Rank non-pristine development positions by small baseline Top-1 gap")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--select", type=int, default=3)
    args = parser.parse_args()

    files = sorted(args.input_dir.rglob("xg-v23-*-summary.json"))
    if not files:
        raise SystemExit("no hard-position scan summaries found")

    records = [load(path) for path in files]
    ids = [record["position_id"] for record in records]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"duplicate position ids: {ids}")
    xgids = [record["xgid"] for record in records]
    if len(xgids) != len(set(xgids)):
        raise SystemExit("duplicate XGIDs in hard-position scan")

    non_book = [record for record in records if not record.get("book_hit")]
    book_hits = [record for record in records if record.get("book_hit")]
    ranked = sorted(
        non_book,
        key=lambda record: (
            float(record["top1_gap"]),
            -int(record.get("candidate_count", 0)),
            record["position_id"],
        ),
    )
    selected = ranked[: max(0, args.select)]

    result = {
        "schema": "mzand.xg.hard-position-scan-corpus.v1",
        "scope": "non-pristine development dice variants only; not a blind benchmark",
        "position_count": len(records),
        "non_book_position_count": len(non_book),
        "book_hit_count": len(book_hits),
        "selection_rule": "smallest baseline Top-1 equity gap among non-book positions",
        "selected_count": len(selected),
        "selected_positions": [
            {
                "position_id": record["position_id"],
                "xgid": record["xgid"],
                "top1_gap": float(record["top1_gap"]),
                "best_move": record["best_move"],
                "second_move": record["second_move"],
                "candidate_count": int(record["candidate_count"]),
            }
            for record in selected
        ],
        "ranked_non_book_positions": [
            {
                "rank": index,
                "position_id": record["position_id"],
                "xgid": record["xgid"],
                "top1_gap": float(record["top1_gap"]),
                "best_move": record["best_move"],
                "second_move": record["second_move"],
                "candidate_count": int(record["candidate_count"]),
                "analysis_elapsed_seconds": int(record.get("analysis_elapsed_seconds", 0)),
            }
            for index, record in enumerate(ranked, 1)
        ],
        "book_hits": [
            {
                "position_id": record["position_id"],
                "xgid": record["xgid"],
                "top1_gap": float(record["top1_gap"]),
            }
            for record in book_hits
        ],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"positions={result['position_count']}")
    print(f"non_book_positions={result['non_book_position_count']}")
    print(f"book_hits={result['book_hit_count']}")
    for item in result["selected_positions"]:
        print(
            f"selected={item['position_id']} gap={item['top1_gap']:+.6f} "
            f"best={item['best_move']} second={item['second_move']}"
        )


if __name__ == "__main__":
    main()
