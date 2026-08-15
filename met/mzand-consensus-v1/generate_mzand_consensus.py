#!/usr/bin/env python3
"""Generate MZand Consensus 25-point MET from redistributable source METs.

Method: per-cell minimax midpoint (midrange), then enforce exact zero-sum
symmetry. eXtreme Gammon is explicitly excluded and must not be present as a
source. This script is intended to make the public artifact reproducible.
"""
from pathlib import Path
import re

EXCLUDE={'extremegammon.met','extreme gammon.met'}

def read_text(p): return p.read_bytes().decode('latin-1')
def parse(p):
    txt=read_text(p); sec=None; meta={}; post=[]; pre=[]; size=0
    for raw in txt.splitlines():
        line=raw.strip()
        if not line or line.startswith(';'): continue
        if line.startswith('[') and line.endswith(']'): sec=line[1:-1]; continue
        if sec=='Current' and '=' in line:
            k,v=line.split('=',1); meta[k.strip()]=v.strip(); continue
        if sec=='PostCrawford' and line.lower().startswith('data='):
            post=[float(x) for x in line.split('=',1)[1].split()]
        if sec=='PreCrawford':
            if line.lower().startswith('size='): size=int(line.split('=',1)[1])
            elif re.match(r'^\d+\s*=',line):
                k,v=line.split('=',1); i=int(k)-1
                while len(pre)<=i: pre.append(None)
                pre[i]=[float(x) for x in v.split()]
    return meta,post,pre,size

here=Path(__file__).resolve().parent
srcdir=here/'tables'
refs=[]
for p in sorted(srcdir.glob('*.met')):
    if p.name=='MZand Consensus 25-point.met' or p.name.lower() in EXCLUDE: continue
    meta,post,pre,size=parse(p)
    if 'extreme gammon' in meta.get('Name','').lower(): continue
    refs.append((p,meta,post,pre,size))
if len(refs)!=6:
    raise SystemExit(f'Expected exactly 6 redistributable source METs; got {len(refs)}')
N=max(r[4] for r in refs)
C=[[0.5]*N for _ in range(N)]
for i in range(N):
    for j in range(i+1,N):
        vals=[]
        for _,_,_,pre,size in refs:
            if i<size and j<size:
                vals.append((pre[i][j] + (1-pre[j][i]))/2)
        C[i][j]=(min(vals)+max(vals))/2
        C[j][i]=1-C[i][j]
post=[]
for k in range(max(len(r[2]) for r in refs)):
    vals=[r[2][k] for r in refs if k<len(r[2])]
    post.append((min(vals)+max(vals))/2)
lines=['[Current]','Name=MZand Consensus 25-point','Version=1.0',
'Description=MZand minimax consensus MET generated from six redistributable reference METs; eXtreme Gammon excluded from generation',
'Copyright=© 2026 MZand Studio (consensus arrangement, generator, and packaging only; source-table rights remain with their respective owners)',
'; MatchPoint=25','; eXtremeGammonUsedForGeneration=NO','',
'[Version]','Current=1.0','', '[PostCrawford]','Size=25','Data='+' '.join(f'{v:.8f}' for v in post),'', '[PreCrawford]','Size=25']
for i,row in enumerate(C,1): lines.append(f'{i:2d}='+' '.join(f'{v:.8f}' for v in row)+' ')
out=srcdir/'MZand Consensus 25-point.met'
out.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(out)
