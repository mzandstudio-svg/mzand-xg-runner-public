import ctypes, ctypes.wintypes as wt, json, math, os, struct, sys
pid=int(sys.argv[1]); out=sys.argv[2]; os.makedirs(out,exist_ok=True)
PROCESS_QUERY_INFORMATION=0x0400; PROCESS_VM_READ=0x0010; MEM_COMMIT=0x1000; PAGE_GUARD=0x100; PAGE_NOACCESS=0x01
class MBI(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wt.DWORD),('PartitionId',wt.WORD),('RegionSize',ctypes.c_size_t),('State',wt.DWORD),('Protect',wt.DWORD),('Type',wt.DWORD)]
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD];k.OpenProcess.restype=wt.HANDLE
k.VirtualQueryEx.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t];k.VirtualQueryEx.restype=ctypes.c_size_t
k.ReadProcessMemory.argtypes=[wt.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)];k.ReadProcessMemory.restype=wt.BOOL
k.CloseHandle.argtypes=[wt.HANDLE]
h=k.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
if not h:raise OSError(ctypes.get_last_error(),'OpenProcess')
def read(base,size):
    buf=ctypes.create_string_buffer(size);got=ctypes.c_size_t(0)
    if not k.ReadProcessMemory(h,ctypes.c_void_p(base),buf,size,ctypes.byref(got)) or got.value==0:return b''
    return buf.raw[:got.value]
# Rounded public XG direct-1-ply start output.  Search with enough tolerance for the
# two-decimal percentage export while requiring all five outputs consecutively.
target=[0.5261,0.1459,0.0069,0.1228,0.0052]
tol=0.00016
hits=[];regions=0;addr=0;CHUNK=4*1024*1024;overlap=64
while addr<0x80000000:
    m=MBI();q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q:break
    base=int(m.BaseAddress or 0);size=int(m.RegionSize);prot=int(m.Protect)
    if size<=0:break
    ok=(m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS)
    if ok:
        regions+=1;off=0;carry=b''
        while off<size:
            n=min(CHUNK,size-off);d=read(base+off,n)
            if not d:break
            blob=carry+d;bb=base+off-len(carry)
            # float32, every possible 4-byte alignment within process address space
            for align in range(4):
                start=(align-(bb&3))&3
                for j in range(start,max(start,len(blob)-20+1),4):
                    try:v=struct.unpack_from('<5f',blob,j)
                    except:break
                    if all(math.isfinite(v[k]) and abs(v[k]-target[k])<=tol for k in range(5)):
                        a=bb+j;hits.append({'type':'f32x5','address':hex(a),'values':list(v),'region_base':hex(base),'region_size':size})
            # float64 target can appear in UI/export state; use looser absolute tolerance.
            for align in range(8):
                start=(align-(bb&7))&7
                for j in range(start,max(start,len(blob)-40+1),8):
                    try:v=struct.unpack_from('<5d',blob,j)
                    except:break
                    if all(math.isfinite(v[k]) and abs(v[k]-target[k])<=tol for k in range(5)):
                        a=bb+j;hits.append({'type':'f64x5','address':hex(a),'values':list(v),'region_base':hex(base),'region_size':size})
            carry=blob[-overlap:] if len(blob)>overlap else blob;off+=len(d)
            if len(d)<n:break
    nxt=base+size
    if nxt<=addr:break
    addr=nxt
# dedup and dump 128KB around hits
uniq=[];seen=set()
for r in hits:
    key=(r['type'],r['address'])
    if key not in seen:seen.add(key);uniq.append(r)
for i,r in enumerate(uniq):
    a=int(r['address'],16);start=max(0,a-65536);d=read(start,131072)
    fn=f"hit_{i:03d}_{r['type']}_{a:08x}.bin";open(os.path.join(out,fn),'wb').write(d)
    r['dump_file']=fn;r['dump_base']=hex(start);r['dump_bytes']=len(d)
json.dump({'pid':pid,'target':target,'tolerance':tol,'regions':regions,'hits':uniq},open(os.path.join(out,'output_hits.json'),'w'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_OUTPUT_MEMORY_V1\n');f.write(f'PID={pid}\nREGIONS={regions}\nHITS={len(uniq)}\n')
    for r in uniq:f.write(f"{r['type']} {r['address']} {r['values']} {r['dump_file']}\n")
k.CloseHandle(h)
