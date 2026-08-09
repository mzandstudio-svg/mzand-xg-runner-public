#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

CANDIDATE_RE = re.compile(
    r"^\s*(\d+)\.\s+(.+?)\s{2,}(\S.*?)\s+eq:([+-]\d+\.\d+)"
    r"(?:\s+\(([+-]\d+\.\d+)\))?\s*$"
)
PLAYER_RE = re.compile(
    r"^\s*Player:\s+(\d+\.\d+)%\s+\(G:(\d+\.\d+)%\s+B:(\d+\.\d+)%\)"
)
OPPONENT_RE = re.compile(
    r"^\s*Opponent:\s+(\d+\.\d+)%\s+\(G:(\d+\.\d+)%\s+B:(\d+\.\d+)%\)"
)
CONFIDENCE_RE = re.compile(
    r"^\s*Confidence:\s+±(\d+\.\d+)\s+\(([+-]\d+\.\d+)\.\.([+-]\d+\.\d+)\)"
    r"\s+-\s+\[(\d+\.\d+)%\]"
)


def pct(value: str) -> float:
    return round(float(value) / 100.0, 6)


def parse_footnotes(lines):
    notes = {}
    current = None
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^([⁰¹²³⁴⁵⁶⁷⁸⁹]+)(.*)$", stripped)
        if m:
            current = m.group(1).translate(SUPERSCRIPT)
            notes[current] = [m.group(2).strip()]
            continue
        if current is not None:
            if stripped.startswith("eXtreme Gammon Version:"):
                current = None
            elif stripped:
                notes[current].append(stripped)
    return {key: " ".join(parts).strip() for key, parts in notes.items()}


def source_note_key(source: str):
    m = re.search(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)$", source)
    return m.group(1).translate(SUPERSCRIPT) if m else None


def analysis_method(source: str, note: str | None):
    note = note or ""
    if "Analyzed in XG Roller++" in note:
        return "XG Roller++"
    if "Games rolled" in note:
        return "Rollout"
    if source.lower().startswith("book"):
        return "Book"
    return source


def parse_export(text: str):
    lines = text.splitlines()

    xgid_match = re.search(r"^XGID=(.+)$", text, re.MULTILINE)
    if not xgid_match:
        raise ValueError("XGID line missing")
    xgid_payload = xgid_match.group(1).strip()

    players_match = re.search(r"^X:(.*?)\s{3,}O:(.*?)\s*$", text, re.MULTILINE)
    score_match = re.search(
        r"^Score is X:(\d+) O:(\d+) (\d+) pt\.\(s\) match\.\s*$", text, re.MULTILINE
    )
    pip_match = re.search(r"^Pip count\s+X:\s*(\d+)\s+O:\s*(\d+).*?$", text, re.MULTILINE)
    cube_match = re.search(r"^Cube:\s*(\d+)(?:\s*,\s*(.*?))?\s*$", text, re.MULTILINE)
    roll_match = re.search(r"^([XO]) to play\s+(\d)(\d)\s*$", text, re.MULTILINE)
    version_match = re.search(r"^eXtreme Gammon Version:\s*(.+)$", text, re.MULTILINE)

    if not score_match or not cube_match or not roll_match:
        raise ValueError("Required score/cube/on-roll header missing")

    candidate_indexes = [i for i, line in enumerate(lines) if CANDIDATE_RE.match(line)]
    if not candidate_indexes:
        raise ValueError("No analyzed candidates found")

    footnotes = parse_footnotes(lines)
    candidates = []
    for pos, line_index in enumerate(candidate_indexes):
        end = candidate_indexes[pos + 1] if pos + 1 < len(candidate_indexes) else len(lines)
        match = CANDIDATE_RE.match(lines[line_index])
        rank, source, move, equity, delta = match.groups()
        candidate = {
            "rank": int(rank),
            "source": source.strip(),
            "move": move.strip(),
            "equity": float(equity),
            "equity_delta": float(delta) if delta is not None else 0.0,
        }

        for line in lines[line_index + 1 : end]:
            player = PLAYER_RE.match(line)
            opponent = OPPONENT_RE.match(line)
            confidence = CONFIDENCE_RE.match(line)
            if player:
                candidate["player"] = {
                    "win": pct(player.group(1)),
                    "gammon": pct(player.group(2)),
                    "backgammon": pct(player.group(3)),
                }
            elif opponent:
                candidate["opponent"] = {
                    "win": pct(opponent.group(1)),
                    "gammon": pct(opponent.group(2)),
                    "backgammon": pct(opponent.group(3)),
                }
            elif confidence:
                candidate["confidence"] = {
                    "plus_minus_equity": float(confidence.group(1)),
                    "equity_low": float(confidence.group(2)),
                    "equity_high": float(confidence.group(3)),
                    "chance_best": pct(confidence.group(4)),
                }

        if "player" not in candidate or "opponent" not in candidate:
            raise ValueError(f"Candidate rank {rank} is missing probabilities")

        note_key = source_note_key(candidate["source"])
        note = footnotes.get(note_key) if note_key else None
        candidate["analysis_method"] = analysis_method(candidate["source"], note)
        if note:
            candidate["provenance"] = note
        candidates.append(candidate)

    expected_ranks = list(range(1, len(candidates) + 1))
    actual_ranks = [item["rank"] for item in candidates]
    if actual_ranks != expected_ranks:
        raise ValueError(f"Candidate ranks are not sequential: {actual_ranks}")

    best_equity = candidates[0]["equity"]
    for candidate in candidates:
        win_sum = candidate["player"]["win"] + candidate["opponent"]["win"]
        if abs(win_sum - 1.0) > 0.002:
            raise ValueError(f"Rank {candidate['rank']} win probabilities do not sum to 1: {win_sum}")
        expected_delta = candidate["equity"] - best_equity
        if abs(candidate["equity_delta"] - expected_delta) > 0.002:
            raise ValueError(
                f"Rank {candidate['rank']} equity delta mismatch: "
                f"reported={candidate['equity_delta']} expected={expected_delta}"
            )

    cube_detail = cube_match.group(2).strip() if cube_match.group(2) else None
    result = {
        "schema": "mzand.xg.position-label.v1",
        "xgid": f"XGID={xgid_payload}",
        "xgid_payload": xgid_payload,
        "players": {
            "x": players_match.group(1).strip() if players_match else "X",
            "o": players_match.group(2).strip() if players_match else "O",
        },
        "score": {
            "x": int(score_match.group(1)),
            "o": int(score_match.group(2)),
            "match_length": int(score_match.group(3)),
        },
        "pip_count": {
            "x": int(pip_match.group(1)) if pip_match else None,
            "o": int(pip_match.group(2)) if pip_match else None,
        },
        "cube": int(cube_match.group(1)),
        "cube_detail": cube_detail,
        "on_roll": roll_match.group(1),
        "dice": [int(roll_match.group(2)), int(roll_match.group(3))],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "xg_version": version_match.group(1).strip() if version_match else None,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Parse eXtreme Gammon position clipboard export")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.input.read_text(encoding="utf-8-sig")
    data = parse_export(text)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"parsed_candidates={data['candidate_count']}")
    print(f"best_move={data['candidates'][0]['move']}")
    print(f"best_equity={data['candidates'][0]['equity']:+.3f}")
    print(f"best_method={data['candidates'][0]['analysis_method']}")


if __name__ == "__main__":
    main()
