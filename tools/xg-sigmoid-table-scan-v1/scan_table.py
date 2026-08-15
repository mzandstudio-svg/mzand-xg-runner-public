import ctypes, ctypes.wintypes as wt, json, math, os, struct, sys, zlib
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
    b=ctypes.create_string_buffer(size);g=ctypes.c_size_t(0)
    if not k.ReadProcessMemory(h,ctypes.c_void_p(base),b,size,ctypes.byref(g)) or g.value==0:return b''
    return b.raw[:g.value]
raw=zlib.decompress(open(model,'rb').read());prefix=raw[24:88]
regions=[];addr=0
while addr<0x80000000:
    m=MBI();q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q:break
    base=int(m.BaseAddress or 0);size=int(m.RegionSize);prot=int(m.Protect)
    if size<=0:break
    if m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS:regions.append((base,size,prot))
    nxt=base+size
    if nxt<=addr:break
    addr=nxt
# Locate active A descriptor using full official arrays and nonzero output.
ci,ch,co=250,256,5;who_off=24+ci*ch*4;ht_off=who_off+ch*co*4;ot_off=ht_off+ch*4
raw_wih=raw[24:who_off];raw_who=raw[who_off:ht_off];raw_ht=raw[ht_off:ot_off];raw_ot=raw[ot_off:ot_off+co*4]
active=None
needle=struct.pack('<III',250,256,5)
for base,size,_ in regions:
    d=read(base,size)
    if not d:continue
    pos=0
    while True:
        j=d.find(needle,pos)
        if j<0:break
        obj=base+j;b=read(obj,60)
        if len(b)>=60:
            u=struct.unpack('<15I',b)
            if u[3]==0x91a6ad6e:
                pwih,pwho,pht,pot,pout,phid=u[9],u[10],u[11],u[12],u[13],u[14]
                valid=(read(pwih,len(raw_wih))==raw_wih and read(pwho,len(raw_who))==raw_who and read(pht,len(raw_ht))==raw_ht and read(pot,len(raw_ot))==raw_ot)
                ob=read(pout,20)
                if valid and len(ob)==20:
                    ov=struct.unpack('<5f',ob)
                    if any(abs(x)>1e-12 for x in ov):
                        active={'object':obj,'hidden_ptr':phid,'output_ptr':pout,'outputs':list(ov)}
                        break
        pos=j+1
    if active:break
if not active:raise RuntimeError('active A descriptor not found')
hb=read(active['hidden_ptr'],256*4)
if len(hb)!=1024:raise RuntimeError('hidden activation read failed')
hvals=struct.unpack('<256f',hb); hbits=set(struct.unpack('<256I',hb))
# Ignore common trivial values; exact nontrivial activation table entries are distinctive.
hbits={x for x,v in zip(struct.unpack('<256I',hb),hvals) if 0.0<v<1.0 and v not in (0.5,)}
reports=[]
for base,size,prot in regions:
    d=read(base,size)
    if not d or size<1024:continue
    n=(len(d)//4)
    if n<16:continue
    vals=struct.unpack('<%dI'%n,d[:n*4])
    hit_idx=[i for i,u in enumerate(vals) if u in hbits]
    if len(hit_idx)<8:continue
    unique=len(set(vals[i] for i in hit_idx))
    if unique<8:continue
    # Look for long monotone [0,1] float runs that could be a LUT.
    f=struct.unpack('<%df'%n,d[:n*4])
    longest=0;best=(0,0);cur=0;start=0;direction=0
    for i,v in enumerate(f):
        good=math.isfinite(v) and 0.0<=v<=1.0
        if not good:
            cur=0;direction=0;continue
        if cur==0:
            cur=1;start=i;direction=0
        else:
            prev=f[i-1]
            nd=1 if v>=prev else -1
            if direction==0 or nd==direction:
                cur+=1;direction=nd if v!=prev else direction
            else:
                cur=2;start=i-1;direction=nd
        if cur>longest:longest=cur;best=(start,i+1)
    rec={'base':hex(base),'size':size,'protect':hex(prot),'activation_hits':len(hit_idx),'unique_activation_hits':unique,'first_hit_offsets':[i*4 for i in hit_idx[:40]],'longest_monotone_01_floats':longest,'best_run_float_index':list(best)}
    # Dump candidate region if it has strong evidence; cap at 4MB.
    if unique>=16 or longest>=512:
        fn=f"region_{base:08x}_{size}.bin";open(os.path.join(out,fn),'wb').write(d[:min(len(d),4*1024*1024)]);rec['dump_file']=fn
    reports.append(rec)
reports.sort(key=lambda r:(r['unique_activation_hits'],r['longest_monotone_01_floats']),reverse=True)
json.dump({'pid':pid,'active':{'object':hex(active['object']),'hidden_ptr':hex(active['hidden_ptr']),'output_ptr':hex(active['output_ptr']),'outputs':active['outputs']},'hidden_unique_bits':len(hbits),'candidates':reports},open(os.path.join(out,'sigmoid_candidates.json'),'w'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_SIGMOID_TABLE_SCAN_V1\n');f.write(f"ACTIVE_OBJECT={hex(active['object'])}\nHIDDEN_PTR={hex(active['hidden_ptr'])}\nCANDIDATES={len(reports)}\n")
    for r in reports[:20]:f.write(f"REGION {r['base']} size={r['size']} hits={r['activation_hits']} unique={r['unique_activation_hits']} monotone01={r['longest_monotone_01_floats']} file={r.get('dump_file','')}\n")
k.CloseHandle(h)
