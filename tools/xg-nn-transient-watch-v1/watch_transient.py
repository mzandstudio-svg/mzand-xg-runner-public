import ctypes, ctypes.wintypes as wt, hashlib, json, math, os, struct, sys, time
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
    if not k.ReadProcessMemory(h,ctypes.c_void_p(base),b,size,ctypes.byref(got)) or got.value==0: return b''
    return b.raw[:got.value]
def fbytes(v): return b''.join(struct.pack('<f',float(x)) for x in v)
def half():
    b=[0]*25;b[5]=5;b[7]=3;b[12]=5;b[23]=2;x=[]
    for n in b:x += [float(n==1),float(n>=2),float(n>=3),max(n-3,0)/2.0]
    return x
H=half(); ENG=[0,0,0,1,23/24,23/24,1/6,0,0,0,2/3,14/36,(14/36)**2,14/36,(14/36)**2,0.6205555555555555,0.105,0,11/36,0.52,31/33,0,0.25,0,0.5]
patterns={'half100':fbytes(H),'base200':fbytes(H+H),'eng25':fbytes(ENG),'eng10_17':fbytes(ENG[10:17]),'eng17_25':fbytes(ENG[17:25]),'full250':fbytes(H+H+ENG+ENG)}
weight_prefix=bytes.fromhex('eed753be9a40f83e81c44c3e8dedcabf')
regions=[]; addr=0
while addr<0x80000000:
    m=MBI(); q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q: break
    base=int(m.BaseAddress or 0); size=int(m.RegionSize); prot=int(m.Protect)
    if size<=0: break
    ok=(m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS and 65536<=size<=4*1024*1024)
    if ok:
        d=read(base,size)
        if d and weight_prefix in d: regions.append((base,size))
    nxt=base+size
    if nxt<=addr: break
    addr=nxt
if not regions:
    raise RuntimeError('no NN weight-containing region found')
with open(os.path.join(out,'regions.json'),'w') as f: json.dump([{'base':hex(a),'size':s} for a,s in regions],f,indent=2)
seen_ctx={}; exact_seen=set(); events=[]; start=time.time(); deadline=start+38.0; loops=0
while time.time()<deadline:
    loops+=1
    for base,size in regions:
        d=read(base,size)
        if not d: continue
        for name,pat in patterns.items():
            pos=0
            while True:
                j=d.find(pat,pos)
                if j<0: break
                absolute=base+j; key=(name,absolute)
                if key not in exact_seen:
                    exact_seen.add(key); events.append({'ms':round((time.time()-start)*1000,1),'type':'pattern','name':name,'address':hex(absolute)})
                if name=='half100':
                    lo=max(0,j-1024); hi=min(len(d),j+4096); ctx=d[lo:hi]; sha=hashlib.sha256(ctx).hexdigest(); ck=(absolute,sha)
                    if ck not in seen_ctx:
                        seen_ctx[ck]=1; fn=f"ctx_{len(seen_ctx):04d}_{absolute:08x}_{sha[:12]}.bin"; open(os.path.join(out,fn),'wb').write(ctx)
                        events.append({'ms':round((time.time()-start)*1000,1),'type':'context','address':hex(absolute),'sha256':sha,'file':fn,'context_base':hex(base+lo),'bytes':len(ctx)})
                pos=j+1
    time.sleep(0.015)
with open(os.path.join(out,'events.jsonl'),'w') as f:
    for e in events:f.write(json.dumps(e)+'\n')
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_TRANSIENT_WATCH_V1\n');f.write(f'PID={pid}\nREGIONS={len(regions)}\nLOOPS={loops}\nCONTEXT_VERSIONS={len(seen_ctx)}\n')
    for n in patterns:f.write(f'{n}_HITS={sum(1 for e in events if e.get("type")=="pattern" and e.get("name")==n)}\n')
k.CloseHandle(h)
