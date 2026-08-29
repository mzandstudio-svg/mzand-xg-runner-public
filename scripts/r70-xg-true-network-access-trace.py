#!/usr/bin/env python3
from __future__ import annotations

import ctypes, importlib.util, math, struct, sys
from pathlib import Path
if sys.platform!='win32': raise SystemExit('R70 requires Windows')
TARGET=Path(__file__).resolve().with_name('r59-xg-network-access-trace.py')
spec=importlib.util.spec_from_file_location('r70_impl',TARGET)
if spec is None or spec.loader is None: raise SystemExit(f'cannot load {TARGET}')
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
_native=mod.struct.unpack_from
_union=16 if ctypes.sizeof(ctypes.c_void_p)==8 else 12
def abi(fmt,b,off=0):
    if fmt=='<I' and off==12 and len(b)>=_union+4: off=_union
    return _native(fmt,b,off)
mod.struct.unpack_from=abi

# Proven by R68 against official XG2 stream0.
PAIR_BITS=0x3F71970A
PAIR_PAT=struct.pack('<I',PAIR_BITS)
PAIR_NEXT=-3.5759213
PAIR_STREAM_OFF=0x678F4
RECORDS=[
    (0,0x00000000,250,256,5),
    (1,0x0004002C,218,256,3),
    (2,0x00077850,250,256,5),
    (3,0x000B787C,252,256,5),
]

def scan(h,_model):
    chunk=2*1024*1024; found=[]; seen=set()
    for rb,rs,state,protect,mem_type in mod.iter_regions(h):
        if state!=mod.MEM_COMMIT or (protect&mod.PAGE_NOACCESS) or (protect&mod.PAGE_GUARD): continue
        pos=0;carry=b''
        while pos<rs:
            n=min(chunk,rs-pos); data=mod.rpm(h,rb+pos,n)
            if not data: pos+=n;carry=b'';continue
            buf=carry+data;base=rb+pos-len(carry);p=0
            while True:
                j=buf.find(PAIR_PAT,p)
                if j<0:break
                addr=base+j
                if j+8<=len(buf):
                    v1=struct.unpack_from('<f',buf,j+4)[0]
                    stream_base=addr-PAIR_STREAM_OFF
                    if abs(v1-PAIR_NEXT)<=2e-4 and stream_base not in seen and stream_base>=rb:
                        ok=True; local=[]
                        for ni,roff,ic,hc,oc in RECORDS:
                            hdr=mod.rpm(h,stream_base+roff,24)
                            if len(hdr)!=24: ok=False;break
                            got=struct.unpack_from('<iiiIff',hdr,0)
                            if got[0:3]!=(ic,hc,oc): ok=False;break
                            # First true Wih float begins immediately after 24-byte header.
                            waddr=stream_base+roff+24
                            probe=mod.rpm(h,waddr,16)
                            if len(probe)!=16 or not all(math.isfinite(x) for x in struct.unpack('<4f',probe)):
                                ok=False;break
                            local.append(mod.MemMatch(tensor=ni,file_offset=roff+24,address=waddr,region_base=rb,region_size=rs,protect=protect,mem_type=mem_type))
                        if ok:
                            print(f'R70_STREAM_BASE=0x{stream_base:08X} PAIR=0x{addr:08X}',flush=True)
                            found.extend(local);seen.add(stream_base)
                p=j+1
            carry=buf[-16:] if len(buf)>=16 else buf;pos+=n
    return found

mod.scan_signatures=scan
print(f'R70_DEBUG_EVENT_UNION_OFFSET={_union}',flush=True)
print('R70_TRUE_RECORDS='+','.join(f'{n}@0x{o:X}:{i}->{h}->{out}' for n,o,i,h,out in RECORDS),flush=True)
raise SystemExit(mod.main())
