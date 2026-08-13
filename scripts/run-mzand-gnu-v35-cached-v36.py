#!/usr/bin/env python3
"""Cached execution wrapper for the frozen GNU v35 algorithm.

Scientific semantics stay v35. This wrapper only removes repeated computation:
- v34 residual training data gets one frozen-v33 inference per row instead of 3,
- afterstate features are encoded once per row for base + residual features,
- tune/dev base scores and residual predictions are cached once,
- all 46 beta/gate tune trials reuse those cached arrays.

The original v35 script, beta/gate grid, metric key, seeds, XGBRanker parameters,
train/tune/dev policy, output model semantics, and provenance gates are preserved.
No dev mining/model selection, pristine data, or XG labels are introduced.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
from xgboost import XGBRanker

HERE = Path(__file__).resolve().parent
START = time.perf_counter()
TIMINGS = {}
CACHE_META = {}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


base = load('mzand_v35_cached_base', HERE / 'train-mzand-gnu-v35-confidence-gated.py')
v34 = base.v34
v35z = base.v27
v34z = v34.v27
enc = v34.enc


def _time(label, fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    TIMINGS[label] = TIMINGS.get(label, 0.0) + dt
    print(f'CACHE_TIMING {label}: {dt:.3f}s', flush=True)
    return out


def row_fast(art, row):
    """Exact v34.base_scores + candidate_features with one feature pass."""
    hints = row.get('hints') or []
    after = np.stack([enc.afterstate_features(row, h) for h in hints])
    phase = v34.v33.phase(row)
    spec = art['phaseExperts'][phase]
    rs = np.asarray(spec['ranker'].predict(after), float)
    eq = np.asarray(spec['reg'].predict(after), float)
    b = float(spec['alpha']) * v34z.zscore(rs) + (1.0 - float(spec['alpha'])) * v34z.zscore(eq)
    b = np.asarray(b, float)
    bz = v34z.zscore(b)
    ez = v34z.zscore(eq)
    rz = v34z.zscore(rs)
    feats = np.stack([
        np.concatenate([after[i], np.asarray([bz[i], ez[i], rz[i]], np.float32)])
        for i in range(len(hints))
    ])
    return b, eq, rs, feats


def dataset_cached(art, rows, splits):
    wanted = set(splits)
    X, y, q, gw = [], [], [], []
    gid = mined = wrong = processed = 0
    t0 = time.perf_counter()
    for row in rows:
        if row.get('split') not in wanted:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        b, _, _, feats = row_fast(art, row)
        n = len(hints)
        eqs = [float(h.get('equity', 0)) for h in hints]
        lo = min(eqs)
        iswrong = int(hints[int(np.argmax(b))].get('rank', 999)) != 1
        margin = row.get('teacherMargin')
        low = isinstance(margin, (int, float)) and margin < 0.03
        hard = bool(iswrong or low or row.get('hard'))
        mined += int(hard)
        wrong += int(iswrong)
        gw.append(max(v34z.base_weight(row), 16.0 if hard else 0.0))
        for f, h, eq in zip(feats, hints, eqs):
            rank = int(h.get('rank', n))
            gap = min(24, max(0, int(round((eq - lo) * 60.0))))
            X.append(f)
            y.append(float((n - rank + 1) + (10 if rank == 1 else 0) + gap))
            q.append(gid)
        gid += 1
        processed += 1
        if processed % 5000 == 0:
            print(f'CACHE_DATASET groups={processed} elapsed={time.perf_counter()-t0:.1f}s', flush=True)
    if not X:
        raise RuntimeError('empty cached residual dataset')
    return (
        np.stack(X), np.asarray(y, np.float32), np.asarray(q, np.int32),
        np.asarray(gw, np.float32),
        {'groups': gid, 'minedRows': mined, 'baseWrongRows': wrong},
    )


def train_cached(art, rows, splits, seed):
    tag = '+'.join(splits)
    X, y, q, w, stats = _time(f'build_dataset_{tag}', lambda: dataset_cached(art, rows, splits))
    print(f'CACHE_DATASET_READY split={tag} candidates={len(X)} groups={stats["groups"]}', flush=True)
    r = XGBRanker(
        objective='rank:pairwise', eval_metric='ndcg@1', n_estimators=2200,
        max_depth=8, learning_rate=.015, min_child_weight=3,
        subsample=.95, colsample_bytree=.95, reg_alpha=.03, reg_lambda=4.0,
        tree_method='hist', n_jobs=-1, random_state=seed,
    )
    _time(f'fit_residual_{tag}', lambda: r.fit(X, y, qid=q, sample_weight=w))
    return r, stats


_EVAL_CACHE = {}


def _verify_rows(art, residual, cache, n=8):
    checked = 0
    for c in cache[:n]:
        row = c['row']
        b2, eq2, rs2 = v34.base_scores(art, row)
        f2 = v34.candidate_features(art, row)
        np.testing.assert_allclose(c['base'], np.asarray(b2, float), rtol=0, atol=1e-12)
        np.testing.assert_allclose(c['eq'], np.asarray(eq2, float), rtol=0, atol=1e-12)
        np.testing.assert_allclose(c['rs'], np.asarray(rs2, float), rtol=0, atol=1e-12)
        np.testing.assert_allclose(c['features'], f2, rtol=0, atol=1e-7)
        rr2 = np.asarray(residual.predict(f2), float)
        np.testing.assert_allclose(c['resZ'], v35z.zscore(rr2), rtol=0, atol=1e-12)
        checked += 1
    print(f'CACHE_EQUIVALENCE: PASS rows={checked}', flush=True)
    return checked


def _build_eval_cache(art, residual, rows, split):
    out = []
    processed = 0
    t0 = time.perf_counter()
    for row in rows:
        if row.get('split') != split:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        b, eq, rs, feats = row_fast(art, row)
        bz = np.asarray(v35z.zscore(b), float)
        ordered = np.sort(bz)
        gap = float(ordered[-1] - ordered[-2]) if len(ordered) >= 2 else 99.0
        rr = np.asarray(residual.predict(feats), float)
        out.append({
            'base': b,
            'baseZ': bz,
            'gap': gap,
            'resZ': np.asarray(v35z.zscore(rr), float),
            'ranks': np.asarray([int(h.get('rank', 999)) for h in hints], np.int32),
            'equities': np.asarray([float(h.get('equity', 0.0)) for h in hints], float),
            'hard': bool(row.get('hard')),
            'row': row, 'eq': eq, 'rs': rs, 'features': feats,
        })
        processed += 1
        if processed % 2500 == 0:
            print(f'CACHE_EVAL split={split} rows={processed} elapsed={time.perf_counter()-t0:.1f}s', flush=True)
    if not out:
        raise RuntimeError(f'empty eval cache for {split}')
    checked = _verify_rows(art, residual, out)
    CACHE_META[split] = {'rows': len(out), 'equivalenceRows': checked}
    for c in out:
        c.pop('row', None); c.pop('eq', None); c.pop('rs', None); c.pop('features', None)
    return out


def evaluate_cached(art, residual, beta, gate, rows, split):
    key = (id(residual), split)
    if key not in _EVAL_CACHE:
        _EVAL_CACHE[key] = _time(f'build_eval_cache_{split}', lambda: _build_eval_cache(art, residual, rows, split))
    cache = _EVAL_CACHE[key]
    total = t1 = t2 = t3 = hardn = hardt = gated = 0
    losses = []
    for c in cache:
        score = c['base']
        if beta > 0 and c['gap'] <= gate:
            score = (1.0 - beta) * c['baseZ'] + beta * c['resZ']
            gated += 1
        ix = int(np.argmax(score))
        rank = int(c['ranks'][ix])
        losses.append(max(0.0, float(c['equities'][0]) - float(c['equities'][ix])))
        total += 1; t1 += rank == 1; t2 += rank <= 2; t3 += rank <= 3
        if c['hard']:
            hardn += 1; hardt += rank == 1
    return {
        'samples': total, 'strictTop1': t1 / total, 'top2': t2 / total,
        'top3': t3 / total, 'meanEquityLoss': float(np.mean(losses)),
        'hardSamples': hardn, 'hardStrictTop1': hardt / hardn if hardn else None,
        'gatedRows': gated,
    }


def write_execution_report():
    lines = [
        'EXECUTION: GNU_V35_CACHED_V36',
        'SCIENTIFIC_ALGORITHM: mzand-gnu-v35',
        'CACHE_ONLY_OPTIMIZATION: True',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'DEV_ROWS_MINED: 0',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
    ]
    for split, meta in sorted(CACHE_META.items()):
        lines += [f'{split.upper()}_CACHE_ROWS: {meta["rows"]}', f'{split.upper()}_CACHE_EQUIVALENCE_ROWS: {meta["equivalenceRows"]}']
    for k, v in sorted(TIMINGS.items()):
        lines.append(f'TIMING_{k.upper()}: {v:.3f}')
    lines.append(f'TOTAL_SECONDS: {time.perf_counter()-START:.3f}')
    Path('mzand-gnu-v35-cached-v36-execution-report.txt').write_text('\n'.join(lines) + '\n')
    print(Path('mzand-gnu-v35-cached-v36-execution-report.txt').read_text(), flush=True)


def main():
    # Monkey-patch computationally equivalent implementations only.
    base.v34.train = train_cached
    base.evaluate = evaluate_cached
    base.main()
    write_execution_report()


if __name__ == '__main__':
    main()
