#!/usr/bin/env python3
"""GNU v38: conservative safe override on top of verified v33 + frozen v37 residual.

Goal
----
v37 improved hard-position Top-1 but regressed overall Top-1 slightly.  v38 keeps
v33 as the default decision and only permits the frozen train-only v37 residual
to override when inference-time confidence signals were safe on TUNE.

Scientific contract
-------------------
- exact verified v33 base (run 31561338583),
- exact frozen v35/v36 corpus,
- exact v37 train-only residual; no retraining and no post-selection refit,
- v37 beta/gate remain frozen,
- TUNE is deterministically group-split by position into selector (80%) and
  safety-guard (20%); DEV is not read during policy selection,
- selector searches only inference-time thresholds (base gap, blend advantage,
  residual advantage, phase scope),
- selected policy must not regress selector Top-1 or mean equity loss versus v33,
- that one selected policy must also not regress the independent TUNE guard;
  otherwise v38 freezes to no-override (exact v33 behavior),
- sealed DEV is evaluated only after the policy is frozen,
- no dev mining/model selection, pristine data, or XG labels.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np

HERE = Path(__file__).resolve().parent
START = time.perf_counter()


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


v37 = load('mzand_v38_v37', HERE / 'run-mzand-gnu-v37-frozen-residual.py')
cache = v37.cache
base = v37.base
v34 = cache.v34
zscore = cache.v35z.zscore

STAGE = os.environ.get('GNU_V38_STAGE', 'all').strip().lower()
V37_SELECTION = Path(os.environ.get('GNU_V38_V37_SELECTION', 'mzand-gnu-v37-selection.json'))
V37_RESIDUAL = Path(os.environ.get('GNU_V38_V37_RESIDUAL', 'mzand-gnu-v37-train-only-residual.joblib'))
POLICY = Path(os.environ.get('GNU_V38_POLICY', 'mzand-gnu-v38-safe-override-policy.json'))
SELECT_REPORT = Path('mzand-gnu-v38-selection-report.txt')
FINAL_REPORT = Path('mzand-gnu-v38-safe-override-report.txt')
FINAL_JSON = Path('mzand-gnu-v38-safe-override-report.json')
FINAL_MODEL = Path('mzand-gnu-v38-safe-override.joblib')
EXEC_REPORT = Path('mzand-gnu-v38-execution-report.txt')

PHASE_SCOPES = {
    'all': ('bar', 'bearoff', 'race', 'contact'),
    'bar': ('bar',),
    'bearoff': ('bearoff',),
    'race': ('race',),
    'contact': ('contact',),
}


def check_v37_selection(sel):
    if sel.get('model') != 'mzand-gnu-v37':
        raise SystemExit(f"unexpected v37 selection model: {sel.get('model')!r}")
    if sel.get('residualFitSplits') != ['train']:
        raise SystemExit('v37 residual was not train-only')
    if sel.get('residualRefitAfterSelection') is not False:
        raise SystemExit('v37 residual refit provenance invalid')
    if sel.get('devUsedForModelSelection') is not False or sel.get('devRowsMined') != 0:
        raise SystemExit('v37 dev provenance invalid')
    if sel.get('pristineDataUsed') is not False or sel.get('xgLabelsUsed') is not False:
        raise SystemExit('v37 forbidden-data provenance invalid')


def group_key(row, index):
    pid = row.get('positionId')
    if pid not in (None, ''):
        return f'position:{pid}'
    board = row.get('board')
    if board is not None:
        return 'board:' + json.dumps(board, sort_keys=True, separators=(',', ':'))
    return f'fallback-row:{index}'


def tune_cohort(row, index):
    # Same position always lands in the same cohort; avoids cross-dice position leakage.
    h = hashlib.sha256(group_key(row, index).encode('utf-8')).digest()
    return 'guard' if int.from_bytes(h[:4], 'big') % 5 == 0 else 'select'


def verify_fast_row(art, residual, row, b, eq, rs, feats, resz):
    b2, eq2, rs2 = v34.base_scores(art, row)
    f2 = v34.candidate_features(art, row)
    np.testing.assert_allclose(b, np.asarray(b2, float), rtol=0, atol=1e-12)
    np.testing.assert_allclose(eq, np.asarray(eq2, float), rtol=0, atol=1e-12)
    np.testing.assert_allclose(rs, np.asarray(rs2, float), rtol=0, atol=1e-12)
    np.testing.assert_allclose(feats, f2, rtol=0, atol=1e-7)
    rr2 = np.asarray(residual.predict(f2), float)
    np.testing.assert_allclose(resz, np.asarray(zscore(rr2), float), rtol=0, atol=1e-12)


def build_policy_cache(art, residual, rows, split, beta, v37_gate):
    out = []
    checked = 0
    t0 = time.perf_counter()
    for i, row in enumerate(rows):
        if row.get('split') != split:
            continue
        hints = row.get('hints') or []
        if len(hints) < 2:
            continue
        b, eq, rs, feats = cache.row_fast(art, row)
        bz = np.asarray(zscore(b), float)
        rr = np.asarray(residual.predict(feats), float)
        rz = np.asarray(zscore(rr), float)
        ordered = np.sort(bz)
        gap = float(ordered[-1] - ordered[-2]) if len(ordered) >= 2 else 99.0
        base_ix = int(np.argmax(b))
        blend = (1.0 - beta) * bz + beta * rz
        candidate_ix = int(np.argmax(blend)) if gap <= v37_gate else base_ix
        phase = v34.v33.phase(row)
        blend_adv = float(blend[candidate_ix] - blend[base_ix]) if candidate_ix != base_ix else 0.0
        residual_adv = float(rz[candidate_ix] - rz[base_ix]) if candidate_ix != base_ix else 0.0
        residual_top = bool(int(np.argmax(rz)) == candidate_ix)
        if checked < 8:
            verify_fast_row(art, residual, row, b, eq, rs, feats, rz)
            checked += 1
        out.append({
            'baseIx': base_ix,
            'candidateIx': candidate_ix,
            'baseGap': gap,
            'blendAdv': blend_adv,
            'residualAdv': residual_adv,
            'residualTop': residual_top,
            'phase': phase,
            'hard': bool(row.get('hard')),
            'ranks': np.asarray([int(h.get('rank', 999)) for h in hints], np.int32),
            'equities': np.asarray([float(h.get('equity', 0.0)) for h in hints], float),
            'cohort': tune_cohort(row, i) if split == 'tune' else split,
        })
    if not out:
        raise RuntimeError(f'empty cache for {split}')
    print(f'V38_CACHE split={split} rows={len(out)} verify={checked} seconds={time.perf_counter()-t0:.3f}', flush=True)
    return out, checked


def policy_choice(c, p):
    b = int(c['baseIx'])
    q = int(c['candidateIx'])
    if not p.get('enabled', False) or q == b:
        return b
    if c['phase'] not in p['phases']:
        return b
    if c['baseGap'] > float(p['maxBaseGap']):
        return b
    if c['blendAdv'] < float(p['minBlendAdv']):
        return b
    if c['residualAdv'] < float(p['minResidualAdv']):
        return b
    if p.get('requireResidualTop', True) and not c['residualTop']:
        return b
    return q


def evaluate(rows, policy=None, cohort=None):
    total = top1 = top2 = top3 = hardn = hard1 = overrides = fixes = harms = 0
    losses = []
    phase_n = {p: 0 for p in ('bar', 'bearoff', 'race', 'contact')}
    phase_1 = {p: 0 for p in phase_n}
    for c in rows:
        if cohort is not None and c['cohort'] != cohort:
            continue
        b = int(c['baseIx'])
        ix = b if policy is None else policy_choice(c, policy)
        rank = int(c['ranks'][ix])
        base_rank = int(c['ranks'][b])
        top_eq = float(c['equities'][0])
        got_eq = float(c['equities'][ix])
        losses.append(max(0.0, top_eq - got_eq))
        total += 1
        top1 += rank == 1
        top2 += rank <= 2
        top3 += rank <= 3
        phase_n[c['phase']] += 1
        phase_1[c['phase']] += rank == 1
        if c['hard']:
            hardn += 1
            hard1 += rank == 1
        if ix != b:
            overrides += 1
            fixes += base_rank != 1 and rank == 1
            harms += base_rank == 1 and rank != 1
    if total == 0:
        raise RuntimeError('empty evaluation subset')
    return {
        'samples': total,
        'strictTop1': top1 / total,
        'top2': top2 / total,
        'top3': top3 / total,
        'meanEquityLoss': float(np.mean(losses)),
        'hardSamples': hardn,
        'hardStrictTop1': hard1 / hardn if hardn else None,
        'overrides': overrides,
        'fixes': fixes,
        'harms': harms,
        'netFixes': fixes - harms,
        'phaseSamples': phase_n,
        'phaseTop1': {p: (phase_1[p] / phase_n[p] if phase_n[p] else None) for p in phase_n},
    }


def delta(m, b):
    return {
        'strictTop1': m['strictTop1'] - b['strictTop1'],
        'top2': m['top2'] - b['top2'],
        'meanEquityLoss': m['meanEquityLoss'] - b['meanEquityLoss'],
        'hardStrictTop1': (m['hardStrictTop1'] or 0.0) - (b['hardStrictTop1'] or 0.0),
    }


def candidate_grid(v37_gate):
    max_gaps = sorted(set(x for x in (0.20, 0.35, 0.50, 0.75) if x <= v37_gate + 1e-12))
    if not max_gaps or abs(max_gaps[-1] - v37_gate) > 1e-12:
        max_gaps.append(float(v37_gate))
    for scope, phases in PHASE_SCOPES.items():
        for max_gap in max_gaps:
            for blend_adv in (0.05, 0.10, 0.20, 0.35, 0.50, 0.75):
                for residual_adv in (0.25, 0.50, 0.75, 1.00, 1.25, 1.50):
                    yield {
                        'enabled': True,
                        'scope': scope,
                        'phases': list(phases),
                        'maxBaseGap': float(max_gap),
                        'minBlendAdv': float(blend_adv),
                        'minResidualAdv': float(residual_adv),
                        'requireResidualTop': True,
                    }


def no_override(reason):
    return {
        'enabled': False,
        'scope': 'none',
        'phases': [],
        'maxBaseGap': 0.0,
        'minBlendAdv': 999.0,
        'minResidualAdv': 999.0,
        'requireResidualTop': True,
        'fallbackReason': reason,
    }


def selector_key(m, base_m):
    # Primary target: harvest v37's hard-position gain without sacrificing v33.
    # Overall Top-1/loss safety is enforced before this ordering is considered.
    hard_delta = (m['hardStrictTop1'] or 0.0) - (base_m['hardStrictTop1'] or 0.0)
    return (hard_delta, m['strictTop1'], -m['meanEquityLoss'], m['netFixes'], -m['overrides'])


def select_stage(rows, art, counts):
    t0 = time.perf_counter()
    sel37 = json.loads(V37_SELECTION.read_text())
    check_v37_selection(sel37)
    residual = joblib.load(V37_RESIDUAL)
    beta = float(sel37['selectedBeta'])
    gate = float(sel37['selectedGate'])
    tune_cache, checked = build_policy_cache(art, residual, rows, 'tune', beta, gate)
    base_select = evaluate(tune_cache, None, 'select')
    base_guard = evaluate(tune_cache, None, 'guard')

    trials = []
    best = None
    min_support = 25
    for p in candidate_grid(gate):
        m = evaluate(tune_cache, p, 'select')
        d = delta(m, base_select)
        safe = (
            m['overrides'] >= min_support and
            m['strictTop1'] + 1e-15 >= base_select['strictTop1'] and
            m['meanEquityLoss'] <= base_select['meanEquityLoss'] + 1e-15 and
            m['netFixes'] > 0
        )
        rec = {'policy': p, 'select': m, 'deltaVsBase': d, 'selectorSafe': safe}
        trials.append(rec)
        if safe:
            k = selector_key(m, base_select)
            if best is None or k > best[0]:
                best = (k, p, m, d)

    if best is None:
        selected_candidate = no_override('NO_SELECTOR_SAFE_POLICY')
        candidate_select = base_select
        candidate_guard = base_guard
        guard_passed = True
        frozen = selected_candidate
    else:
        selected_candidate = best[1]
        candidate_select = best[2]
        candidate_guard = evaluate(tune_cache, selected_candidate, 'guard')
        guard_passed = (
            candidate_guard['strictTop1'] + 1e-15 >= base_guard['strictTop1'] and
            candidate_guard['meanEquityLoss'] <= base_guard['meanEquityLoss'] + 1e-15 and
            candidate_guard['netFixes'] >= 0
        )
        frozen = dict(selected_candidate) if guard_passed else no_override('TUNE_GUARD_REJECTED_SELECTED_POLICY')

    frozen_select = evaluate(tune_cache, frozen, 'select')
    frozen_guard = evaluate(tune_cache, frozen, 'guard')
    out = {
        'model': 'mzand-gnu-v38',
        'architecture': 'V33_DEFAULT_WITH_TUNE_GUARDED_FROZEN_V37_SAFE_OVERRIDE',
        'stage': 'select',
        'counts': counts,
        'v37SelectedBeta': beta,
        'v37SelectedGate': gate,
        'v37ResidualFitSplits': ['train'],
        'v37ResidualRefitAfterSelection': False,
        'tuneSplitMethod': 'SHA256_POSITION_GROUP_MOD5_GUARD0',
        'tuneCacheEquivalenceRows': checked,
        'baseSelect': base_select,
        'baseGuard': base_guard,
        'selectedCandidatePolicy': selected_candidate,
        'candidateSelect': candidate_select,
        'candidateGuard': candidate_guard,
        'guardPassed': guard_passed,
        'frozenPolicy': frozen,
        'frozenSelect': frozen_select,
        'frozenGuard': frozen_guard,
        'selectorTrials': trials,
        'devOpened': False,
        'devUsedForModelSelection': False,
        'devRowsMined': 0,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
    }
    POLICY.write_text(json.dumps(out, indent=2) + '\n')
    SELECT_REPORT.write_text('\n'.join([
        'MODEL: mzand-gnu-v38',
        'STAGE: SELECT_TUNE_ONLY',
        'ARCHITECTURE: V33_DEFAULT_WITH_TUNE_GUARDED_FROZEN_V37_SAFE_OVERRIDE',
        f'V37_BETA: {beta:.2f}',
        f'V37_GATE: {gate:.2f}',
        f'TUNE_SELECT_SAMPLES: {base_select["samples"]}',
        f'TUNE_GUARD_SAMPLES: {base_guard["samples"]}',
        f'BASE_SELECT_TOP1: {base_select["strictTop1"]:.6f}',
        f'BASE_SELECT_LOSS: {base_select["meanEquityLoss"]:.6f}',
        f'BASE_SELECT_HARD_TOP1: {base_select["hardStrictTop1"]:.6f}',
        f'CANDIDATE_SELECT_TOP1: {candidate_select["strictTop1"]:.6f}',
        f'CANDIDATE_SELECT_LOSS: {candidate_select["meanEquityLoss"]:.6f}',
        f'CANDIDATE_SELECT_HARD_TOP1: {candidate_select["hardStrictTop1"]:.6f}',
        f'CANDIDATE_SELECT_OVERRIDES: {candidate_select["overrides"]}',
        f'CANDIDATE_SELECT_NET_FIXES: {candidate_select["netFixes"]}',
        f'BASE_GUARD_TOP1: {base_guard["strictTop1"]:.6f}',
        f'BASE_GUARD_LOSS: {base_guard["meanEquityLoss"]:.6f}',
        f'CANDIDATE_GUARD_TOP1: {candidate_guard["strictTop1"]:.6f}',
        f'CANDIDATE_GUARD_LOSS: {candidate_guard["meanEquityLoss"]:.6f}',
        f'CANDIDATE_GUARD_OVERRIDES: {candidate_guard["overrides"]}',
        f'CANDIDATE_GUARD_NET_FIXES: {candidate_guard["netFixes"]}',
        f'GUARD_PASSED: {guard_passed}',
        f'POLICY_ENABLED: {frozen["enabled"]}',
        f'POLICY_SCOPE: {frozen["scope"]}',
        f'POLICY_MAX_BASE_GAP: {frozen["maxBaseGap"]:.2f}',
        f'POLICY_MIN_BLEND_ADV: {frozen["minBlendAdv"]:.2f}',
        f'POLICY_MIN_RESIDUAL_ADV: {frozen["minResidualAdv"]:.2f}',
        'RESIDUAL_FIT_SPLITS: train',
        'RESIDUAL_REFIT_AFTER_SELECTION: False',
        'DEV_OPENED: False',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'DEV_ROWS_MINED: 0',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
        f'SELECT_SECONDS: {time.perf_counter()-t0:.3f}',
    ]) + '\n')
    print(SELECT_REPORT.read_text(), flush=True)


def check_policy(sel):
    if sel.get('model') != 'mzand-gnu-v38' or sel.get('stage') != 'select':
        raise SystemExit('invalid v38 policy artifact')
    if sel.get('devOpened') is not False or sel.get('devUsedForModelSelection') is not False:
        raise SystemExit('v38 selection dev provenance invalid')
    if sel.get('devRowsMined') != 0:
        raise SystemExit('v38 selection dev mining invalid')
    if sel.get('pristineDataUsed') is not False or sel.get('xgLabelsUsed') is not False:
        raise SystemExit('v38 forbidden-data provenance invalid')
    if sel.get('v37ResidualFitSplits') != ['train'] or sel.get('v37ResidualRefitAfterSelection') is not False:
        raise SystemExit('v38 residual provenance invalid')


def final_stage(rows, art, counts):
    t0 = time.perf_counter()
    sel = json.loads(POLICY.read_text())
    check_policy(sel)
    residual = joblib.load(V37_RESIDUAL)
    beta = float(sel['v37SelectedBeta'])
    gate = float(sel['v37SelectedGate'])
    frozen = sel['frozenPolicy']
    dev_cache, checked = build_policy_cache(art, residual, rows, 'dev', beta, gate)
    base_dev = evaluate(dev_cache, None)
    dev = evaluate(dev_cache, frozen)
    d = delta(dev, base_dev)
    out = {
        'model': 'mzand-gnu-v38',
        'architecture': 'V33_DEFAULT_WITH_TUNE_GUARDED_FROZEN_V37_SAFE_OVERRIDE',
        'counts': counts,
        'v37SelectedBeta': beta,
        'v37SelectedGate': gate,
        'frozenPolicy': frozen,
        'guardPassed': bool(sel['guardPassed']),
        'baseDev': base_dev,
        'dev': dev,
        'deltaVsBase': d,
        'devCacheEquivalenceRows': checked,
        'residualFitSplits': ['train'],
        'residualRefitAfterSelection': False,
        'devUsedForModelSelection': False,
        'devRowsMined': 0,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
    }
    joblib.dump({
        'version': 'mzand-gnu-v38',
        'architecture': out['architecture'],
        'baseModel': 'gnu-phase-experts-v33',
        'baseRunId': 31561338583,
        'residualModel': 'mzand-gnu-v37-train-only-residual',
        'residualRunId': 31679869523,
        'residualRanker': residual,
        'beta': beta,
        'v37Gate': gate,
        'safeOverridePolicy': frozen,
        'residualFitSplits': ['train'],
        'residualRefitAfterSelection': False,
        'devUsedForModelSelection': False,
        'devRowsMined': 0,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
    }, FINAL_MODEL)
    FINAL_JSON.write_text(json.dumps(out, indent=2) + '\n')
    FINAL_REPORT.write_text('\n'.join([
        'MODEL: mzand-gnu-v38',
        'ARCHITECTURE: V33_DEFAULT_WITH_TUNE_GUARDED_FROZEN_V37_SAFE_OVERRIDE',
        f'POLICY_ENABLED: {frozen["enabled"]}',
        f'POLICY_SCOPE: {frozen["scope"]}',
        f'POLICY_MAX_BASE_GAP: {float(frozen["maxBaseGap"]):.2f}',
        f'POLICY_MIN_BLEND_ADV: {float(frozen["minBlendAdv"]):.2f}',
        f'POLICY_MIN_RESIDUAL_ADV: {float(frozen["minResidualAdv"]):.2f}',
        f'GUARD_PASSED: {sel["guardPassed"]}',
        f'TRAIN_POSITION_SAMPLES: {counts["train"]}',
        f'TUNE_POSITION_SAMPLES: {counts["tune"]}',
        f'DEV_POSITION_SAMPLES: {counts["dev"]}',
        f'BASE_DEV_STRICT_TOP1: {base_dev["strictTop1"]:.6f}',
        f'BASE_DEV_TOP2: {base_dev["top2"]:.6f}',
        f'BASE_DEV_TOP3: {base_dev["top3"]:.6f}',
        f'BASE_DEV_MEAN_EQUITY_LOSS: {base_dev["meanEquityLoss"]:.6f}',
        f'BASE_DEV_HARD_STRICT_TOP1: {base_dev["hardStrictTop1"]:.6f}',
        f'DEV_STRICT_TOP1: {dev["strictTop1"]:.6f}',
        f'DEV_TOP2: {dev["top2"]:.6f}',
        f'DEV_TOP3: {dev["top3"]:.6f}',
        f'DEV_MEAN_EQUITY_LOSS: {dev["meanEquityLoss"]:.6f}',
        f'DEV_HARD_SAMPLES: {dev["hardSamples"]}',
        f'DEV_HARD_STRICT_TOP1: {dev["hardStrictTop1"]:.6f}',
        f'DEV_OVERRIDES: {dev["overrides"]}',
        f'DEV_FIXES: {dev["fixes"]}',
        f'DEV_HARMS: {dev["harms"]}',
        f'DEV_NET_FIXES: {dev["netFixes"]}',
        f'DELTA_STRICT_TOP1_VS_BASE: {d["strictTop1"]:+.6f}',
        f'DELTA_HARD_STRICT_TOP1_VS_BASE: {d["hardStrictTop1"]:+.6f}',
        f'DELTA_MEAN_EQUITY_LOSS_VS_BASE: {d["meanEquityLoss"]:+.6f}',
        'RESIDUAL_FIT_SPLITS: train',
        'RESIDUAL_REFIT_AFTER_SELECTION: False',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'DEV_ROWS_MINED: 0',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
        f'FINAL_SECONDS: {time.perf_counter()-t0:.3f}',
    ]) + '\n')
    print(FINAL_REPORT.read_text(), flush=True)


def write_exec_report():
    EXEC_REPORT.write_text('\n'.join([
        'EXECUTION: GNU_V38_SAFE_OVERRIDE',
        'BASE: VERIFIED_GNU_V33',
        'RESIDUAL: FROZEN_GNU_V37_TRAIN_ONLY',
        'TUNE_GROUP_GUARD: True',
        'RESIDUAL_REFIT_AFTER_SELECTION: False',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'DEV_ROWS_MINED: 0',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
        f'TOTAL_SECONDS: {time.perf_counter()-START:.3f}',
    ]) + '\n')
    print(EXEC_REPORT.read_text(), flush=True)


def main():
    rows, art, counts = base.load_inputs()
    if STAGE == 'select':
        select_stage(rows, art, counts)
    elif STAGE == 'final':
        final_stage(rows, art, counts)
    elif STAGE == 'all':
        select_stage(rows, art, counts)
        final_stage(rows, art, counts)
    else:
        raise SystemExit(f'unknown GNU_V38_STAGE={STAGE!r}')
    write_exec_report()


if __name__ == '__main__':
    main()
