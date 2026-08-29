#!/usr/bin/env python3
from __future__ import annotations
import argparse,math,struct,zlib
from pathlib import Path

def streams(data):
 out=[];rest=data;pos=0
 while rest and len(rest)>=2 and rest[0]==0x78:
  d=zlib.decompressobj(); dec=d.decompress(rest)+d.flush(); used=len(rest)-len(d.unused_data)
  if used<=0: break
  out.append((pos,used,dec)); pos+=used; rest=d.unused_data
 return out

def valid_float(v): return math.isfinite(v) and abs(v)<1e7 and (v==0.0 or abs(v)>=1e-35)

def score_span(blob,start,n):
 if start<0 or start+4*n>len(blob): return None
 good=0; mn=float('inf');mx=float('-inf'); sm=0.0; bad=[]
 for i in range(n):
  v=struct.unpack_from('<f',blob,start+4*i)[0]
  if valid_float(v): good+=1; mn=min(mn,v);mx=max(mx,v);sm+=v
  elif len(bad)<8: bad.append((i,v,blob[start+4*i:start+4*i+4].hex()))
 return good/n,mn,mx,(sm/good if good else float('nan')),bad

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--xg-exe',type=Path,required=True);ap.add_argument('--outdir',type=Path,required=True);a=ap.parse_args();a.outdir.mkdir(parents=True,exist_ok=True)
 model=next(iter(a.xg_exe.parent.rglob('eXtremeGammon v2.dat'))); ss=streams(model.read_bytes()); rows=['stream\theader_off\tin\thidden\tout\tcount_bias_both\tend_bias_both\tvalid_ratio\tmin\tmax\tmean\tbad_preview']
 for si,(_,_,blob) in enumerate(ss):
  for off in range(0,len(blob)-12,4):
   ni,nh,no=struct.unpack_from('<III',blob,off)
   if not (64<=ni<=1024 and 8<=nh<=8192 and 1<=no<=32): continue
   # strongest known XG family signals; keep scan broad but reject absurd products
   n=(ni+1)*nh+(nh+1)*no
   if n>500000: continue
   sc=score_span(blob,off+12,n)
   if sc is None: continue
   ratio,mn,mx,mean,bad=sc
   if ratio<0.995: continue
   rows.append(f'{si}\t0x{off:08X}\t{ni}\t{nh}\t{no}\t{n}\t0x{off+12+4*n:08X}\t{ratio:.9f}\t{mn:.9g}\t{mx:.9g}\t{mean:.9g}\t{bad}')
   print(rows[-1])
   # boundary context and layout probes for high-value 5-output records
   if no==5:
    wstart=off+12; wend=wstart+4*n
    ctx=[]
    for q in range(max(0,off-64),min(len(blob),off+76),4):
     raw=blob[q:q+4];ctx.append(f'0x{q:08X}\t{raw.hex()}\ti={struct.unpack("<i",raw)[0]}\tf={struct.unpack("<f",raw)[0]:.9g}')
    ctx.append('---END---')
    for q in range(max(0,wend-32),min(len(blob),wend+64),4):
     raw=blob[q:q+4];ctx.append(f'0x{q:08X}\t{raw.hex()}\ti={struct.unpack("<i",raw)[0]}\tf={struct.unpack("<f",raw)[0]:.9g}')
    (a.outdir/f'r68-stream{si}-{off:08X}-context.tsv').write_text('\n'.join(ctx)+'\n',encoding='utf-8')
 (a.outdir/'r68-network-records.tsv').write_text('\n'.join(rows)+'\n',encoding='utf-8')
 print(f'R68_CANDIDATES={len(rows)-1}')
 return 0
if __name__=='__main__':raise SystemExit(main())
