#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

p = Path(__file__).resolve().with_name("r74-xg-checker-depth-keyboard-oracle.py")
spec = importlib.util.spec_from_file_location("r74_keyboard_impl", p)
if spec is None or spec.loader is None:
    raise SystemExit(f"cannot load {p}")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

level = int(os.environ["R74_ONLY_LEVEL"])
rows = [r for r in mod.LEVELS if r[1] == level]
if len(rows) != 1:
    raise SystemExit(f"invalid R74_ONLY_LEVEL={level}")
mod.LEVELS = rows
print(f"R74_MATRIX_ONLY_LEVEL={level}", flush=True)
raise SystemExit(mod.main())
