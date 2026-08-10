#!/usr/bin/env python3
import argparse
import json
import math
import re
from pathlib import Path

BLOCKED_WORDS = ("pristine", "blind")
LAMBDA_GRID = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def safe_text(value):
    text = str(value or "").lower().replace("non-pristine", "").replace("non_pristine", "")
    return text


def reject_sensitive(path, data):
    values = [Path(path).name]
    for key in ("scope", "split", "dataset_split", "benchmark", "benchmark_name"):
        value = data.get(key)
        if isinstance(value, str):
            values.append(value)
    for value in values:
        text = safe_text(value)
        if "pristine" in text or re.search(r"\bblind\b", text):
            raise ValueError(f"blocked benchmark-sensitive input: {path} value={value!r}")


def confidence_pm(candidate):
    value = (candidate.get("confidence") or {}).get("plus_minus_equity")
    if value is None:
        value = candidate.get("confidence_pm")
    return None if value is None else float(value)


def xgid_dice(xgid):
    payload = str(xgid).split("=", 1)[-1]
    parts = payload.split(":")
    if len(parts) < 5:
        return (0, 0)
    token = parts[4]
    if len(token) != 2 or not token.isdigit():
        return (0, 0)
    return int(token[0]), int(token[1])


def move_features(move):
    tokens = str(move).split()
    pip_distance = 0.0
    checker_moves = 0.0
    hit_count = str(move).count("*")
    from_points = []
    to_points = []
    for token in tokens:
        match = re.match(r"^(bar|\d+)/(off|\d+)(?:\((\d+)\))?\*?$", token, re.I)
        if not match:
            continue
        src, dst, count_text = match.groups()
        count = int(count_text or 1)
        checker_moves += count
        src_point = 25 if src.lower() == "bar" else int(src)
        dst_point = 0 if dst.lower() == "off" else int(dst)
        pip_distance += abs(src_point - dst_point) * count
        from_points.extend([src_point] * count)
        to_points.extend([dst_point] * count)
    return {
        "token_count": float(len(tokens)),
        "checker_moves": checker_moves,
        "pip_distance": pip_distance,
        "hit_count": float(hit_count),
        "from_mean": sum(from_points) / len(from_points) if from_points else 0.0,
        "to_mean": sum(to_points) / len(to_points) if to_points else 0.0,
    }


def candidate_features(position, candidate):
    player = candidate.get("player") or {}
    opponent = candidate.get("opponent") or {}
    d1, d2 = xgid_dice(position["xgid"])
    mf = move_features(candidate["move"])
    return [
        float(candidate["equity"]),
        float(candidate.get("screening_rank") or candidate.get("rank") or 0),
        float(candidate.get("original_analysis_rank") or 0),
        float(player.get("win") or 0.0),
        float(player.get("gammon") or 0.0),
        float(player.get("backgammon") or 0.0),
        float(opponent.get("win") or 0.0),
        float(opponent.get("gammon") or 0.0),
        float(opponent.get("backgammon") or 0.0),
        float(max(d1, d2)),
        float(min(d1, d2)),
        float(d1 == d2),
        mf["token_count"],
        mf["checker_moves"],
        mf["pip_distance"],
        mf["hit_count"],
        mf["from_mean"],
        mf["to_mean"],
    ]


def parse_position(path):
    data = load(path)
    reject_sensitive(path, data)
    if data.get("schema") != "mzand.xg.screening-coverage-audit.v2":
        return None
    screening = list(data.get("screening_candidates") or [])
    teacher = list(data.get("teacher_candidates") or [])
    if len(screening) < 2 or len(teacher) < 2:
        raise ValueError(f"coverage audit lacks candidates: {path}")
    sby = {item["move"]: dict(item) for item in screening}
    tby = {item["move"]: dict(item) for item in teacher}
    if set(sby) != set(tby):
        raise ValueError(f"candidate set mismatch in {path}")
    screening = sorted(sby.values(), key=lambda item: int(item.get("screening_rank") or item.get("rank") or 999))
    teacher = sorted(tby.values(), key=lambda item: int(item.get("rollout_rank") or item.get("rank") or 999))
    if len({item["move"] for item in screening}) != len(screening):
        raise ValueError(f"duplicate screening moves in {path}")
    return {
        "path": str(path),
        "xgid": data["xgid"],
        "screening": screening,
        "teacher": teacher,
        "teacher_by_move": tby,
        "teacher_best_move": teacher[0]["move"],
    }


def transpose(matrix):
    return list(map(list, zip(*matrix)))


def solve_linear(a, b):
    n = len(b)
    m = [list(map(float, row)) + [float(b[i])] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            m[pivot][col] += 1e-8
        m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col]
            if factor == 0:
                continue
            for j in range(col, n + 1):
                m[r][j] -= factor * m[col][j]
    return [m[i][n] for i in range(n)]


def fit_ridge(rows, lam):
    xs = [row["features"] for row in rows]
    ys = [row["target_residual"] for row in rows]
    p = len(xs[0])
    means = [sum(x[j] for x in xs) / len(xs) for j in range(p)]
    scales = []
    for j in range(p):
        variance = sum((x[j] - means[j]) ** 2 for x in xs) / max(1, len(xs) - 1)
        scales.append(math.sqrt(variance) if variance > 1e-12 else 1.0)
    zx = [[1.0] + [(x[j] - means[j]) / scales[j] for j in range(p)] for x in xs]
    q = p + 1
    gram = [[0.0] * q for _ in range(q)]
    rhs = [0.0] * q
    for x, y in zip(zx, ys):
        for i in range(q):
            rhs[i] += x[i] * y
            for j in range(q):
                gram[i][j] += x[i] * x[j]
    for i in range(1, q):
        gram[i][i] += lam
    coef = solve_linear(gram, rhs)
    return {"coef": coef, "means": means, "scales": scales, "lambda": lam}


def predict(model, features):
    z = [1.0] + [
        (features[j] - model["means"][j]) / model["scales"][j]
        for j in range(len(features))
    ]
    return sum(c * x for c, x in zip(model["coef"], z))


def training_rows(positions):
    rows = []
    for position in positions:
        for item in position["screening"]:
            teacher = position["teacher_by_move"][item["move"]]
            screening_equity = float(item["equity"])
            rows.append({
                "position": position,
                "move": item["move"],
                "features": candidate_features(position, item),
                "screening_equity": screening_equity,
                "teacher_equity": float(teacher["equity"]),
                "target_residual": float(teacher["equity"]) - screening_equity,
            })
    return rows


def score_position(position, model=None):
    scored = []
    for item in position["screening"]:
        base = float(item["equity"])
        residual = predict(model, candidate_features(position, item)) if model else 0.0
        scored.append((base + residual, item["move"]))
    scored.sort(reverse=True)
    return [move for _, move in scored]


def decisive_pairs(position, margin):
    teacher = position["teacher"]
    pairs = []
    for i in range(len(teacher)):
        for j in range(i + 1, len(teacher)):
            a, b = teacher[i], teacher[j]
            ca, cb = confidence_pm(a), confidence_pm(b)
            if ca is None or cb is None:
                continue
            gap = float(a["equity"]) - float(b["equity"])
            if gap > ca + cb + margin:
                pairs.append((a["move"], b["move"]))
    return pairs


def evaluate(positions, models_by_xgid, margin):
    top1_hits = 0
    pair_hits = pair_total = 0
    records = []
    for position in positions:
        model = models_by_xgid.get(position["xgid"])
        order = score_position(position, model)
        top1 = order[0] == position["teacher_best_move"]
        top1_hits += int(top1)
        rank = {move: i for i, move in enumerate(order)}
        pairs = decisive_pairs(position, margin)
        correct = sum(rank[a] < rank[b] for a, b in pairs)
        pair_hits += correct
        pair_total += len(pairs)
        records.append({
            "xgid": position["xgid"],
            "predicted_best_move": order[0],
            "teacher_best_move": position["teacher_best_move"],
            "top1_match": top1,
            "decisive_pair_correct": correct,
            "decisive_pair_count": len(pairs),
        })
    return {
        "top1_hits": top1_hits,
        "position_count": len(positions),
        "top1_accuracy": top1_hits / len(positions),
        "decisive_pair_correct": pair_hits,
        "decisive_pair_count": pair_total,
        "decisive_pair_accuracy": pair_hits / pair_total if pair_total else None,
        "positions": records,
    }


def inner_select_lambda(train_positions, margin):
    if len(train_positions) < 3:
        return 1000.0
    best = None
    for lam in LAMBDA_GRID:
        models = {}
        residual_sq = []
        for held in train_positions:
            nested_train = [p for p in train_positions if p["xgid"] != held["xgid"]]
            model = fit_ridge(training_rows(nested_train), lam)
            models[held["xgid"]] = model
            for item in held["screening"]:
                teacher = held["teacher_by_move"][item["move"]]
                target = float(teacher["equity"]) - float(item["equity"])
                pred = predict(model, candidate_features(held, item))
                residual_sq.append((target - pred) ** 2)
        metrics = evaluate(train_positions, models, margin)
        rmse = math.sqrt(sum(residual_sq) / len(residual_sq)) if residual_sq else float("inf")
        key = (
            metrics["top1_accuracy"],
            metrics["decisive_pair_accuracy"] if metrics["decisive_pair_accuracy"] is not None else 0.0,
            -rmse,
            lam,
        )
        if best is None or key > best[0]:
            best = (key, lam)
    return best[1]


def main():
    parser = argparse.ArgumentParser(description="Train and LOPO-test a development-only residual reranker")
    parser.add_argument("references", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--margin", type=float, default=0.005)
    args = parser.parse_args()

    files = sorted(args.references.glob("xg-v*-coverage.json"))
    positions = []
    for path in files:
        position = parse_position(path)
        if position is not None:
            positions.append(position)
    if len(positions) < 3:
        raise SystemExit(f"need at least three non-pristine coverage positions, found {len(positions)}")
    if len({p['xgid'] for p in positions}) != len(positions):
        raise SystemExit("duplicate XGID in development coverage corpus")

    baseline_models = {p["xgid"]: None for p in positions}
    baseline = evaluate(positions, baseline_models, args.margin)

    fold_models = {}
    fold_lambdas = {}
    for held in positions:
        train = [p for p in positions if p["xgid"] != held["xgid"]]
        lam = inner_select_lambda(train, args.margin)
        fold_lambdas[held["xgid"]] = lam
        fold_models[held["xgid"]] = fit_ridge(training_rows(train), lam)
    reranker = evaluate(positions, fold_models, args.margin)

    no_top1_regression = all(item["top1_match"] for item in reranker["positions"] if next(p for p in baseline["positions"] if p["xgid"] == item["xgid"])["top1_match"])
    base_pair = baseline["decisive_pair_accuracy"] if baseline["decisive_pair_accuracy"] is not None else 0.0
    rerank_pair = reranker["decisive_pair_accuracy"] if reranker["decisive_pair_accuracy"] is not None else 0.0
    adopt = bool(
        no_top1_regression
        and (
            reranker["top1_accuracy"] > baseline["top1_accuracy"]
            or (
                reranker["top1_accuracy"] == baseline["top1_accuracy"]
                and rerank_pair > base_pair
            )
        )
    )

    full_lambda = inner_select_lambda(positions, args.margin)
    full_model = fit_ridge(training_rows(positions), full_lambda)
    result = {
        "schema": "mzand.xg.development-residual-reranker-audit.v1",
        "scope": "non-pristine development coverage only; not a blind benchmark",
        "position_count": len(positions),
        "candidate_count": sum(len(p["screening"]) for p in positions),
        "validation": "leave-one-position-out with nested lambda selection",
        "feature_contract": "XGR++ equity/ranks/probabilities + dice + parsed move structure; predicts rollout-equity residual",
        "confidence_margin": args.margin,
        "baseline": baseline,
        "reranker": reranker,
        "fold_lambdas": fold_lambdas,
        "adopt_candidate": adopt,
        "adoption_rule": "no Top-1 regression and strict improvement in Top-1, or equal Top-1 with strict decisive-pair improvement",
        "full_training_lambda": full_lambda,
        "full_model": full_model,
        "source_files": [Path(p["path"]).name for p in positions],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"development_positions={result['position_count']}")
    print(f"baseline_top1={baseline['top1_hits']}/{baseline['position_count']} ({baseline['top1_accuracy']:.6f})")
    print(f"reranker_top1={reranker['top1_hits']}/{reranker['position_count']} ({reranker['top1_accuracy']:.6f})")
    print(f"baseline_decisive_pairs={baseline['decisive_pair_correct']}/{baseline['decisive_pair_count']}")
    print(f"reranker_decisive_pairs={reranker['decisive_pair_correct']}/{reranker['decisive_pair_count']}")
    print(f"adopt_candidate={adopt}")
    print(f"full_training_lambda={full_lambda}")


if __name__ == "__main__":
    main()
