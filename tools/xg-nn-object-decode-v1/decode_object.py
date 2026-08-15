import ctypes, ctypes.wintypes as wt, json, math, os, struct, sys, zlib
pid=int(sys.argv[1]); model=sys.argv[2]; out=sys.argv[3]; os.makedirs(out,exist_ok=True)
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
    if not base or size<=0:return b''
    b=ctypes.create_string_buffer(size); got=ctypes.c_size_t(0)
    if not k.ReadProcessMemory(h,ctypes.c_void_p(base),b,size,ctypes.byref(got)) or got.value==0:return b''
    return b.raw[:got.value]

raw=zlib.decompress(open(model,'rb').read())
ci,ch,co,_=struct.unpack_from('<IIII',raw,0)
raw_wih=raw[24:24+ci*ch*4]
off=24+ci*ch*4
raw_who=raw[off:off+ch*co*4]; off+=ch*co*4
raw_ht=raw[off:off+ch*4]; off+=ch*4
raw_ot=raw[off:off+co*4]
weight_prefix=raw_wih[:64]
outcome=[0.526123046875,0.1458740234375,0.006863594055175781,0.1227569580078125,0.005184173583984375]
outcome_bytes=struct.pack('<5f',*outcome)

# Cache readable regions once.
regions=[];addr=0
while addr<0x80000000:
    m=MBI();q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q:break
    base=int(m.BaseAddress or 0);size=int(m.RegionSize);prot=int(m.Protect)
    if size<=0:break
    if m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS: regions.append((base,size,prot))
    nxt=base+size
    if nxt<=addr:break
    addr=nxt

# Find exact raw slot0 weight copies.
copies=[]
for base,size,_ in regions:
    d=read(base,size)
    if not d:continue
    pos=0
    while True:
        j=d.find(weight_prefix,pos)
        if j<0:break
        copies.append(base+j);pos=j+1
copies=sorted(set(copies))

# Find references where the 36 bytes immediately before the weight pointer begin
# with XG's observed custom NN descriptor signature: 250,256,5,0x91a6ad6e.
objects=[]
for target in copies:
    pat=struct.pack('<I',target)
    for base,size,_ in regions:
        d=read(base,size)
        if not d:continue
        pos=0
        while True:
            j=d.find(pat,pos)
            if j<0:break
            ref=base+j; obj=ref-36
            blob=read(obj,128)
            if len(blob)>=80:
                u=list(struct.unpack('<32I',blob[:128])); f=list(struct.unpack('<32f',blob[:128]))
                if u[:4]==[250,256,5,0x91a6ad6e] and u[9]==target:
                    rec={'object':hex(obj),'weight_ref':hex(ref),'weight_copy':hex(target),'u32':u,'f32':f,'fields':[]}
                    # Pointer-like fields observed in the runtime descriptor. Follow them.
                    for field_off in (16,20,36,40,44,48,52,56,60,64,76,80,84,88,92,96,100,104,108,112,116,120,124):
                        idx=field_off//4; p=u[idx] if idx<len(u) else 0
                        if p<0x10000 or p>=0x80000000:continue
                        dmp=read(p,262144)
                        if not dmp:continue
                        fn=f"obj_{obj:08x}_off{field_off:03d}_{p:08x}.bin";open(os.path.join(out,fn),'wb').write(dmp)
                        fld={'offset':field_off,'address':hex(p),'bytes':len(dmp),'file':fn}
                        fld['matches_raw_wih_full']=len(dmp)>=len(raw_wih) and dmp[:len(raw_wih)]==raw_wih
                        fld['matches_raw_who_full']=len(dmp)>=len(raw_who) and dmp[:len(raw_who)]==raw_who
                        fld['matches_raw_ht_full']=len(dmp)>=len(raw_ht) and dmp[:len(raw_ht)]==raw_ht
                        fld['matches_raw_ot_full']=len(dmp)>=len(raw_ot) and dmp[:len(raw_ot)]==raw_ot
                        fld['outcome_exact_at_start']=len(dmp)>=20 and dmp[:20]==outcome_bytes
                        nf=min(len(dmp)//4,1024)
                        vals=[]
                        if nf:
                            vals=list(struct.unpack('<%df'%nf,dmp[:nf*4]))
                            finite=[x for x in vals if math.isfinite(x)]
                            fld['float_count_inspected']=nf
                            fld['finite']=len(finite)
                            fld['zeros']=sum(x==0.0 for x in finite)
                            fld['ones']=sum(x==1.0 for x in finite)
                            fld['in_0_1']=sum(0.0<=x<=1.0 for x in finite)
                            fld['first16_floats']=vals[:16]
                            if nf>=250:
                                v=vals[:250]
                                fld['first250_binary01']=sum(x in (0.0,1.0) for x in v)
                                fld['first250_in01']=sum(math.isfinite(x) and 0.0<=x<=1.0 for x in v)
                                fld['first250_min']=min(x for x in v if math.isfinite(x)) if any(math.isfinite(x) for x in v) else None
                                fld['first250_max']=max(x for x in v if math.isfinite(x)) if any(math.isfinite(x) for x in v) else None
                        rec['fields'].append(fld)
                    objects.append(rec)
            pos=j+1

json.dump({'pid':pid,'weight_copies':[hex(x) for x in copies],'object_count':len(objects),'objects':objects},open(os.path.join(out,'objects.json'),'w'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_OBJECT_DECODE_V1\n');f.write(f'PID={pid}\nWEIGHT_COPIES={len(copies)}\nOBJECTS={len(objects)}\n')
    for o in objects:
        f.write(f"OBJECT={o['object']} WEIGHT={o['weight_copy']}\n")
        for x in o['fields']:
            flags=[]
            if x['matches_raw_wih_full']:flags.append('RAW_WIH')
            if x['matches_raw_who_full']:flags.append('RAW_WHO')
            if x['matches_raw_ht_full']:flags.append('RAW_HT')
            if x['matches_raw_ot_full']:flags.append('RAW_OT')
            if x['outcome_exact_at_start']:flags.append('XG_OUTCOME5')
            b=x.get('first250_binary01',''); q=x.get('first250_in01','')
            f.write(f"  off={x['offset']} ptr={x['address']} flags={','.join(flags) or '-'} bin250={b} in01_250={q}\n")
k.CloseHandle(h)
