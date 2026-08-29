#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import importlib.util
import math
import struct
import sys
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R63 requires Windows")

TARGET = Path(__file__).resolve().with_name("r59-xg-network-access-trace.py")
spec = importlib.util.spec_from_file_location("r63_trace_impl", TARGET)
if spec is None or spec.loader is None:
    raise SystemExit(f"cannot load {TARGET}")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

# GitHub hosted runners are 64-bit while XG itself is a 32-bit/WOW64 process.
# DEBUG_EVENT therefore aligns its union at byte 16 in the debugger process.
_native_unpack_from = mod.struct.unpack_from
_union_offset = 16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 12


def _abi_unpack_from(fmt, buffer, offset=0):
    if fmt == "<I" and offset == 12 and len(buffer) >= _union_offset + 4:
        offset = _union_offset
    return _native_unpack_from(fmt, buffer, offset)


mod.struct.unpack_from = _abi_unpack_from

# R62 proved that the old decoded model is present in current official XG2 RAM.
# The unique first pair was observed as:
#   0.943710923 (bits 0x3F71970A), -3.5759213
# The five historical tensor starts are contiguous offsets within that decoded
# float payload. R63 locates the decoded base by the proven pair and watches the
# first four tensor starts (the x86 hardware limit is four DR slots).
KNOWN0_BITS = 0x3F71970A
KNOWN0_PATTERN = struct.pack("<I", KNOWN0_BITS)
KNOWN1 = -3.5759213
TENSOR_FLOAT_OFFSETS = [0, 53261, 110101, 166941, 172716]


def _scan_decoded_payload(h, _model_bytes):
    matches = []
    chunk_size = 2 * 1024 * 1024
    seen_bases = set()

    for region_base, region_size, state, protect, mem_type in mod.iter_regions(h):
        if state != mod.MEM_COMMIT or (protect & mod.PAGE_NOACCESS) or (protect & mod.PAGE_GUARD):
            continue
        pos = 0
        carry = b""
        while pos < region_size:
            n = min(chunk_size, region_size - pos)
            data = mod.rpm(h, region_base + pos, n)
            if not data:
                pos += n
                carry = b""
                continue
            buf = carry + data
            buf_base = region_base + pos - len(carry)
            p = 0
            while True:
                j = buf.find(KNOWN0_PATTERN, p)
                if j < 0:
                    break
                if j + 8 <= len(buf):
                    v1 = struct.unpack_from("<f", buf, j + 4)[0]
                    decoded_base = buf_base + j
                    if (
                        math.isfinite(v1)
                        and abs(v1 - KNOWN1) <= 2e-4
                        and decoded_base not in seen_bases
                        and (decoded_base & 3) == 0
                    ):
                        # Verify every inferred tensor address is readable and
                        # starts with finite float32 data before arming DRx.
                        inferred = []
                        ok = True
                        for ti, foff in enumerate(TENSOR_FLOAT_OFFSETS):
                            addr = decoded_base + 4 * foff
                            probe = mod.rpm(h, addr, 24)
                            if len(probe) != 24:
                                ok = False
                                break
                            vals = struct.unpack("<6f", probe)
                            if not all(math.isfinite(v) for v in vals):
                                ok = False
                                break
                            inferred.append(
                                mod.MemMatch(
                                    tensor=ti,
                                    file_offset=12 + 4 * foff,
                                    address=addr,
                                    region_base=region_base,
                                    region_size=region_size,
                                    protect=protect,
                                    mem_type=mem_type,
                                )
                            )
                        if ok:
                            matches.extend(inferred)
                            seen_bases.add(decoded_base)
                p = j + 1
            carry = buf[-16:] if len(buf) >= 16 else buf
            pos += n

    return matches


mod.scan_signatures = _scan_decoded_payload
print(f"R63_DEBUG_EVENT_UNION_OFFSET={_union_offset}", flush=True)
print("R63_ANCHOR_BITS=0x3F71970A", flush=True)
print("R63_DECODED_TENSOR_OFFSETS=" + ",".join(str(x) for x in TENSOR_FLOAT_OFFSETS), flush=True)
raise SystemExit(mod.main())
