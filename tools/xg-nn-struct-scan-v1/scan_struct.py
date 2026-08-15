import ctypes, ctypes.wintypes as wt, json, math, os, struct, sys, zlib
pid=int(sys.argv[1]); model_path=sys.argv[2]; out=sys.argv[3]; os.makedirs(out,exist_ok=True)
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
raw=zlib.decompress(open(model_path,'rb').read())
ci,ch,co,raw_field=struct.unpack_from('<IIII',raw,0);bh,bo=struct.unpack_from('<ff',raw,16)
assert (ci,ch,co)==(250,256,5)
raw_wih=raw[24:24+ci*ch*4]
raw_who=raw[24+ci*ch*4:24+ci*ch*4+ch*co*4]
raw_ht=raw[24+ci*ch*4+ch*co*4:24+ci*ch*4+ch*co*4+ch*4]
raw_ot=raw[24+ci*ch*4+ch*co*4+ch*4:24+ci*ch*4+ch*co*4+ch*4+co*4]
needle=struct.pack('<III',250,256,5)
candidates=[];addr=0;regions=0
while addr<0x80000000:
    m=MBI();q=k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m))
    if not q:break
    base=int(m.BaseAddress or 0);size=int(m.RegionSize);prot=int(m.Protect)
    if size<=0:break
    ok=(m.State==MEM_COMMIT and not(prot&PAGE_GUARD) and (prot&0xff)!=PAGE_NOACCESS)
    if ok:
        regions+=1; d=read(base,size)
        if d:
            pos=0
            while True:
                j=d.find(needle,pos)
                if j<0:break
                a=base+j; blob=read(a,40)
                if len(blob)>=40:
                    try:
                        ci0,ch0,co0,ntrained,bh0,bo0,pwih,pwho,pht,pot=struct.unpack('<IIIiffIIII',blob)
                        if abs(bh0-0.1)<1e-4 and abs(bo0-1.0)<1e-4:
                            rec={'address':hex(a),'nTrained':ntrained,'beta_hidden':bh0,'beta_output':bo0,'p_wih':hex(pwih),'p_who':hex(pwho),'p_ht':hex(pht),'p_ot':hex(pot),'region_base':hex(base),'region_size':size}
                            awih=read(pwih,len(raw_wih));awho=read(pwho,len(raw_who));aht=read(pht,len(raw_ht));aot=read(pot,len(raw_ot))
                            rec['read_sizes']=[len(awih),len(awho),len(aht),len(aot)]
                            rec['wih_prefix_match']=len(awih)>=64 and awih[:64]==raw_wih[:64]
                            rec['wih_full_match']=len(awih)==len(raw_wih) and awih==raw_wih
                            rec['who_full_match']=len(awho)==len(raw_who) and awho==raw_who
                            rec['ht_full_match']=len(aht)==len(raw_ht) and aht==raw_ht
                            rec['ot_full_match']=len(aot)==len(raw_ot) and aot==raw_ot
                            if len(awih)>=64:rec['wih_first16']=list(struct.unpack('<16f',awih[:64]))
                            candidates.append(rec)
                    except Exception:pass
                pos=j+1
    nxt=base+size
    if nxt<=addr:break
    addr=nxt
json.dump({'pid':pid,'regions':regions,'raw_field4':raw_field,'raw_beta':[bh,bo],'candidates':candidates},open(os.path.join(out,'nn_structs.json'),'w'),indent=2)
with open(os.path.join(out,'SUMMARY.txt'),'w') as f:
    f.write('XG_NN_STRUCT_SCAN_V1\n');f.write(f'PID={pid}\nREGIONS={regions}\nCANDIDATES={len(candidates)}\n')
    for r in candidates:
        f.write(f"STRUCT {r['address']} nTrained={r['nTrained']} wih={r['p_wih']} full={int(r['wih_full_match'])} who={int(r['who_full_match'])} ht={int(r['ht_full_match'])} ot={int(r['ot_full_match'])}\n")
k.CloseHandle(h)
