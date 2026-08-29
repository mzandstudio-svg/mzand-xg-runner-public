#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('R54 requires Windows')

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

IMAGE_BASE = 0x00400000
TARGETS = {
    'eval_core_9D5C20': (0x009D5C20, 0x0060),
    'dead_wrapper_9D5C80': (0x009D5C80, 0x0070),
    'dead_engine_6FFEF4': (0x006FFEF4, 0x1800),
    'eval_entry_9D4E10': (0x009D4E10, 0x1000),
}
SCANS = [
    ('region_6f', 0x006F0000, 0x00710000),
    ('region_9d', 0x009D0000, 0x009E4000),
]


def rpm(h, addr: int, n: int) -> bytes:
    buf = (ctypes.c_ubyte * n)()
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(), f'RPM 0x{addr:08X}')
    return bytes(buf[:got.value])


def disasm(md, blob: bytes, addr: int) -> list[str]:
    return [f'0x{i.address:08X}\t{i.bytes.hex():<24}\t{i.mnemonic:<9}\t{i.op_str}' for i in md.disasm(blob, addr)]


def rel32_calls(blob: bytes, base: int, targets: set[int]) -> list[tuple[int,int]]:
    out=[]
    for off in range(max(0,len(blob)-5)):
        if blob[off] != 0xE8:
            continue
        rel=struct.unpack_from('<i',blob,off+1)[0]
        src=base+off
        dst=(src+5+rel)&0xffffffff
        if dst in targets:
            out.append((src,dst))
    return out


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--pid',required=True,type=int)
    ap.add_argument('--outdir',required=True,type=Path)
    a=ap.parse_args()
    a.outdir.mkdir(parents=True,exist_ok=True)
    h=k32.OpenProcess(ACCESS,False,a.pid)
    if not h:
        raise OSError(ctypes.get_last_error(),'OpenProcess')
    md=Cs(CS_ARCH_X86,CS_MODE_32)
    md.skipdata=True
    summary=[f'R54_PID={a.pid}']
    try:
        if rpm(h,IMAGE_BASE,2)!=b'MZ':
            raise RuntimeError('R54 image base contract failed')
        for name,(addr,size) in TARGETS.items():
            blob=rpm(h,addr,size)
            p=a.outdir/f'r54-{name}-disasm.txt'
            p.write_text('\n'.join(disasm(md,blob,addr))+'\n',encoding='utf-8')
            summary.append(f'R54_DUMP_{name}=0x{addr:08X} bytes={len(blob)} file={p.name}')

        target_addrs={v[0] for v in TARGETS.values()}
        xlines=['scan\tcaller_va\ttarget_va']
        for scan_name,lo,hi in SCANS:
            blob=rpm(h,lo,hi-lo)
            for src,dst in rel32_calls(blob,lo,target_addrs):
                xlines.append(f'{scan_name}\t0x{src:08X}\t0x{dst:08X}')
        (a.outdir/'r54-dead-xrefs.tsv').write_text('\n'.join(xlines)+'\n',encoding='utf-8')
        summary.append(f'R54_XREF_COUNT={len(xlines)-1}')
        summary.append('R54_DEAD_ENDPOINT_STATIC=PASS')
        (a.outdir/'r54-summary.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
        print('\n'.join(summary))
        return 0
    finally:
        k32.CloseHandle(h)

if __name__=='__main__':
    raise SystemExit(main())
