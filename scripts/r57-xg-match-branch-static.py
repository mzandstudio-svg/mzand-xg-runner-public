#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('R57 requires Windows')

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
ACCESS = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]

TARGETS = {
    # Exact helper reached repeatedly by the non-money branch of 0x9DBA90.
    'match_table_builder_9DB220': (0x009DB220, 0x0870),
    # Alternate efficiency/blend helper used before the second 0x9DBA90 call.
    'branch_blend_helper_9DABA0': (0x009DABA0, 0x04B0),
    # Full mid-function including money and match/MET branches.
    'cube_mid_9DBA90': (0x009DBA90, 0x0B80),
    # Caller containing Branch A, Branch B, recursive recube paths and blends.
    'cube_driver_9DC770': (0x009DC770, 0x08B0),
    # Immediate wrapper/caller area for root action materialization.
    'cube_root_9DD030': (0x009DD030, 0x0360),
}

SCANS = [
    ('region_6f', 0x006F0000, 0x00710000),
    ('region_9d', 0x009D0000, 0x009E4000),
]

# Small data windows referenced directly by the branch math.
RAW_WINDOWS = {
    'mid_constants_9DC610': (0x009DC610, 0x30),
    'evaluator_global_B0AD18': (0x00B0AD18, 0x10),
    'global_flags_A12620': (0x00A12620, 0x20),
}


def rpm(h, addr: int, n: int) -> bytes:
    buf = (ctypes.c_ubyte * n)()
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(), f'RPM 0x{addr:08X}')
    return bytes(buf[:got.value])


def disasm(md, blob: bytes, addr: int) -> list[str]:
    return [
        f'0x{i.address:08X}\t{i.bytes.hex():<24}\t{i.mnemonic:<9}\t{i.op_str}'
        for i in md.disasm(blob, addr)
    ]


def calls(blob: bytes, base: int, targets: set[int]):
    out = []
    for i in range(max(0, len(blob) - 5)):
        if blob[i] != 0xE8:
            continue
        rel = struct.unpack_from('<i', blob, i + 1)[0]
        src = base + i
        dst = (src + 5 + rel) & 0xffffffff
        if dst in targets:
            out.append((src, dst))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--outdir', type=Path, required=True)
    a = ap.parse_args()
    a.outdir.mkdir(parents=True, exist_ok=True)

    h = k32.OpenProcess(ACCESS, False, a.pid)
    if not h:
        raise OSError(ctypes.get_last_error(), 'OpenProcess')

    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.skipdata = True
    summary = [f'R57_PID={a.pid}']
    try:
        if rpm(h, 0x400000, 2) != b'MZ':
            raise RuntimeError('R57 image-base contract failed')

        for name, (addr, size) in TARGETS.items():
            blob = rpm(h, addr, size)
            p = a.outdir / f'r57-{name}-disasm.txt'
            p.write_text('\n'.join(disasm(md, blob, addr)) + '\n', encoding='utf-8')
            summary.append(f'R57_DUMP_{name}=0x{addr:08X} bytes={len(blob)} file={p.name}')

        raw_lines = ['name\taddress\tbytes\tf32_words\tu32_words']
        for name, (addr, size) in RAW_WINDOWS.items():
            blob = rpm(h, addr, size)
            n4 = len(blob) // 4
            f32s = struct.unpack('<' + 'f' * n4, blob[:n4 * 4]) if n4 else ()
            u32s = struct.unpack('<' + 'I' * n4, blob[:n4 * 4]) if n4 else ()
            raw_lines.append(
                f'{name}\t0x{addr:08X}\t{blob.hex()}\t' +
                ','.join(f'{x:.9g}' for x in f32s) + '\t' +
                ','.join(f'0x{x:08X}' for x in u32s)
            )
        (a.outdir / 'r57-raw-windows.tsv').write_text('\n'.join(raw_lines) + '\n', encoding='utf-8')

        target_addrs = {v[0] for v in TARGETS.values()} | {
            0x009DA770, 0x009D5C80, 0x009DAD30, 0x009DC630, 0x009DC690,
        }
        xs = ['scan\tcaller_va\ttarget_va']
        for scan_name, lo, hi in SCANS:
            blob = rpm(h, lo, hi - lo)
            xs += [f'{scan_name}\t0x{s:08X}\t0x{d:08X}' for s, d in calls(blob, lo, target_addrs)]
        (a.outdir / 'r57-match-branch-xrefs.tsv').write_text('\n'.join(xs) + '\n', encoding='utf-8')

        # Machine-check the key static branch shape so accidental address drift is loud.
        driver = rpm(h, 0x009DC770, 0x08B0)
        required = {
            'CALL_BRANCH_A_9DBA90': (0x009DC7E6, 0x009DBA90),
            'CALL_BRANCH_B_9DBA90': (0x009DCD7F, 0x009DBA90),
            'CALL_ALT_BLEND_9DABA0': (0x009DCD37, 0x009DABA0),
            'CALL_EFF_B_9DAD30': (0x009DCE97, 0x009DAD30),
            'RECURSE_B_9DCF29': (0x009DCF29, 0x009DC770),
        }
        found = {(s, d) for s, d in calls(driver, 0x009DC770, {d for _, d in required.values()})}
        for label, pair in required.items():
            ok = pair in found
            summary.append(f'R57_{label}={"PASS" if ok else "FAIL"}')
            if not ok:
                raise RuntimeError(f'R57 static branch contract drift: {label} expected {pair}')

        summary.append('R57_XG_MATCH_BRANCH_STATIC=PASS')
        (a.outdir / 'r57-summary.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
        print('\n'.join(summary))
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == '__main__':
    raise SystemExit(main())
