import ctypes, ctypes.wintypes as wt, json, os, struct, sys, zlib
pid=int(sys.argv[1]); model=sys.argv[2]; out=sys.argv[3]; os.makedirs(out,exist_ok=True)
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
    if not base or size<=0:return b''
    buf=ctypes.create_string_buffer(size);got=ctypes.c_size_t(0)
    if not k.ReadProcessMemory(h,ctypes.c_void_p(base),buf,size,ctypes.byref(got)) or got.value==0:return b''
    return buf.raw[:got.value]
raw=zlib.decompress(open(model,'rb').read()); prefix=raw[24:24+64]
regions=[];addr=0
while addr<0x80000000:
    m=MBI();q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q:break
    base=int(m.BaseAddress or 0);size=int(m.RegionSize);prot=int(m.Protect)
    if size<=0:break
    if m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS:
        regions.append((base,size,prot))
    nxt=base+size
    if nxt<=addr:break
    addr=nxt
copies=[]
for base,size,prot in regions:
    d=read(base,size)
    if not d:continue
    pos=0
    while True:
        j=d.find(prefix,pos)
        if j<0:break
        a=base+j
        if a<0x100000000:copies.append(a)
        pos=j+1
copies=sorted(set(copies))
refs=[]
for target in copies:
    pat=struct.pack('<I',target)
    for base,size,prot in regions:
        d=read(base,size)
        if not d:continue
        pos=0
        while True:
            j=d.find(pat,pos)
            if j<0:break
            a=base+j
            ctx_base=max(0,a-64);ctx=read(ctx_base,160)
            rec={'target_weight':hex(target),'ref_address':hex(a),'region_base':hex(base),'region_size':size,'context_base':hex(ctx_base)}
            if len(ctx)>=160:
                rec['u32']=list(struct.unpack('<40I',ctx[:160]))
                rec['f32']=list(struct.unpack('<40f',ctx[:160]))
                rel=a-ctx_base
                rec['ref_index_u32']=rel//4
            fn=f"ref_{len(refs):04d}_{target:08x}_{a:08x}.bin";open(os.path.join(out,fn),'wb').write(ctx);rec['file']=fn
            refs.append(rec);pos=j+1
json.dump({'pid':pid,'weight_copies':[hex(x) for x in copies],'reference_count':len(refs),'references':refs},open(os.path.join(out,'pointer_refs.json'),'w'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_POINTER_REFS_V1\n');f.write(f'PID={pid}\nWEIGHT_COPIES={len(copies)}\nPOINTER_REFS={len(refs)}\n')
    for c in copies:f.write(f'WEIGHT_COPY={hex(c)}\n')
    for r in refs:f.write(f"REF target={r['target_weight']} at={r['ref_address']} file={r['file']}\n")
k.CloseHandle(h)
