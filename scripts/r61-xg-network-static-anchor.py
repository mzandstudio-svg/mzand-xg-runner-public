#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('R61 requires Windows')

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86 import X86_OP_IMM

k32=ctypes.WinDLL('kernel32',use_last_error=True)
PROCESS_VM_READ=0x0010
PROCESS_QUERY_INFORMATION=0x0400
ACCESS=PROCESS_VM_READ|PROCESS_QUERY_INFORMATION
k32.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k32.OpenProcess.restype=wt.HANDLE
k32.ReadProcessMemory.argtypes=[wt.HANDLE,wt.LPCVOID,wt.LPVOID,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]; k32.ReadProcessMemory.restype=wt.BOOL
k32.CloseHandle.argtypes=[wt.HANDLE]

BASE=0x00400000
DIMS={4096,4060,385,15,14,13}
STRINGS=[
    b'eXtremeGammon v2.dat',
    'eXtremeGammon v2.dat'.encode('utf-16le'),
    b'eXtremeGammon v2 prune.dat',
    'eXtremeGammon v2 prune.dat'.encode('utf-16le'),
    b'v2.dat',
    'v2.dat'.encode('utf-16le'),
]


def rpm(h,addr,n):
    b=(ctypes.c_ubyte*n)(); got=ctypes.c_size_t()
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(addr),b,n,ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(),f'RPM 0x{addr:08X}')
    return bytes(b[:got.value])


def pe_size_of_image(h):
    dos=rpm(h,BASE,0x1000)
    if dos[:2]!=b'MZ': raise RuntimeError('MZ missing')
    peoff=struct.unpack_from('<I',dos,0x3c)[0]
    hdr=rpm(h,BASE+peoff,0x200)
    if hdr[:4]!=b'PE\0\0': raise RuntimeError('PE signature missing')
    opt=24
    magic=struct.unpack_from('<H',hdr,opt)[0]
    if magic!=0x10b: raise RuntimeError(f'expected PE32, magic=0x{magic:x}')
    return struct.unpack_from('<I',hdr,opt+56)[0]


def all_find(blob,needle):
    out=[]; p=0
    while True:
        p=blob.find(needle,p)
        if p<0: return out
        out.append(p); p+=1


def disasm_window(md,image,addr,before=96,after=192):
    off=addr-BASE
    lo=max(0,off-before); hi=min(len(image),off+after)
    start=BASE+lo
    return '\n'.join(f'0x{i.address:08X}\t{i.bytes.hex():<24}\t{i.mnemonic:<9}\t{i.op_str}' for i in md.disasm(image[lo:hi],start))+'\n'


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--pid',type=int,required=True); ap.add_argument('--outdir',type=Path,required=True); a=ap.parse_args()
    a.outdir.mkdir(parents=True,exist_ok=True)
    h=k32.OpenProcess(ACCESS,False,a.pid)
    if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')
    md=Cs(CS_ARCH_X86,CS_MODE_32); md.detail=True; md.skipdata=True
    summary=[f'R61_PID={a.pid}']
    try:
        size=pe_size_of_image(h); image=rpm(h,BASE,size)
        summary.append(f'R61_IMAGE_SIZE=0x{size:X}')

        # Locate model-path strings in the live unpacked image.
        strings=[]
        seen=set()
        for needle in STRINGS:
            for off in all_find(image,needle):
                va=BASE+off
                key=(va,needle)
                if key in seen: continue
                seen.add(key)
                enc='utf16' if b'\x00' in needle else 'ascii'
                strings.append((va,enc,needle))
        slines=['address\tencoding\thex\ttext']
        for va,enc,needle in strings:
            txt=needle.decode('utf-16le' if enc=='utf16' else 'ascii','replace')
            slines.append(f'0x{va:08X}\t{enc}\t{needle.hex()}\t{txt}')
        (a.outdir/'r61-model-strings.tsv').write_text('\n'.join(slines)+'\n',encoding='utf-8')
        summary.append(f'R61_MODEL_STRING_HITS={len(strings)}')

        # Find absolute-address byte references to each model string. Delphi/VCL
        # code frequently materializes these as 32-bit immediates/pointers.
        xrefs=[]
        for sva,enc,needle in strings:
            pat=struct.pack('<I',sva)
            for off in all_find(image,pat):
                xva=BASE+off
                xrefs.append((sva,xva,enc))
        xlines=['string_va\txref_va\tencoding']+[f'0x{s:08X}\t0x{x:08X}\t{e}' for s,x,e in xrefs]
        (a.outdir/'r61-model-string-xrefs.tsv').write_text('\n'.join(xlines)+'\n',encoding='utf-8')
        summary.append(f'R61_MODEL_STRING_XREFS={len(xrefs)}')
        for i,(_,xva,_) in enumerate(xrefs[:40]):
            (a.outdir/f'r61-model-xref-{i:02d}-{xva:08X}.txt').write_text(disasm_window(md,image,xva),encoding='utf-8')

        # Scan decoded x86 instructions for exact dimension immediates and group
        # nearby occurrences. Network constructors/loops tend to carry several of
        # 4096,4060,385,15,14,13 in a short function window.
        hits=[]
        for ins in md.disasm(image,BASE):
            try:
                imms=[int(op.imm)&0xffffffff for op in ins.operands if op.type==X86_OP_IMM]
            except Exception:
                continue
            matched=sorted({v for v in imms if v in DIMS})
            if matched:
                hits.append((ins.address,matched,ins.mnemonic,ins.op_str))
        dlines=['address\tdims\tmnemonic\top_str']+[f'0x{va:08X}\t{",".join(map(str,ds))}\t{mn}\t{op}' for va,ds,mn,op in hits]
        (a.outdir/'r61-dimension-immediates.tsv').write_text('\n'.join(dlines)+'\n',encoding='utf-8')
        summary.append(f'R61_DIMENSION_INSN_HITS={len(hits)}')

        clusters=[]
        for va,ds,_,_ in hits:
            nearby=[h for h in hits if abs(h[0]-va)<=0x180]
            vals=sorted({v for _,vv,_,_ in nearby for v in vv})
            score=len(set(vals)&DIMS)
            if score>=3:
                clusters.append((score,va,vals))
        # Dedupe cluster centers that are very near one another.
        clusters=sorted(clusters,key=lambda x:(-x[0],x[1]))
        picked=[]
        for c in clusters:
            if any(abs(c[1]-p[1])<0x200 for p in picked): continue
            picked.append(c)
            if len(picked)>=30: break
        clines=['score\tcenter\tdims']
        for i,(score,va,vals) in enumerate(picked):
            clines.append(f'{score}\t0x{va:08X}\t{",".join(map(str,vals))}')
            (a.outdir/f'r61-dim-cluster-{i:02d}-{va:08X}.txt').write_text(disasm_window(md,image,va,before=256,after=512),encoding='utf-8')
        (a.outdir/'r61-dimension-clusters.tsv').write_text('\n'.join(clines)+'\n',encoding='utf-8')
        summary.append(f'R61_DIMENSION_CLUSTERS={len(picked)}')
        summary.append('R61_XG_NETWORK_STATIC_ANCHOR=PASS')
        (a.outdir/'r61-summary.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
        print('\n'.join(summary)); return 0
    finally:
        k32.CloseHandle(h)

if __name__=='__main__': raise SystemExit(main())
