#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('R55 requires Windows')

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

k32=ctypes.WinDLL('kernel32',use_last_error=True)
PROCESS_VM_READ=0x0010
PROCESS_QUERY_INFORMATION=0x0400
ACCESS=PROCESS_VM_READ|PROCESS_QUERY_INFORMATION
k32.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k32.OpenProcess.restype=wt.HANDLE
k32.ReadProcessMemory.argtypes=[wt.HANDLE,wt.LPCVOID,wt.LPVOID,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]; k32.ReadProcessMemory.restype=wt.BOOL
k32.CloseHandle.argtypes=[wt.HANDLE]

TARGETS={
    'context_builder_6FF704':(0x006FF704,0x068C),
    'endpoint_basis_6FFD90':(0x006FFD90,0x0164),
    'eval_mode_6FFFEC':(0x006FFFEC,0x0238),
}
GLOBALS={
    'dead_basis_A_A0EC48':(0x00A0EC48,5),
    'dead_basis_B_A0EC5C':(0x00A0EC5C,5),
}
SCANS=[('region_6f',0x006F0000,0x00710000),('region_9d',0x009D0000,0x009E4000)]


def rpm(h,addr,n):
    b=(ctypes.c_ubyte*n)(); got=ctypes.c_size_t()
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(addr),b,n,ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(),f'RPM 0x{addr:08X}')
    return bytes(b[:got.value])


def disasm(md,b,addr):
    return [f'0x{i.address:08X}\t{i.bytes.hex():<24}\t{i.mnemonic:<9}\t{i.op_str}' for i in md.disasm(b,addr)]


def calls(blob,base,targets):
    out=[]
    for i in range(max(0,len(blob)-5)):
        if blob[i]!=0xE8: continue
        rel=struct.unpack_from('<i',blob,i+1)[0]
        src=base+i; dst=(src+5+rel)&0xffffffff
        if dst in targets: out.append((src,dst))
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--pid',type=int,required=True); ap.add_argument('--outdir',type=Path,required=True); a=ap.parse_args()
    a.outdir.mkdir(parents=True,exist_ok=True)
    h=k32.OpenProcess(ACCESS,False,a.pid)
    if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')
    md=Cs(CS_ARCH_X86,CS_MODE_32); md.skipdata=True
    summary=[f'R55_PID={a.pid}']
    try:
        if rpm(h,0x400000,2)!=b'MZ': raise RuntimeError('R55 image-base contract failed')
        for name,(addr,size) in TARGETS.items():
            b=rpm(h,addr,size); p=a.outdir/f'r55-{name}-disasm.txt'; p.write_text('\n'.join(disasm(md,b,addr))+'\n',encoding='utf-8')
            summary.append(f'R55_DUMP_{name}=0x{addr:08X} bytes={len(b)} file={p.name}')
        glines=['name\taddress\tf0\tf1\tf2\tf3\tf4\thex']
        for name,(addr,count) in GLOBALS.items():
            b=rpm(h,addr,count*4); fs=struct.unpack('<'+'f'*count,b)
            glines.append(name+'\t'+f'0x{addr:08X}\t'+'\t'.join(f'{x:.9g}' for x in fs)+'\t'+b.hex())
            summary.append(f'R55_GLOBAL_{name}='+','.join(f'{x:.9g}' for x in fs))
        (a.outdir/'r55-dead-basis-globals.tsv').write_text('\n'.join(glines)+'\n',encoding='utf-8')
        target_addrs={v[0] for v in TARGETS.values()}|{0x006FFEF4}
        xs=['scan\tcaller_va\ttarget_va']
        for sn,lo,hi in SCANS:
            b=rpm(h,lo,hi-lo)
            xs += [f'{sn}\t0x{s:08X}\t0x{d:08X}' for s,d in calls(b,lo,target_addrs)]
        (a.outdir/'r55-helper-xrefs.tsv').write_text('\n'.join(xs)+'\n',encoding='utf-8')
        summary.append(f'R55_XREF_COUNT={len(xs)-1}')
        summary.append('R55_DEAD_HELPER_RECOVERY=PASS')
        (a.outdir/'r55-summary.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
        print('\n'.join(summary)); return 0
    finally:
        k32.CloseHandle(h)

if __name__=='__main__': raise SystemExit(main())
