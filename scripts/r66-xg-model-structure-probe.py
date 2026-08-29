#!/usr/bin/env python3
from __future__ import annotations

import argparse, math, struct, zlib
from pathlib import Path

W0_BITS=0x3F71970A
W0=struct.unpack('<f',struct.pack('<I',W0_BITS))[0]
W1=-3.5759213
DIMS=set([5,6,7,10,13,14,15,25,32,64,80,100,128,140,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,192,200,224,250,252,254,256,258,300,320,384,385,400,4060,4096])

def streams(data):
    out=[]; pos=0; rest=data
    while rest and len(rest)>=2 and rest[0]==0x78:
        d=zlib.decompressobj(); dec=d.decompress(rest)+d.flush(); used=len(rest)-len(d.unused_data)
        if used<=0: break
        out.append((pos,used,dec)); pos+=used; rest=d.unused_data
    return out

def reasonable(v,limit): return math.isfinite(v) and abs(v)<=limit and (v==0.0 or abs(v)>=1e-30)

def aligned_run(blob, off, limit):
    # off is a 4-byte aligned known float offset.
    lo=off; hi=off
    while lo>=4:
        v=struct.unpack_from('<f',blob,lo-4)[0]
        if not reasonable(v,limit): break
        lo-=4
    while hi+4<=len(blob):
        v=struct.unpack_from('<f',blob,hi)[0]
        if not reasonable(v,limit): break
        hi+=4
    return lo,hi,(hi-lo)//4

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--xg-exe',type=Path,required=True); ap.add_argument('--outdir',type=Path,required=True); a=ap.parse_args(); a.outdir.mkdir(parents=True,exist_ok=True)
    model=next(iter(a.xg_exe.parent.rglob('eXtremeGammon v2.dat')))
    ss=streams(model.read_bytes())
    pat=struct.pack('<I',W0_BITS)
    summary=[]
    for si,(_,_,blob) in enumerate(ss):
        hits=[]; p=0
        while True:
            j=blob.find(pat,p)
            if j<0: break
            if j+8<=len(blob) and abs(struct.unpack_from('<f',blob,j+4)[0]-W1)<=2e-4: hits.append(j)
            p=j+1
        summary.append(f'STREAM_{si}_SIZE={len(blob)} HITS={hits}')
        if not hits: continue
        for hix,off in enumerate(hits):
            lines=[f'stream={si}',f'known_pair_offset={off}',f'alignment={off%4}']
            for lim in (8,16,32,64,100,256,1000,1e6):
                lo,hi,n=aligned_run(blob,off,lim); lines.append(f'float_run_limit_{lim:g}=0x{lo:X}..0x{hi:X} floats={n} bytes={hi-lo}')
            # typed view, 1 KiB before and after
            lo=max(0,off-1024); hi=min(len(blob),off+2048)
            lo-=lo%4
            typed=['offset\thex\ti32\tu32\tf32\tflags']
            for q in range(lo,hi-3,4):
                raw=blob[q:q+4]; u=struct.unpack('<I',raw)[0]; i=struct.unpack('<i',raw)[0]; f=struct.unpack('<f',raw)[0]
                flags=[]
                if i in DIMS or u in DIMS: flags.append('DIM')
                if reasonable(f,100): flags.append('F100')
                if q==off: flags.append('KNOWN_W0')
                if q==off+4: flags.append('KNOWN_W1')
                typed.append(f'0x{q:08X}\t{raw.hex()}\t{i}\t{u}\t{f:.9g}\t{",".join(flags)}')
            (a.outdir/f'r66-stream{si}-hit{hix}-typed.tsv').write_text('\n'.join(typed)+'\n',encoding='utf-8')
            # compact hex around exact boundary
            hs=[]
            hlo=max(0,off-256); hhi=min(len(blob),off+512)
            for q in range(hlo,hhi,16): hs.append(f'{q:08X}: '+blob[q:q+16].hex(' '))
            (a.outdir/f'r66-stream{si}-hit{hix}-hex.txt').write_text('\n'.join(hs)+'\n',encoding='ascii')
            # nearby dimension-like int32 values +/-64 KiB
            dl=max(0,off-65536); dh=min(len(blob),off+65536); dims=['offset\tvalue\tdelta']
            for q in range(dl-(dl%4),dh-3,4):
                v=struct.unpack_from('<I',blob,q)[0]
                if v in DIMS: dims.append(f'0x{q:08X}\t{v}\t{q-off}')
            (a.outdir/f'r66-stream{si}-hit{hix}-near-dims.tsv').write_text('\n'.join(dims)+'\n',encoding='utf-8')
            (a.outdir/f'r66-stream{si}-hit{hix}-summary.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
            print('\n'.join(lines))
            print('\n'.join(dims[:120]))
    (a.outdir/'r66-summary.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8'); print('\n'.join(summary)); return 0
if __name__=='__main__': raise SystemExit(main())
