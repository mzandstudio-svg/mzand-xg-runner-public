#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import math
import struct
import sys
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('R62 requires Windows')

k32=ctypes.WinDLL('kernel32',use_last_error=True)
PROCESS_VM_READ=0x0010
PROCESS_QUERY_INFORMATION=0x0400
ACCESS=PROCESS_VM_READ|PROCESS_QUERY_INFORMATION
MEM_COMMIT=0x1000
PAGE_NOACCESS=0x01
PAGE_GUARD=0x100
MEM_PRIVATE=0x20000
MEM_MAPPED=0x40000
MEM_IMAGE=0x1000000

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_=[
        ('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),
        ('AllocationProtect',wt.DWORD),('PartitionId',wt.WORD),
        ('RegionSize',ctypes.c_size_t),('State',wt.DWORD),('Protect',wt.DWORD),('Type',wt.DWORD),
    ]

k32.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k32.OpenProcess.restype=wt.HANDLE
k32.ReadProcessMemory.argtypes=[wt.HANDLE,wt.LPCVOID,wt.LPVOID,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]; k32.ReadProcessMemory.restype=wt.BOOL
k32.VirtualQueryEx.argtypes=[wt.HANDLE,wt.LPCVOID,ctypes.POINTER(MEMORY_BASIC_INFORMATION),ctypes.c_size_t]; k32.VirtualQueryEx.restype=ctypes.c_size_t
k32.CloseHandle.argtypes=[wt.HANDLE]

KNOWN0=0.943711
KNOWN1=-3.57592


def rpm(h,addr,n):
    b=(ctypes.c_ubyte*n)(); got=ctypes.c_size_t()
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(addr),b,n,ctypes.byref(got)):
        return b''
    return bytes(b[:got.value])


def iter_regions(h):
    addr=0; lim=0x80000000; mbi=MEMORY_BASIC_INFORMATION()
    while addr<lim:
        got=k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(mbi),ctypes.sizeof(mbi))
        if not got:
            addr+=0x1000; continue
        base=int(mbi.BaseAddress or 0); size=int(mbi.RegionSize)
        if size<=0: addr+=0x1000; continue
        yield base,size,int(mbi.State),int(mbi.Protect),int(mbi.Type)
        nxt=base+size; addr=nxt if nxt>addr else addr+0x1000


def ulp_patterns(value:float,radius:int=16):
    bits=struct.unpack('<I',struct.pack('<f',value))[0]
    out=[]
    for d in range(-radius,radius+1):
        b=(bits+d)&0xffffffff
        out.append((b,struct.pack('<I',b),struct.unpack('<f',struct.pack('<I',b))[0]))
    return out


def entropy(data:bytes)->float:
    if not data: return 0.0
    counts=[0]*256
    for b in data: counts[b]+=1
    n=len(data)
    return -sum((c/n)*math.log2(c/n) for c in counts if c)


def find_model(exe:Path)->Path:
    exact=list(exe.parent.rglob('eXtremeGammon v2.dat'))
    if not exact: raise RuntimeError('official v2.dat not found')
    return exact[0]


def container_report(model:Path,out:Path):
    data=model.read_bytes()
    lines=[
        f'path\t{model}',
        f'size\t{len(data)}',
        f'sha256\t{hashlib.sha256(data).hexdigest()}',
        f'head256\t{data[:256].hex()}',
        f'tail256\t{data[-256:].hex()}',
        f'entropy_all\t{entropy(data):.9f}',
    ]
    chunk=65536
    for i in range(0,len(data),chunk):
        part=data[i:i+chunk]
        lines.append(f'entropy_0x{i:08X}\t{len(part)}\t{entropy(part):.9f}')
    magics={
        'gzip':b'\x1f\x8b','zip':b'PK\x03\x04','zlib_78_01':b'\x78\x01','zlib_78_9c':b'\x78\x9c','zlib_78_da':b'\x78\xda',
        '7z':b'7z\xbc\xaf\x27\x1c','bz2':b'BZh','xz':b'\xfd7zXZ\x00',
    }
    for name,magic in magics.items():
        pos=[]; p=0
        while True:
            p=data.find(magic,p)
            if p<0: break
            pos.append(p); p+=1
            if len(pos)>=40: break
        lines.append(f'magic_{name}\t{",".join(hex(x) for x in pos)}')
    # Count finite plausible float32 values at each byte alignment. This is not
    # a decoder, only a fingerprint for whether the container visibly stores raw floats.
    for align in range(4):
        total=finite=moderate=0
        for off in range(align,len(data)-3,4):
            v=struct.unpack_from('<f',data,off)[0]; total+=1
            if math.isfinite(v):
                finite+=1
                if abs(v)<=1000: moderate+=1
        lines.append(f'float_alignment_{align}\ttotal={total}\tfinite={finite}\tmoderate={moderate}')
    out.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return data


def scan_decoded_anchor(h):
    pats=ulp_patterns(KNOWN0,24)
    matches=[]; max_matches=80; chunk_size=2*1024*1024
    for base,size,state,protect,mem_type in iter_regions(h):
        if state!=MEM_COMMIT or (protect&PAGE_NOACCESS) or (protect&PAGE_GUARD): continue
        pos=0; carry=b''
        while pos<size:
            n=min(chunk_size,size-pos); data=rpm(h,base+pos,n)
            if not data:
                carry=b''; pos+=n; continue
            buf=carry+data; buf_base=base+pos-len(carry)
            for bits,pat,v0 in pats:
                p=0
                while True:
                    j=buf.find(pat,p)
                    if j<0: break
                    if j+8<=len(buf):
                        v1=struct.unpack_from('<f',buf,j+4)[0]
                        if math.isfinite(v1) and abs(v1-KNOWN1)<=2e-4:
                            addr=buf_base+j
                            matches.append((addr,base,size,protect,mem_type,v0,v1,bits))
                            if len(matches)>=max_matches: return matches
                    p=j+1
            carry=buf[-16:] if len(buf)>=16 else buf; pos+=n
    return matches


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--pid',type=int,required=True); ap.add_argument('--xg-exe',type=Path,required=True); ap.add_argument('--outdir',type=Path,required=True); a=ap.parse_args()
    a.outdir.mkdir(parents=True,exist_ok=True)
    model=find_model(a.xg_exe)
    data=container_report(model,a.outdir/'r62-container-report.tsv')
    h=k32.OpenProcess(ACCESS,False,a.pid)
    if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')
    try:
        matches=scan_decoded_anchor(h)
        lines=['address\tregion_base\tregion_size\tprotect\ttype\tv0\tv1\tv0_bits']
        for addr,base,size,protect,typ,v0,v1,bits in matches:
            lines.append(f'0x{addr:08X}\t0x{base:08X}\t0x{size:X}\t0x{protect:X}\t0x{typ:X}\t{v0:.9g}\t{v1:.9g}\t0x{bits:08X}')
            blob=rpm(h,max(0,addr-64),512)
            (a.outdir/f'r62-anchor-{addr:08X}.bin.hex.txt').write_text(blob.hex()+'\n',encoding='ascii')
        (a.outdir/'r62-decoded-anchor-matches.tsv').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        summary=[
            f'R62_MODEL_PATH={model}',f'R62_MODEL_SIZE={len(data)}',f'R62_MODEL_SHA256={hashlib.sha256(data).hexdigest()}',
            f'R62_OLD_DECODED_PAIR_MATCHES={len(matches)}',
            'R62_OLD_DECODED_MODEL_PRESENT_IN_RAM='+('YES' if matches else 'NO'),
            'R62_XG_MODEL_CONTAINER_DECODED_ANCHOR=PASS',
        ]
        (a.outdir/'r62-summary.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
        print('\n'.join(summary)); return 0
    finally:
        k32.CloseHandle(h)

if __name__=='__main__': raise SystemExit(main())
