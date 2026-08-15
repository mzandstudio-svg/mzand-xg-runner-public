import ctypes, ctypes.wintypes as wt, hashlib, json, os, struct, sys, time
pid=int(sys.argv[1]); out=sys.argv[2]; os.makedirs(out,exist_ok=True)
PROCESS_QUERY_INFORMATION=0x0400; PROCESS_VM_READ=0x0010; MEM_COMMIT=0x1000; PAGE_GUARD=0x100; PAGE_NOACCESS=0x01
class MBI(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wt.DWORD),('PartitionId',wt.WORD),('RegionSize',ctypes.c_size_t),('State',wt.DWORD),('Protect',wt.DWORD),('Type',wt.DWORD)]
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k.OpenProcess.restype=wt.HANDLE
k.VirtualQueryEx.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]; k.VirtualQueryEx.restype=ctypes.c_size_t
k.ReadProcessMemory.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]; k.ReadProcessMemory.restype=wt.BOOL
k.CloseHandle.argtypes=[wt.HANDLE]
h=k.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')
def read(base,size):
    b=ctypes.create_string_buffer(size); got=ctypes.c_size_t(0)
    if not k.ReadProcessMemory(h,ctypes.c_void_p(base),b,size,ctypes.byref(got)) or got.value==0:return b''
    return b.raw[:got.value]
def fbytes(v):return b''.join(struct.pack('<f',float(x)) for x in v)
def half():
    b=[0]*25;b[5]=5;b[7]=3;b[12]=5;b[23]=2;x=[]
    for n in b:x += [float(n==1),float(n>=2),float(n>=3),max(n-3,0)/2.0]
    return x
H=half(); ENG=[0,0,0,1,23/24,23/24,1/6,0,0,0,2/3,14/36,(14/36)**2,14/36,(14/36)**2,0.6205555555555555,0.105,0,11/36,0.52,31/33,0,0.25,0,0.5]
patterns={'half100':fbytes(H),'base200':fbytes(H+H),'eng25':fbytes(ENG),'eng10_17':fbytes(ENG[10:17]),'eng17_25':fbytes(ENG[17:25]),'full250':fbytes(H+H+ENG+ENG)}
# Locate committed readable regions that already contain the exact imported start-board
# 100-float occupancy half.  This is the region empirically observed in the post-analysis
# scan; it is distinct from the NN-weight regions.
regions=[]; anchors=[]; addr=0
while addr<0x80000000:
    m=MBI();q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q:break
    base=int(m.BaseAddress or 0);size=int(m.RegionSize);prot=int(m.Protect)
    if size<=0:break
    ok=(m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS and 4096<=size<=8*1024*1024)
    if ok:
        d=read(base,size)
        if d:
            pos=0; local=[]
            while True:
                j=d.find(patterns['half100'],pos)
                if j<0:break
                local.append(base+j);pos=j+1
            if local:
                regions.append((base,size));anchors.extend(local)
    nxt=base+size
    if nxt<=addr:break
    addr=nxt
if not regions:raise RuntimeError('no start-feature-containing region found before analysis')
with open(os.path.join(out,'regions.json'),'w') as f:json.dump({'regions':[{'base':hex(a),'size':s} for a,s in regions],'anchors':[hex(a) for a in anchors]},f,indent=2)
# Monitor both exact patterns and changing windows around each pre-analysis occupancy anchor.
# The window is large enough to include nearby engineered/candidate structures without
# dumping the whole process. Save only changed versions and cap artifact growth.
seen_exact=set(); last_hash={}; events=[]; snap_count=0; MAX_SNAPS=160
start=time.time(); deadline=start+38.0; loops=0
while time.time()<deadline:
    loops+=1
    for base,size in regions:
        d=read(base,size)
        if not d:continue
        for name,pat in patterns.items():
            pos=0
            while True:
                j=d.find(pat,pos)
                if j<0:break
                absolute=base+j;key=(name,absolute)
                if key not in seen_exact:
                    seen_exact.add(key);events.append({'ms':round((time.time()-start)*1000,1),'type':'pattern','name':name,'address':hex(absolute)})
                pos=j+1
        for absolute in anchors:
            if not (base<=absolute<base+size):continue
            center=absolute-base;lo=max(0,center-4096);hi=min(len(d),center+12288);ctx=d[lo:hi]
            sha=hashlib.sha256(ctx).hexdigest();prev=last_hash.get(absolute)
            if prev!=sha:
                last_hash[absolute]=sha
                ev={'ms':round((time.time()-start)*1000,1),'type':'context_change','anchor':hex(absolute),'sha256':sha,'context_base':hex(base+lo),'bytes':len(ctx)}
                if snap_count<MAX_SNAPS:
                    snap_count+=1;fn=f"ctx_{snap_count:04d}_{absolute:08x}_{sha[:12]}.bin";open(os.path.join(out,fn),'wb').write(ctx);ev['file']=fn
                events.append(ev)
    time.sleep(0.012)
with open(os.path.join(out,'events.jsonl'),'w') as f:
    for e in events:f.write(json.dumps(e)+'\n')
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_TRANSIENT_WATCH_V2_FEATURE_REGION\n');f.write(f'PID={pid}\nREGIONS={len(regions)}\nANCHORS={len(anchors)}\nLOOPS={loops}\nSNAPSHOTS={snap_count}\nCONTEXT_CHANGES={sum(1 for e in events if e["type"]=="context_change")}\n')
    for n in patterns:f.write(f'{n}_HITS={sum(1 for e in events if e.get("type")=="pattern" and e.get("name")==n)}\n')
k.CloseHandle(h)
