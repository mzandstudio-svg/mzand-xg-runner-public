#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
src = here / 'r52-xg-endpoint-origin-trace.py'
spec = importlib.util.spec_from_file_location('r52probe', src)
if spec is None or spec.loader is None:
    raise SystemExit('R52C failed to load base probe')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def external_only(pid: int) -> None:
    print(f'R52C_INTERNAL_UI_TRIGGER=DISABLED PID={pid}', flush=True)

mod.trigger_analyze_position = external_only
raise SystemExit(mod.main())
