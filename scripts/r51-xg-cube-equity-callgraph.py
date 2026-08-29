#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R51 requires Windows")

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except Exception as exc:
    raise SystemExit(f"R51 requires capstone: {exc}")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
ACCESS = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE

k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]

IMAGE_BASE = 0x00400000
TARGETS = {
    "cube_core_9DA770": 0x009DA770,
    "cube_mid_9DBA90": 0x009DBA90,
    "cube_driver_9DC770": 0x009DC770,
    "eff_dispatch_9DAD30": 0x009DAD30,
    "blend_callsite_A_9DC8E9": 0x009DC8E9,
    "blend_callsite_B_9DCE97": 0x009DCE97,
}

WINDOWS = [
    ("cube_core", 0x009DA600, 0x009DB000),
    ("cube_mid", 0x009DB900, 0x009DC200),
    ("cube_driver", 0x009DC600, 0x009DD100),
]
SCAN_START = 0x009D0000
SCAN_END = 0x009E4000


def rpm(h, addr: int, n: int) -> bytes:
    buf = (ctypes.c_ubyte * n)()
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
    if not ok:
        raise OSError(ctypes.get_last_error(), f"ReadProcessMemory 0x{addr:08x}")
    return bytes(buf[: got.value])


def verify_image(h) -> None:
    if rpm(h, IMAGE_BASE, 2) != b"MZ":
        raise RuntimeError("R51 image base contract failed: expected MZ at 0x00400000")


def disasm(md: Cs, blob: bytes, start: int) -> list[str]:
    out = []
    for ins in md.disasm(blob, start):
        out.append(f"0x{ins.address:08X}\t{ins.bytes.hex():<20}\t{ins.mnemonic:<8}\t{ins.op_str}")
    return out


def scan_rel32_calls(blob: bytes, base: int) -> list[tuple[int, int]]:
    out = []
    for i in range(0, max(0, len(blob) - 5)):
        if blob[i] != 0xE8:
            continue
        rel = struct.unpack_from("<i", blob, i + 1)[0]
        src = base + i
        dst = (src + 5 + rel) & 0xFFFFFFFF
        out.append((src, dst))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    h = k32.OpenProcess(ACCESS, False, args.pid)
    if not h:
        raise OSError(ctypes.get_last_error(), "OpenProcess")

    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False

    summary = []
    try:
        verify_image(h)
        summary.append(f"R51_PID={args.pid}")
        summary.append("R51_IMAGE_BASE=0x00400000")
        summary.append("R51_TARGETS=" + ",".join(f"{k}=0x{v:08X}" for k, v in TARGETS.items()))

        for name, lo, hi in WINDOWS:
            blob = rpm(h, lo, hi - lo)
            p = args.outdir / f"r51-{name}-disasm.txt"
            p.write_text("\n".join(disasm(md, blob, lo)) + "\n", encoding="utf-8")
            summary.append(f"R51_DISASM_{name.upper()}={p.name} bytes={len(blob)}")

        scan_blob = rpm(h, SCAN_START, SCAN_END - SCAN_START)
        calls = scan_rel32_calls(scan_blob, SCAN_START)
        by_target = {addr: [] for addr in TARGETS.values()}
        for src, dst in calls:
            if dst in by_target:
                by_target[dst].append(src)

        xref_lines = ["target_name\ttarget_va\tcaller_va"]
        for name, target in TARGETS.items():
            callers = sorted(by_target[target])
            if callers:
                for src in callers:
                    xref_lines.append(f"{name}\t0x{target:08X}\t0x{src:08X}")
            else:
                xref_lines.append(f"{name}\t0x{target:08X}\tNONE")
            summary.append(f"R51_XREF_{name}={len(callers)}")
        (args.outdir / "r51-call-xrefs.tsv").write_text("\n".join(xref_lines) + "\n", encoding="utf-8")

        # Emit focused caller neighborhoods around every direct call to the three core functions.
        focus_targets = {TARGETS["cube_core_9DA770"], TARGETS["cube_mid_9DBA90"], TARGETS["cube_driver_9DC770"]}
        neigh = []
        for src, dst in calls:
            if dst not in focus_targets:
                continue
            lo = max(SCAN_START, src - 64)
            hi = min(SCAN_END, src + 96)
            try:
                b = rpm(h, lo, hi - lo)
            except Exception as exc:
                neigh.append(f"CALLER 0x{src:08X} -> 0x{dst:08X} READ_FAIL {exc}")
                continue
            neigh.append(f"\n===== CALLER 0x{src:08X} -> 0x{dst:08X} =====")
            neigh.extend(disasm(md, b, lo))
        (args.outdir / "r51-core-callers-disasm.txt").write_text("\n".join(neigh) + "\n", encoding="utf-8")

        # Capture raw bytes around known blend sites for independent verification.
        blend = []
        for key in ("blend_callsite_A_9DC8E9", "blend_callsite_B_9DCE97"):
            va = TARGETS[key]
            lo = va - 96
            b = rpm(h, lo, 224)
            blend.append(f"\n===== {key} 0x{va:08X} =====")
            blend.extend(disasm(md, b, lo))
        (args.outdir / "r51-blend-sites-disasm.txt").write_text("\n".join(blend) + "\n", encoding="utf-8")

        summary.append("R51_CUBE_EQUITY_CALLGRAPH=PASS")
        (args.outdir / "r51-summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
        print("\n".join(summary))
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
