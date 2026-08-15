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

def parse_raw_network(raw,off,label):
    ci,ch,co,field4=struct.unpack_from('<IIII',raw,off); bh,bo=struct.unpack_from('<ff',raw,off+16)
    p=off+24
    sizes=[ci*ch*4,ch*co*4,ch*4,co*4]
    arr=[]
    for n in sizes:
        arr.append(raw[p:p+n]);p+=n
    return {'label':label,'offset':off,'dims':[ci,ch,co],'field4':field4,'betas':[bh,bo],'wih':arr[0],'who':arr[1],'ht':arr[2],'ot':arr[3],'next':p}

raw=zlib.decompress(open(model,'rb').read())
# File offsets are independently discoverable from the dimension headers and are
# fixed in the official 2.10 DAT currently installed by the workflow.
rawnets=[]
for label,dims,start in [('A',(250,256,5),0),('B',(218,256,3),262188),('C',(250,256,5),489552),('D',(252,256,5),751740)]:
    n=parse_raw_network(raw,start,label)
    if tuple(n['dims'])!=dims: raise RuntimeError(f'{label} raw dimensions mismatch: {n["dims"]}')
    rawnets.append(n)

regions=[];addr=0
while addr<0x80000000:
    m=MBI();q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q:break
    base=int(m.BaseAddress or 0); size=int(m.RegionSize); prot=int(m.Protect)
    if size<=0:break
    if m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS:regions.append((base,size,prot))
    nxt=base+size
    if nxt<=addr:break
    addr=nxt

# Find custom XG descriptors by dimension header and validate live model pointers.
records=[]
for net in rawnets:
    ci,ch,co=net['dims']; needle=struct.pack('<III',ci,ch,co)
    for base,size,_ in regions:
        d=read(base,size)
        if not d:continue
        pos=0
        while True:
            j=d.find(needle,pos)
            if j<0:break
            obj=base+j; blob=read(obj,84)
            if len(blob)>=60:
                u=struct.unpack('<21I',blob[:84]); f=struct.unpack('<21f',blob[:84])
                field4=u[3]
                p_input=u[4]; p_hidden_pre=u[5]; p_wih=u[9]; p_who=u[10]; p_ht=u[11]; p_ot=u[12]; p_out=u[13]; p_hidden_act=u[14]
                # Full-array equality validates that this is the correct live descriptor,
                # not an incidental 250/256/5 integer sequence.
                awih=read(p_wih,len(net['wih'])); awho=read(p_who,len(net['who'])); aht=read(p_ht,len(net['ht'])); aot=read(p_ot,len(net['ot']))
                valid=(awih==net['wih'] and awho==net['who'] and aht==net['ht'] and aot==net['ot'])
                if valid:
                    inp=read(p_input,ci*4)
                    vals=list(struct.unpack('<%df'%ci,inp)) if len(inp)==ci*4 else []
                    outvals=[]
                    ob=read(p_out,co*4)
                    if len(ob)==co*4: outvals=list(struct.unpack('<%df'%co,ob))
                    fn=f"{net['label']}_{obj:08x}_input{ci}.txt"
                    with open(os.path.join(out,fn),'w') as z:
                        z.write('# XG live NN input; runtime interoperability evidence; TRAINING_ELIGIBLE=False\n')
                        for ii,v in enumerate(vals):z.write(f'{ii} {v:.17g}\n')
                    rec={'network':net['label'],'object':hex(obj),'dims':net['dims'],'field4':hex(field4),'input_ptr':hex(p_input),'hidden_pre_ptr':hex(p_hidden_pre),'wih_ptr':hex(p_wih),'who_ptr':hex(p_who),'ht_ptr':hex(p_ht),'ot_ptr':hex(p_ot),'output_ptr':hex(p_out),'hidden_act_ptr':hex(p_hidden_act),'input_file':fn,'input_values':vals,'output_values':outvals,'input_finite':all(math.isfinite(x) for x in vals),'input_zero_count':sum(x==0.0 for x in vals),'input_binary01_count':sum(x in (0.0,1.0) for x in vals),'input_in01_count':sum(math.isfinite(x) and 0.0<=x<=1.0 for x in vals),'descriptor_float_28':f[7],'descriptor_float_32':f[8]}
                    records.append(rec)
            pos=j+1

# Deduplicate identical descriptor addresses caused by repeated scans of same header.
uniq=[];seen=set()
for r in records:
    key=(r['network'],r['object'])
    if key not in seen:seen.add(key);uniq.append(r)
records=uniq
json.dump({'pid':pid,'region_count':len(regions),'records':records},open(os.path.join(out,'allnet.json'),'w'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_ALLNET_INPUT_V1\n');f.write(f'PID={pid}\nREGIONS={len(regions)}\nRECORDS={len(records)}\n')
    for label in 'ABCD':
        rr=[r for r in records if r['network']==label]
        f.write(f'NETWORK_{label}_DESCRIPTORS={len(rr)}\n')
        for r in rr:
            f.write(f"  {label} object={r['object']} input={r['input_ptr']} zeros={r['input_zero_count']} binary01={r['input_binary01_count']} in01={r['input_in01_count']} out={r['output_values']} file={r['input_file']}\n")
k.CloseHandle(h)
