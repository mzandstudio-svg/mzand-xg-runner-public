#!/usr/bin/env python3
"""GNU v37: freeze the tune-selected train-only v35 residual for sealed dev.

Motivation
----------
GNU v35 selected beta/gate using a residual fitted on TRAIN only, then refit the
residual on TRAIN+TUNE before opening sealed DEV.  The v36 cached execution
proved that this exact procedure is fast and deterministic, but its held-out
result regressed slightly versus v33 even though TUNE improved strongly.

v37 isolates that post-selection model-shift variable:
  select: fit residual on TRAIN only; select beta+gate on TUNE only; save the
          exact fitted residual and frozen selection.
  final:  load that exact residual unchanged; open DEV once; no refit.

Everything else stays aligned with the v35/v36 scientific contract:
- same frozen corpus and verified v33 base model,
- same residual XGBRanker parameters and seed 3501,
- same beta/gate grid and metric key,
- no dev mining/model selection,
- no pristine data,
- no XG labels.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import joblib

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


cache = load('mzand_v37_cache', HERE / 'run-mzand-gnu-v35-cached-v36.py')
base = cache.base

STAGE = os.environ.get('GNU_V37_STAGE', 'all').strip().lower()
SELECTION = Path(os.environ.get('GNU_V37_SELECTION', 'mzand-gnu-v37-selection.json'))
RESIDUAL = Path(os.environ.get('GNU_V37_RESIDUAL', 'mzand-gnu-v37-train-only-residual.joblib'))
SELECT_REPORT = Path('mzand-gnu-v37-selection-report.txt')
FINAL_REPORT = Path('mzand-gnu-v37-frozen-residual-report.txt')
FINAL_JSON = Path('mzand-gnu-v37-frozen-residual-report.json')
FINAL_MODEL = Path('mzand-gnu-v37-frozen-residual.joblib')
EXEC_REPORT = Path('mzand-gnu-v37-execution-report.txt')


def _grid():
    for beta in (0.0, 0.20, 0.35, 0.50, 0.65, 0.80):
        gates = (0.0,) if beta == 0 else (0.10, 0.20, 0.35, 0.50, 0.75, 1.00, 1.50, 2.50, 9.00)
        for gate in gates:
            yield beta, gate


def _check_selection(sel):
    required_false = ('devUsedForModelSelection', 'pristineDataUsed', 'xgLabelsUsed', 'residualRefitAfterSelection')
    for k in required_false:
        if sel.get(k) is not False:
            raise SystemExit(f'selection provenance invalid: {k}={sel.get(k)!r}')
    if sel.get('devRowsMined') != 0:
        raise SystemExit('selection provenance invalid: devRowsMined')
    if sel.get('residualFitSplits') != ['train']:
        raise SystemExit(f"selection residual split invalid: {sel.get('residualFitSplits')!r}")


def select_stage(rows, art, counts):
    t0 = time.perf_counter()
    residual, stats = cache.train_cached(art, rows, ['train'], 3501)
    trials = []
    best = None
    for beta, gate in _grid():
        m = cache.evaluate_cached(art, residual, beta, gate, rows, 'tune')
        trials.append({'beta': beta, 'gate': gate, 'tune': m})
        k = base.mkey(m)
        if best is None or k > best[0]:
            best = (k, beta, gate, m)
    beta, gate, tune = best[1], best[2], best[3]
    out = {
        'model': 'mzand-gnu-v37',
        'architecture': 'V33_PLUS_FROZEN_TRAIN_ONLY_CONFIDENCE_GATED_RESIDUAL',
        'stage': 'select',
        'counts': counts,
        'selectedBeta': beta,
        'selectedGate': gate,
        'selectedTune': tune,
        'trainMining': stats,
        'tuneTrials': trials,
        'residualSeed': 3501,
        'residualFitSplits': ['train'],
        'residualRefitAfterSelection': False,
        'devOpened': False,
        'devUsedForModelSelection': False,
        'devRowsMined': 0,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
    }
    joblib.dump(residual, RESIDUAL)
    SELECTION.write_text(json.dumps(out, indent=2) + '\n')
    SELECT_REPORT.write_text('\n'.join([
        'MODEL: mzand-gnu-v37',
        'STAGE: SELECT_TRAIN_TUNE_ONLY',
        'ARCHITECTURE: V33_PLUS_FROZEN_TRAIN_ONLY_CONFIDENCE_GATED_RESIDUAL',
        f'SELECTED_BETA: {beta:.2f}',
        f'SELECTED_GATE: {gate:.2f}',
        f'TUNE_STRICT_TOP1: {tune["strictTop1"]:.6f}',
        f'TUNE_TOP2: {tune["top2"]:.6f}',
        f'TUNE_MEAN_EQUITY_LOSS: {tune["meanEquityLoss"]:.6f}',
        f'TUNE_HARD_STRICT_TOP1: {tune["hardStrictTop1"]:.6f}',
        f'TUNE_GATED_ROWS: {tune["gatedRows"]}',
        f'TRAIN_MINED_ROWS: {stats["minedRows"]}',
        f'TRAIN_BASE_WRONG_ROWS: {stats["baseWrongRows"]}',
        f'TRAIN_POSITION_SAMPLES: {counts["train"]}',
        f'TUNE_POSITION_SAMPLES: {counts["tune"]}',
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


def final_stage(rows, art, counts):
    t0 = time.perf_counter()
    sel = json.loads(SELECTION.read_text())
    _check_selection(sel)
    residual = joblib.load(RESIDUAL)
    beta = float(sel['selectedBeta'])
    gate = float(sel['selectedGate'])

    # Baseline and candidate share the exact same cached v33/residual predictions.
    # beta=0 is the frozen v33 decision on this exact dev corpus.
    base_dev = cache.evaluate_cached(art, residual, 0.0, 0.0, rows, 'dev')
    dev = cache.evaluate_cached(art, residual, beta, gate, rows, 'dev')
    out = {
        'model': 'mzand-gnu-v37',
        'architecture': 'V33_PLUS_FROZEN_TRAIN_ONLY_CONFIDENCE_GATED_RESIDUAL',
        'counts': counts,
        'selectedBeta': beta,
        'selectedGate': gate,
        'residualSeed': int(sel['residualSeed']),
        'residualFitSplits': ['train'],
        'residualRefitAfterSelection': False,
        'trainMining': sel['trainMining'],
        'tuneTrials': sel['tuneTrials'],
        'baseDev': base_dev,
        'dev': dev,
        'deltaStrictTop1VsBase': dev['strictTop1'] - base_dev['strictTop1'],
        'deltaHardStrictTop1VsBase': (dev['hardStrictTop1'] or 0.0) - (base_dev['hardStrictTop1'] or 0.0),
        'deltaMeanEquityLossVsBase': dev['meanEquityLoss'] - base_dev['meanEquityLoss'],
        'devUsedForModelSelection': False,
        'devRowsMined': 0,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
    }
    # Keep the research artifact compact: reference the verified v33 base by
    # provenance instead of duplicating its ~200 MB payload inside this file.
    joblib.dump({
        'version': 'mzand-gnu-v37',
        'architecture': out['architecture'],
        'baseModel': 'gnu-phase-experts-v33',
        'baseRunId': 31561338583,
        'residualRanker': residual,
        'beta': beta,
        'gate': gate,
        'residualSeed': int(sel['residualSeed']),
        'residualFitSplits': ['train'],
        'residualRefitAfterSelection': False,
        'devUsedForModelSelection': False,
        'devRowsMined': 0,
        'pristineDataUsed': False,
        'xgLabelsUsed': False,
    }, FINAL_MODEL)
    FINAL_JSON.write_text(json.dumps(out, indent=2) + '\n')
    FINAL_REPORT.write_text('\n'.join([
        'MODEL: mzand-gnu-v37',
        'ARCHITECTURE: V33_PLUS_FROZEN_TRAIN_ONLY_CONFIDENCE_GATED_RESIDUAL',
        f'SELECTED_BETA: {beta:.2f}',
        f'SELECTED_GATE: {gate:.2f}',
        f'TRAIN_POSITION_SAMPLES: {counts["train"]}',
        f'TUNE_POSITION_SAMPLES: {counts["tune"]}',
        f'DEV_POSITION_SAMPLES: {counts["dev"]}',
        f'BASE_DEV_STRICT_TOP1: {base_dev["strictTop1"]:.6f}',
        f'BASE_DEV_TOP2: {base_dev["top2"]:.6f}',
        f'BASE_DEV_MEAN_EQUITY_LOSS: {base_dev["meanEquityLoss"]:.6f}',
        f'BASE_DEV_HARD_STRICT_TOP1: {base_dev["hardStrictTop1"]:.6f}',
        f'DEV_STRICT_TOP1: {dev["strictTop1"]:.6f}',
        f'DEV_TOP2: {dev["top2"]:.6f}',
        f'DEV_TOP3: {dev["top3"]:.6f}',
        f'DEV_MEAN_EQUITY_LOSS: {dev["meanEquityLoss"]:.6f}',
        f'DEV_HARD_SAMPLES: {dev["hardSamples"]}',
        f'DEV_HARD_STRICT_TOP1: {dev["hardStrictTop1"]:.6f}',
        f'DEV_GATED_ROWS: {dev["gatedRows"]}',
        f'DELTA_STRICT_TOP1_VS_BASE: {out["deltaStrictTop1VsBase"]:+.6f}',
        f'DELTA_HARD_STRICT_TOP1_VS_BASE: {out["deltaHardStrictTop1VsBase"]:+.6f}',
        f'DELTA_MEAN_EQUITY_LOSS_VS_BASE: {out["deltaMeanEquityLossVsBase"]:+.6f}',
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
    lines = [
        'EXECUTION: GNU_V37_FROZEN_RESIDUAL',
        'SCIENTIFIC_BASE: GNU_V35_CACHED_V36',
        'KEY_CHANGE: NO_POST_SELECTION_RESIDUAL_REFIT',
        'RESIDUAL_REFIT_AFTER_SELECTION: False',
        'DEV_USED_FOR_MODEL_SELECTION: False',
        'DEV_ROWS_MINED: 0',
        'PRISTINE_DATA_USED: False',
        'XG_LABELS_USED: False',
    ]
    for split, meta in sorted(cache.CACHE_META.items()):
        lines.append(f'{split.upper()}_CACHE_ROWS: {meta["rows"]}')
        lines.append(f'{split.upper()}_CACHE_EQUIVALENCE_ROWS: {meta["equivalenceRows"]}')
    for k, v in sorted(cache.TIMINGS.items()):
        lines.append(f'TIMING_{k.upper()}: {v:.3f}')
    lines.append(f'TOTAL_SECONDS: {time.perf_counter()-START:.3f}')
    EXEC_REPORT.write_text('\n'.join(lines) + '\n')
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
        raise SystemExit(f'unknown GNU_V37_STAGE={STAGE!r}')
    write_exec_report()


if __name__ == '__main__':
    main()
