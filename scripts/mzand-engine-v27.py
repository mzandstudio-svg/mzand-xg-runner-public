#!/usr/bin/env python3
"""Independent MZand move engine built on GNU-trained equity + ranking models.

Key properties
--------------
* No XG code, weights, labels, or runtime dependency.
* Exhaustive legal move enumeration for a turn from the compact board schema
  produced by ``gnu-teacher-v6.mjs``.
* Uses the existing MZand candidate feature encoder, an equity regressor, and
  a pairwise/listwise ranker. Classifier-only artifacts are deliberately
  rejected.
* Expectiminimax search over the 21 unordered dice outcomes with correct
  36-way probabilities and configurable candidate beam width.
* Cubeless self-play rollout with common-random-number seeds across candidate
  moves for low-noise candidate comparison.

This module is intentionally a search/runtime layer. It does not train on dev,
pristine, or XG data and it does not modify sealed evidence.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import joblib
import numpy as np


DICE_OUTCOMES: Tuple[Tuple[Tuple[int, int], float], ...] = tuple(
    ((a, b), (1.0 if a == b else 2.0) / 36.0)
    for a in range(1, 7)
    for b in range(a, 7)
)


def _load_afterstate_module():
    path = Path(__file__).with_name("mzand-afterstate-v27.py")
    spec = importlib.util.spec_from_file_location("mzand_afterstate_v27", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import afterstate encoder from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AFTERSTATE = None


def afterstate_module():
    global AFTERSTATE
    if AFTERSTATE is None:
        AFTERSTATE = _load_afterstate_module()
    return AFTERSTATE


def _tuple_board(board: Dict) -> Tuple:
    return (
        tuple(int(x) for x in board["own"]),
        tuple(int(x) for x in board["opp"]),
        int(board.get("barOwn", 0)),
        int(board.get("barOpp", 0)),
        int(board.get("offOwn", 0)),
        int(board.get("offOpp", 0)),
    )


def _dict_board(key: Tuple) -> Dict:
    own, opp, bar_own, bar_opp, off_own, off_opp = key
    return {
        "own": list(own),
        "opp": list(opp),
        "barOwn": int(bar_own),
        "barOpp": int(bar_opp),
        "offOwn": int(off_own),
        "offOpp": int(off_opp),
    }


def flip_board(board: Dict) -> Dict:
    """Return the same physical board from the opponent-to-move perspective."""
    return {
        "own": list(reversed(board["opp"])),
        "opp": list(reversed(board["own"])),
        "barOwn": int(board.get("barOpp", 0)),
        "barOpp": int(board.get("barOwn", 0)),
        "offOwn": int(board.get("offOpp", 0)),
        "offOpp": int(board.get("offOwn", 0)),
    }


def all_in_home(board: Dict) -> bool:
    own = board["own"]
    return int(board.get("barOwn", 0)) == 0 and sum(int(x) for x in own[6:]) == 0


def terminal_points_for_mover(after_board: Dict) -> int | None:
    """Return +1/+2/+3 when the mover just won, otherwise None.

    Coordinates are from the mover perspective, whose home board is points 1..6.
    """
    if int(after_board.get("offOwn", 0)) < 15:
        return None
    if int(after_board.get("offOpp", 0)) > 0:
        return 1
    loser_on_bar = int(after_board.get("barOpp", 0)) > 0
    loser_in_winner_home = sum(int(x) for x in after_board["opp"][:6]) > 0
    return 3 if loser_on_bar or loser_in_winner_home else 2


def _single_die_moves(board: Dict, die: int) -> List[Tuple[Dict, Dict]]:
    """All legal one-checker plays for one die.

    Returns ``(next_board, move_dict)`` pairs using the same move schema as GNU
    hints consumed by ``train-mzand-gnu-v2.py``.
    """
    die = int(die)
    own = [int(x) for x in board["own"]]
    opp = [int(x) for x in board["opp"]]
    bar_own = int(board.get("barOwn", 0))
    bar_opp = int(board.get("barOpp", 0))
    off_own = int(board.get("offOwn", 0))
    off_opp = int(board.get("offOpp", 0))
    out: List[Tuple[Dict, Dict]] = []

    # A checker on the bar must be entered before any other checker can move.
    if bar_own > 0:
        to = 25 - die
        ti = to - 1
        if 1 <= to <= 24 and opp[ti] <= 1:
            own2, opp2 = own.copy(), opp.copy()
            bopp = bar_opp
            hit = opp2[ti] == 1
            if hit:
                opp2[ti] = 0
                bopp += 1
            own2[ti] += 1
            out.append(({
                "own": own2, "opp": opp2,
                "barOwn": bar_own - 1, "barOpp": bopp,
                "offOwn": off_own, "offOpp": off_opp,
            }, {"moveKind": "reenter", "to": to, "isHit": hit}))
        return out

    # Ordinary point-to-point moves.
    for fr in range(1, 25):
        fi = fr - 1
        if own[fi] <= 0:
            continue
        to = fr - die
        if to >= 1:
            ti = to - 1
            if opp[ti] > 1:
                continue
            own2, opp2 = own.copy(), opp.copy()
            bopp = bar_opp
            own2[fi] -= 1
            hit = opp2[ti] == 1
            if hit:
                opp2[ti] = 0
                bopp += 1
            own2[ti] += 1
            out.append(({
                "own": own2, "opp": opp2,
                "barOwn": 0, "barOpp": bopp,
                "offOwn": off_own, "offOpp": off_opp,
            }, {"moveKind": "point-to-point", "from": fr, "to": to, "isHit": hit}))
            continue

        # Bear off only when every checker is in the home board.
        if not all_in_home(board) or fr > 6:
            continue
        exact = fr == die
        oversize = fr < die and not any(own[p - 1] > 0 for p in range(fr + 1, 7))
        if not (exact or oversize):
            continue
        own2 = own.copy()
        own2[fi] -= 1
        out.append(({
            "own": own2, "opp": opp.copy(),
            "barOwn": 0, "barOpp": bar_opp,
            "offOwn": off_own + 1, "offOpp": off_opp,
        }, {"moveKind": "bear-off", "from": fr, "isHit": False}))

    return out


def _play_dice_order(board: Dict, dice_order: Sequence[int]) -> List[Tuple[Dict, List[Dict], Tuple[int, ...]]]:
    states = [(board, [], tuple())]
    for die in dice_order:
        nxt: List[Tuple[Dict, List[Dict], Tuple[int, ...]]] = []
        for b, moves, used in states:
            plays = _single_die_moves(b, die)
            if not plays:
                # This order cannot consume this die; keep the partial play so
                # maximum-dice filtering can decide whether it is legal overall.
                nxt.append((b, moves, used))
                continue
            for b2, mv in plays:
                nxt.append((b2, moves + [mv], used + (int(die),)))
        states = nxt
    return states


def canonical_moves(moves: Sequence[Dict]) -> Tuple:
    return tuple(
        (
            str(m.get("moveKind", "point-to-point")),
            int(m["from"]) if isinstance(m.get("from"), (int, float)) else 0,
            int(m["to"]) if isinstance(m.get("to"), (int, float)) else 0,
            bool(m.get("isHit", False)),
        )
        for m in moves
    )


def generate_legal_candidates(board: Dict, dice: Sequence[int]) -> List[Dict]:
    """Exhaustively enumerate legal move sequences for a roll.

    Enforces the backgammon maximum-dice rule and the higher-die rule when only
    one of two distinct dice can be played. Result-equivalent sequences are
    deduplicated by final board, retaining a deterministic representative move
    sequence.
    """
    if len(dice) != 2:
        raise ValueError("dice must contain exactly two values")
    a, b = int(dice[0]), int(dice[1])
    if not (1 <= a <= 6 and 1 <= b <= 6):
        raise ValueError("dice values must be in 1..6")
    orders = [(a, a, a, a)] if a == b else [(a, b), (b, a)]
    raw: List[Tuple[Dict, List[Dict], Tuple[int, ...]]] = []
    for order in orders:
        raw.extend(_play_dice_order(board, order))

    max_used = max((len(u) for _, _, u in raw), default=0)
    raw = [x for x in raw if len(x[2]) == max_used]

    # If only one of two distinct dice can be used, the larger die is compulsory
    # whenever at least one legal play using it exists.
    if a != b and max_used == 1:
        hi = max(a, b)
        if any(x[2] and x[2][0] == hi for x in raw):
            raw = [x for x in raw if x[2] and x[2][0] == hi]

    if max_used == 0:
        return [{"moves": [], "usedDice": [], "forcedPass": True}]

    best_by_board: Dict[Tuple, Dict] = {}
    for b2, moves, used in raw:
        k = _tuple_board(b2)
        cand = {
            "moves": moves,
            "usedDice": list(used),
            "forcedPass": False,
            "afterBoard": b2,
        }
        old = best_by_board.get(k)
        if old is None or canonical_moves(cand["moves"]) < canonical_moves(old["moves"]):
            best_by_board[k] = cand
    return sorted(best_by_board.values(), key=lambda c: canonical_moves(c["moves"]))


def apply_candidate(board: Dict, candidate: Dict) -> Dict:
    if "afterBoard" in candidate:
        return candidate["afterBoard"]
    if not candidate.get("moves"):
        return {k: (list(v) if isinstance(v, list) else v) for k, v in board.items()}
    return afterstate_module().afterstate_from_hint(board, candidate)


def zscore(a: Sequence[float]) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    if len(a) <= 1:
        return np.zeros_like(a)
    s = float(np.std(a))
    return a - float(np.mean(a)) if s < 1e-9 else (a - float(np.mean(a))) / s


@dataclass
class CandidateScore:
    candidate: Dict
    predicted_equity: float
    rank_score: float
    blend_score: float
    search_equity: float | None = None


class MZandEngine:
    def __init__(self, model_path: str | Path, beam_width: int = 8):
        artifact = joblib.load(model_path)
        if not isinstance(artifact, dict):
            raise RuntimeError("unsupported MZand model artifact")
        if artifact.get("xgLabelsUsed") is True or artifact.get("pristineDataUsed") is True:
            raise RuntimeError("forbidden model provenance: XG/pristine data flagged")
        if "equityRegressor" not in artifact or "ranker" not in artifact:
            raise RuntimeError(
                "model must contain equityRegressor + ranker; classifier-only artifacts are rejected"
            )
        if artifact.get("featureSchema") not in ("mzand.afterstate.v27", None):
            raise RuntimeError(f"unsupported feature schema {artifact.get('featureSchema')}")
        self.artifact = artifact
        self.equity = artifact["equityRegressor"]
        self.ranker = artifact["ranker"]
        self.alpha = float(artifact.get("rankBlendAlpha", 0.65))
        self.beam_width = max(1, int(beam_width))

    def score_candidates(self, board: Dict, dice: Sequence[int], candidates: Sequence[Dict] | None = None) -> List[CandidateScore]:
        candidates = list(candidates if candidates is not None else generate_legal_candidates(board, dice))
        if not candidates:
            return []
        # A forced pass leaves the board unchanged and hands the roll to the
        # opponent. The afterstate evaluator can score that unchanged board
        # directly, so pass positions do not collapse to an arbitrary zero.
        if len(candidates) == 1 and candidates[0].get("forcedPass"):
            enc = afterstate_module()
            x = enc.afterstate_features_from_board(board).reshape(1, -1)
            eq = float(np.asarray(self.equity.predict(x), dtype=float)[0])
            return [CandidateScore(candidates[0], eq, 0.0, eq)]
        enc = afterstate_module()
        X = np.stack([enc.afterstate_features_from_board(apply_candidate(board, c)) for c in candidates])
        eq = np.asarray(self.equity.predict(X), dtype=float)
        rs = np.asarray(self.ranker.predict(X), dtype=float)
        blend = self.alpha * zscore(rs) + (1.0 - self.alpha) * zscore(eq)
        out = [
            CandidateScore(c, float(eq[i]), float(rs[i]), float(blend[i]))
            for i, c in enumerate(candidates)
        ]
        return sorted(out, key=lambda s: (s.blend_score, s.predicted_equity), reverse=True)

    def choose_fast(self, board: Dict, dice: Sequence[int]) -> CandidateScore:
        scored = self.score_candidates(board, dice)
        if not scored:
            raise RuntimeError("no candidate generated")
        return scored[0]

    def _decision_value(self, board: Dict, dice: Tuple[int, int], depth: int) -> float:
        scored = self.score_candidates(board, dice)
        if not scored:
            return 0.0
        if scored[0].candidate.get("forcedPass"):
            if depth <= 1:
                return scored[0].predicted_equity
            return -self._chance_value(flip_board(board), depth - 1)

        beam = scored[: self.beam_width]
        best = -math.inf
        for s in beam:
            after = apply_candidate(board, s.candidate)
            terminal = terminal_points_for_mover(after)
            if terminal is not None:
                v = float(terminal)
            elif depth <= 1:
                v = s.predicted_equity
            else:
                v = -self._chance_value(flip_board(after), depth - 1)
            best = max(best, v)
        return best

    def _chance_value(self, board: Dict, depth: int) -> float:
        return sum(prob * self._decision_value(board, dice, depth) for dice, prob in DICE_OUTCOMES)

    def search(self, board: Dict, dice: Sequence[int], depth: int = 2) -> List[CandidateScore]:
        depth = max(1, int(depth))
        scored = self.score_candidates(board, dice)
        if depth == 1 or (len(scored) == 1 and scored[0].candidate.get("forcedPass")):
            for s in scored:
                s.search_equity = s.predicted_equity
            return scored

        # Search only the strongest fast candidates; all legal candidates were
        # still enumerated before pruning.
        beam_ids = {id(s.candidate) for s in scored[: self.beam_width]}
        for s in scored:
            if id(s.candidate) not in beam_ids:
                s.search_equity = None
                continue
            after = apply_candidate(board, s.candidate)
            terminal = terminal_points_for_mover(after)
            s.search_equity = float(terminal) if terminal is not None else -self._chance_value(flip_board(after), depth - 1)
        return sorted(
            scored,
            key=lambda s: (
                -math.inf if s.search_equity is None else s.search_equity,
                s.blend_score,
            ),
            reverse=True,
        )

    def rollout_candidate(self, board: Dict, candidate: Dict, trials: int = 1296, seed: int = 20260811, max_turns: int = 512) -> Dict:
        """Cubeless self-play rollout from a root candidate.

        This is MZand self-play, not a GNU rollout label. It is suitable for
        independent candidate verification/mining after the supervised model is
        frozen. Results are never implicitly marked training-eligible.
        """
        root_after = apply_candidate(board, candidate)
        immediate = terminal_points_for_mover(root_after)
        if immediate is not None:
            return {
                "trials": int(trials), "seed": int(seed),
                "meanEquity": float(immediate), "stdError": 0.0,
                "completed": int(trials), "truncated": 0,
                "trainingEligible": False,
                "provenance": "MZAND_SELF_PLAY_ROLLOUT",
            }

        outcomes: List[float] = []
        truncated = 0
        for t in range(int(trials)):
            rng = random.Random(int(seed) + t)
            b = flip_board(root_after)
            sign_to_root = -1.0
            result = None
            for _ in range(max_turns):
                d = (rng.randint(1, 6), rng.randint(1, 6))
                pick = self.choose_fast(b, d)
                if pick.candidate.get("forcedPass"):
                    b = flip_board(b)
                    sign_to_root *= -1.0
                    continue
                after = apply_candidate(b, pick.candidate)
                points = terminal_points_for_mover(after)
                if points is not None:
                    result = sign_to_root * float(points)
                    break
                b = flip_board(after)
                sign_to_root *= -1.0
            if result is None:
                truncated += 1
                # Conservative neutral treatment; surfaced explicitly in report.
                result = 0.0
            outcomes.append(result)

        a = np.asarray(outcomes, dtype=float)
        se = float(np.std(a, ddof=1) / math.sqrt(len(a))) if len(a) > 1 else 0.0
        return {
            "trials": int(trials), "seed": int(seed),
            "meanEquity": float(np.mean(a)), "stdError": se,
            "completed": int(trials - truncated), "truncated": int(truncated),
            "trainingEligible": False,
            "provenance": "MZAND_SELF_PLAY_ROLLOUT",
        }

    def rollout_top(self, board: Dict, dice: Sequence[int], top_n: int = 5, trials: int = 1296, seed: int = 20260811) -> List[Dict]:
        searched = self.search(board, dice, depth=1)
        out = []
        for i, score in enumerate(searched[: max(1, int(top_n))]):
            r = self.rollout_candidate(board, score.candidate, trials=trials, seed=seed)
            r.update({
                "candidateIndex": i,
                "moves": score.candidate.get("moves", []),
                "fastPredictedEquity": score.predicted_equity,
                "fastBlendScore": score.blend_score,
            })
            out.append(r)
        return sorted(out, key=lambda r: r["meanEquity"], reverse=True)


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--position-json", required=True, help="JSON file with board + dice")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--beam", type=int, default=8)
    ap.add_argument("--rollout-trials", type=int, default=0)
    ap.add_argument("--rollout-top", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260811)
    args = ap.parse_args()

    pos = json.loads(Path(args.position_json).read_text())
    board, dice = pos["board"], pos["dice"]
    engine = MZandEngine(args.model, beam_width=args.beam)
    result = {
        "modelVersion": engine.artifact.get("version"),
        "candidateCoverage": "EXHAUSTIVE_LEGAL_ENUMERATION",
        "searchDepth": args.depth,
        "beamWidth": args.beam,
        "xgLabelsUsed": False,
        "pristineDataUsed": False,
        "candidates": [],
    }
    for s in engine.search(board, dice, depth=args.depth):
        result["candidates"].append({
            "moves": s.candidate.get("moves", []),
            "usedDice": s.candidate.get("usedDice", []),
            "predictedEquity": s.predicted_equity,
            "rankScore": s.rank_score,
            "blendScore": s.blend_score,
            "searchEquity": s.search_equity,
        })
    if args.rollout_trials > 0:
        result["selfPlayRollout"] = engine.rollout_top(
            board, dice, top_n=args.rollout_top,
            trials=args.rollout_trials, seed=args.seed,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
