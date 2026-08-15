import ctypes, ctypes.wintypes as wt, json, os, sys
import numpy as np

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

target=np.array([0.5261,0.1459,0.0069,0.1228,0.0052],dtype=np.float64)
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
            skip=(-bb)&3;usable=((len(blob)-skip)//4)*4
            if usable>=20:
                a=np.frombuffer(memoryview(blob)[skip:skip+usable],dtype='<f4')
                if a.size>=5:
                    idx=np.flatnonzero(np.isfinite(a[:-4]) & (np.abs(a[:-4]-target[0])<=tol))
                    for ii in idx.tolist():
                        vv=a[ii:ii+5].astype(np.float64)
                        if vv.size==5 and np.all(np.isfinite(vv)) and np.all(np.abs(vv-target)<=tol):
                            absolute=bb+skip+ii*4
                            hits.append({'type':'f32x5','address':hex(absolute),'values':vv.tolist(),'region_base':hex(base),'region_size':size})
            skip=(-bb)&7;usable=((len(blob)-skip)//8)*8
            if usable>=40:
                a=np.frombuffer(memoryview(blob)[skip:skip+usable],dtype='<f8')
                if a.size>=5:
                    idx=np.flatnonzero(np.isfinite(a[:-4]) & (np.abs(a[:-4]-target[0])<=tol))
                    for ii in idx.tolist():
                        vv=a[ii:ii+5]
                        if vv.size==5 and np.all(np.isfinite(vv)) and np.all(np.abs(vv-target)<=tol):
                            absolute=bb+skip+ii*8
                            hits.append({'type':'f64x5','address':hex(absolute),'values':vv.tolist(),'region_base':hex(base),'region_size':size})
            carry=blob[-overlap:] if len(blob)>overlap else blob;off+=len(d)
            if len(d)<n:break
    nxt=base+size
    if nxt<=addr:break
    addr=nxt
uniq=[];seen=set()
for r in hits:
    key=(r['type'],r['address'])
    if key not in seen:seen.add(key);uniq.append(r)
for i,r in enumerate(uniq):
    a=int(r['address'],16);start=max(0,a-65536);d=read(start,131072)
    fn=f"hit_{i:03d}_{r['type']}_{a:08x}.bin";open(os.path.join(out,fn),'wb').write(d)
    r['dump_file']=fn;r['dump_base']=hex(start);r['dump_bytes']=len(d)
json.dump({'pid':pid,'target':target.tolist(),'tolerance':tol,'regions':regions,'hits':uniq},open(os.path.join(out,'output_hits.json'),'w'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_OUTPUT_MEMORY_V1\n');f.write(f'PID={pid}\nREGIONS={regions}\nHITS={len(uniq)}\n')
    for r in uniq:f.write(f"{r['type']} {r['address']} {r['values']} {r['dump_file']}\n")
k.CloseHandle(h)
