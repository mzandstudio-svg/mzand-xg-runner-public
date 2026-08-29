#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import importlib.util
import sys
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R59B requires Windows")

TARGET = Path(__file__).resolve().with_name("r59-xg-network-access-trace.py")
spec = importlib.util.spec_from_file_location("r59_trace_impl", TARGET)
if spec is None or spec.loader is None:
    raise SystemExit(f"cannot load {TARGET}")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

# DEBUG_EVENT is a native debugger-side structure. On the 64-bit GitHub runner
# its union is 8-byte aligned and starts at offset 16; the original R59 parser
# used the 32-bit offset 12. Redirect only the exact exception-code read while
# leaving every other struct.unpack_from call untouched.
_native_unpack_from = mod.struct.unpack_from
_union_offset = 16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 12


def _abi_unpack_from(fmt, buffer, offset=0):
    if fmt == "<I" and offset == 12 and len(buffer) >= _union_offset + 4:
        offset = _union_offset
    return _native_unpack_from(fmt, buffer, offset)


mod.struct.unpack_from = _abi_unpack_from
print(f"R59B_DEBUG_EVENT_UNION_OFFSET={_union_offset}", flush=True)
raise SystemExit(mod.main())
