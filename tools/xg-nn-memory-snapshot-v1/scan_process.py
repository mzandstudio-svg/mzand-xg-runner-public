import ctypes, ctypes.wintypes as wt, json, math, os, struct, sys

pid=int(sys.argv[1])
ref_path=sys.argv[2]  # retained for workflow compatibility; not trusted for V4 patterns
out=sys.argv[3]
os.makedirs(out,exist_ok=True)

PROCESS_QUERY_INFORMATION=0x0400
PROCESS_VM_READ=0x0010
MEM_COMMIT=0x1000
PAGE_GUARD=0x100
PAGE_NOACCESS=0x01

class MBI(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wt.DWORD),('PartitionId',wt.WORD),('RegionSize',ctypes.c_size_t),('State',wt.DWORD),('Protect',wt.DWORD),('Type',wt.DWORD)]

k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k.OpenProcess.restype=wt.HANDLE
k.VirtualQueryEx.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]; k.VirtualQueryEx.restype=ctypes.c_size_t
k.ReadProcessMemory.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]; k.ReadProcessMemory.restype=wt.BOOL
k.CloseHandle.argtypes=[wt.HANDLE]

h=k.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')

def fbytes(vals): return b''.join(struct.pack('<f',float(x)) for x in vals)

def start_half(kind):
    b=[0]*25; b[5]=5; b[7]=3; b[12]=5; b[23]=2
    x=[]
    for n in b:
        if kind=='exact2': q=[n==1,n==2,n>=3,max(n-3,0)/2.0]
        elif kind=='ge2': q=[n==1,n>=2,n>=3,max(n-3,0)/2.0]
        elif kind=='tail6': q=[n==1,n==2,n>=3,max(n-3,0)/6.0]
        elif kind=='mx': q=[n==1,n==2,n>=3,0.0 if n<=3 else ((n-3)/8.0 if n<=7 else 0.5+(n-7)/16.0)]
        else: raise ValueError(kind)
        x.extend(float(v) for v in q)
    assert len(x)==100
    return x

# Exact engineered half emitted by Zand V4 FIX1 for the symmetric start board.
eng=[0.0,0.0,0.0,1.0,23.0/24.0,23.0/24.0,1.0/6.0,0.0,0.0,0.0,
     2.0/3.0,14.0/36.0,(14.0/36.0)**2,14.0/36.0,(14.0/36.0)**2,
     0.6205555555555555,0.105,0.0,11.0/36.0,0.52,31.0/33.0,0.0,0.25,0.0,0.5]
assert len(eng)==25
half_ge2=start_half('ge2')
full_v4=half_ge2+half_ge2+eng+eng
assert len(full_v4)==250

patterns={
  'full250_v4_exact':fbytes(full_v4),
  'base200_v4_exact':fbytes(half_ge2+half_ge2),
  'half100_v4_exact':fbytes(half_ge2),
  'engineered25_v4_exact':fbytes(eng),
  'engineered50_v4_exact':fbytes(eng+eng),
  'eng_chunk_3_10':fbytes(eng[3:10]),
  'eng_chunk_10_17':fbytes(eng[10:17]),
  'eng_chunk_17_25':fbytes(eng[17:25]),
}
for kind in ('exact2','ge2','tail6','mx'):
    hh=start_half(kind); patterns['half100_'+kind]=fbytes(hh); patterns['base200_'+kind]=fbytes(hh+hh)

hits=[]; regions=[]; addr=0; MAXADDR=0x80000000; CHUNK=4*1024*1024
OVERLAP=max(len(p) for p in patterns.values())-1

def read_mem(base,size):
    buf=ctypes.create_string_buffer(size); got=ctypes.c_size_t(0)
    ok=k.ReadProcessMemory(h,ctypes.c_void_p(base),buf,size,ctypes.byref(got))
    if not ok or got.value==0: return b''
    return buf.raw[:got.value]

while addr<MAXADDR:
    mbi=MBI(); q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(mbi),ctypes.sizeof(mbi))
    if not q: break
    base=int(mbi.BaseAddress or 0); size=int(mbi.RegionSize)
    if size<=0: break
    readable=(mbi.State==MEM_COMMIT and not(mbi.Protect&PAGE_GUARD) and (mbi.Protect&0xff)!=PAGE_NOACCESS)
    if readable:
        regions.append({'base':hex(base),'size':size,'protect':hex(int(mbi.Protect))})
        off=0; carry=b''
        while off<size:
            n=min(CHUNK,size-off); data=read_mem(base+off,n)
            if not data: break
            blob=carry+data; blob_base=base+off-len(carry)
            for name,pat in patterns.items():
                pos=0
                while True:
                    j=blob.find(pat,pos)
                    if j<0: break
                    hits.append({'pattern':name,'address':hex(blob_base+j),'region_base':hex(base),'region_size':size}); pos=j+1
            carry=blob[-OVERLAP:] if len(blob)>OVERLAP else blob
            off+=len(data)
            if len(data)<n: break
    nxt=base+size
    if nxt<=addr: break
    addr=nxt

uniq=[]; seen=set()
for r in hits:
    key=(r['pattern'],r['address'])
    if key not in seen: seen.add(key); uniq.append(r)
for i,r in enumerate(uniq):
    a=int(r['address'],16); start=max(0,a-1024); data=read_mem(start,8192)
    fn=f"hit_{i:03d}_{r['pattern']}_{a:08x}.bin"; open(os.path.join(out,fn),'wb').write(data)
    r['dump_file']=fn; r['dump_base']=hex(start); r['dump_bytes']=len(data)
    direct=read_mem(a,1000)
    if len(direct)>=1000:
        vals=list(struct.unpack('<250f',direct[:1000])); r['first250_floats']=vals
        r['finite_250']=all(math.isfinite(v) for v in vals); r['zeros_250']=sum(v==0.0 for v in vals); r['ones_250']=sum(v==1.0 for v in vals)

json.dump({'pid':pid,'reference':'internal_exact_v4','region_count':len(regions),'patterns':{name:len(pat) for name,pat in patterns.items()},'hits':uniq},open(os.path.join(out,'scan.json'),'w',encoding='utf-8'),indent=2)
json.dump(regions,open(os.path.join(out,'regions.json'),'w',encoding='utf-8'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w',encoding='utf-8') as f:
    f.write('XG_POST_ANALYSIS_MEMORY_SCAN_V4_EXACT\n'); f.write(f'PID={pid}\nREFERENCE=internal_exact_v4\nREGIONS={len(regions)}\nHITS={len(uniq)}\n')
    for r in uniq: f.write(f"{r['pattern']} {r['address']} zeros={r.get('zeros_250','')} ones={r.get('ones_250','')} {r.get('dump_file','')}\n")
k.CloseHandle(h)
