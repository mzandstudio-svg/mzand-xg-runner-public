#!/usr/bin/env python3
import argparse, ctypes, ctypes.wintypes as wt, os, struct, re, hashlib
from pathlib import Path

PROCESS_QUERY_INFORMATION=0x0400
PROCESS_VM_READ=0x0010
LIST_MODULES_ALL=0x03
k32=ctypes.WinDLL('kernel32',use_last_error=True)
psapi=ctypes.WinDLL('psapi',use_last_error=True)

k32.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]
k32.OpenProcess.restype=wt.HANDLE
k32.ReadProcessMemory.argtypes=[wt.HANDLE,wt.LPCVOID,wt.LPVOID,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype=wt.BOOL
k32.CloseHandle.argtypes=[wt.HANDLE]

psapi.EnumProcessModulesEx.argtypes=[wt.HANDLE,ctypes.POINTER(wt.HMODULE),wt.DWORD,ctypes.POINTER(wt.DWORD),wt.DWORD]
psapi.GetModuleInformation.argtypes=[wt.HANDLE,wt.HMODULE,wt.LPVOID,wt.DWORD]

class MODULEINFO(ctypes.Structure):
    _fields_=[('lpBaseOfDll',wt.LPVOID),('SizeOfImage',wt.DWORD),('EntryPoint',wt.LPVOID)]

def read_mem(h,addr,size):
    buf=(ctypes.c_ubyte*size)(); got=ctypes.c_size_t()
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(addr),buf,size,ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(),f'ReadProcessMemory 0x{addr:x} size=0x{size:x}')
    return bytes(buf[:got.value])

def pe_sections(d):
    if d[:2]!=b'MZ': raise RuntimeError('not MZ')
    peoff=struct.unpack_from('<I',d,0x3c)[0]
    if d[peoff:peoff+4]!=b'PE\0\0': raise RuntimeError('not PE')
    machine,nsec,_,_,_,optsz,_=struct.unpack_from('<HHIIIHH',d,peoff+4)
    opt=peoff+24
    magic=struct.unpack_from('<H',d,opt)[0]
    if magic!=0x10b: raise RuntimeError(f'expected PE32, magic={magic:x}')
    imagebase=struct.unpack_from('<I',d,opt+28)[0]
    section_align=struct.unpack_from('<I',d,opt+32)[0]
    file_align=struct.unpack_from('<I',d,opt+36)[0]
    size_image=struct.unpack_from('<I',d,opt+56)[0]
    size_headers=struct.unpack_from('<I',d,opt+60)[0]
    ep=struct.unpack_from('<I',d,opt+16)[0]
    secs=[]; so=opt+optsz
    for i in range(nsec):
        p=so+i*40
        name=d[p:p+8].rstrip(b'\0').decode('latin1','replace')
        vs,va,rs,rp=struct.unpack_from('<IIII',d,p+8)
        secs.append((name,vs,va,rs,rp,p))
    return imagebase,size_image,size_headers,ep,file_align,secs

def ascii_hits(blob, needles):
    out=[]
    low=blob.lower()
    for n in needles:
        nb=n.lower().encode('ascii')
        pos=0
        while True:
            i=low.find(nb,pos)
            if i<0: break
            out.append((i,n,'ascii'))
            pos=i+1
        wb=n.lower().encode('utf-16le')
        pos=0
        while True:
            i=low.find(wb,pos)
            if i<0: break
            out.append((i,n,'utf16'))
            pos=i+2
    return sorted(out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pid',type=int,required=True)
    ap.add_argument('--exe',type=Path,required=True)
    ap.add_argument('--outdir',type=Path,required=True)
    a=ap.parse_args(); a.outdir.mkdir(parents=True,exist_ok=True)
    disk=a.exe.read_bytes()
    diskbase,disksz,hdrsz,ep,filealign,secs=pe_sections(disk)
    h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,a.pid)
    if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')
    try:
        mods=(wt.HMODULE*1024)(); needed=wt.DWORD()
        if not psapi.EnumProcessModulesEx(h,mods,ctypes.sizeof(mods),ctypes.byref(needed),LIST_MODULES_ALL):
            raise OSError(ctypes.get_last_error(),'EnumProcessModulesEx')
        mi=MODULEINFO()
        if not psapi.GetModuleInformation(h,mods[0],ctypes.byref(mi),ctypes.sizeof(mi)):
            raise OSError(ctypes.get_last_error(),'GetModuleInformation')
        base=ctypes.cast(mi.lpBaseOfDll,ctypes.c_void_p).value
        size=int(mi.SizeOfImage)
        mem=read_mem(h,base,size)
    finally:
        k32.CloseHandle(h)

    (a.outdir/'xg2-unpacked-memory.bin').write_bytes(mem)

    # Rebuild a file-layout PE using in-memory headers and section contents.
    mhdr=mem[:max(hdrsz,0x1000)]
    _,_,mhdrsz,mep,mfilealign,msecs=pe_sections(mhdr+disk[len(mhdr):max(len(disk),len(mhdr))])
    maxend=max([mhdrsz]+[rp+max(rs,0) for _,vs,va,rs,rp,_ in msecs])
    rebuilt=bytearray(max(maxend,len(disk)))
    rebuilt[:min(hdrsz,len(mem))]=mem[:min(hdrsz,len(mem))]
    for name,vs,va,rs,rp,_ in msecs:
        if rs and va < len(mem):
            take=min(rs,len(mem)-va)
            rebuilt[rp:rp+take]=mem[va:va+take]
    (a.outdir/'eXtremeGammon2-unpacked-rebuilt.exe').write_bytes(rebuilt)

    needles=['CubeVitality1Click','CubeEval','Cube Vitality','Cubefull Equities','Dead Cube','Live Cube','Take Point','Cash Point','XGRPlusCube']
    hits=ascii_hits(mem,needles)
    with (a.outdir/'r36-string-addresses.tsv').open('w',encoding='utf-8') as f:
        f.write('offset\tva\tkind\tneedle\n')
        for off,n,k in hits:
            f.write(f'0x{off:08x}\t0x{base+off:08x}\t{k}\t{n}\n')

    # Delphi published-method names are often short-string encoded. Scan for
    # byte-length + name and dump nearby dwords that look like image pointers.
    target=b'CubeVitality1Click'
    forensic=[]
    for i in range(len(mem)-len(target)-1):
        if mem[i]==len(target) and mem[i+1:i+1+len(target)]==target:
            lo=max(0,i-96); hi=min(len(mem),i+len(target)+1+96)
            win=mem[lo:hi]
            ptrs=[]
            for j in range(0,len(win)-4):
                v=struct.unpack_from('<I',win,j)[0]
                if base <= v < base+len(mem): ptrs.append((lo+j,v,v-base))
            forensic.append((i,ptrs,win))
    with (a.outdir/'r36-delphi-method-rtti.txt').open('w',encoding='utf-8') as f:
        f.write(f'PID={a.pid}\nBASE=0x{base:08x}\nSIZE=0x{len(mem):x}\nDISK_IMAGEBASE=0x{diskbase:08x}\nENTRY_RVA_DISK=0x{ep:x}\nENTRY_RVA_MEM=0x{mep:x}\n')
        f.write(f'MEM_SHA256={hashlib.sha256(mem).hexdigest()}\nREBUILT_SHA256={hashlib.sha256(rebuilt).hexdigest()}\n')
        for idx,(off,ptrs,win) in enumerate(forensic):
            f.write(f'\nMETHOD_NAME_HIT[{idx}] RVA=0x{off:x} VA=0x{base+off:x}\n')
            for po,pv,pr in ptrs[:80]: f.write(f'  PTR_AT_RVA=0x{po:x} -> VA=0x{pv:x} RVA=0x{pr:x}\n')
            f.write('  WINDOW_HEX='+win.hex()+'\n')
    print(f'R36_DUMP=PASS PID={a.pid} BASE=0x{base:x} SIZE=0x{len(mem):x} HITS={len(hits)} RTTI_HITS={len(forensic)}')

if __name__=='__main__': main()
