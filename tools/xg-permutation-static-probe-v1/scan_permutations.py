import os,sys,struct,json,collections
root,out=sys.argv[1],sys.argv[2]
os.makedirs(out,exist_ok=True)
sizes=[218,250,252,256]
results=[]

def scan_u32(data,path,n):
    lim=len(data)-4*n
    if lim<0:return
    for off in range(0,lim+1,4):
        # cheap gate
        a=struct.unpack_from('<I',data,off)[0]
        b=struct.unpack_from('<I',data,off+4)[0]
        c=struct.unpack_from('<I',data,off+8)[0]
        if a>=n or b>=n or c>=n: continue
        vals=struct.unpack_from('<%dI'%n,data,off)
        if max(vals)<n and len(set(vals))==n:
            results.append(dict(file=path,encoding='u32le',n=n,offset=off,values=list(vals)))

def scan_u16(data,path,n):
    lim=len(data)-2*n
    if lim<0:return
    for off in range(0,lim+1,2):
        a,b,c=struct.unpack_from('<3H',data,off)
        if a>=n or b>=n or c>=n: continue
        vals=struct.unpack_from('<%dH'%n,data,off)
        if max(vals)<n and len(set(vals))==n:
            results.append(dict(file=path,encoding='u16le',n=n,offset=off,values=list(vals)))

def scan_u8(data,path,n):
    if n>256 or len(data)<n:return
    cnt=[0]*256; dup=0; bad=0
    for v in data[:n]:
        if v>=n: bad+=1
        if cnt[v]: dup+=1
        cnt[v]+=1
    if bad==0 and dup==0: results.append(dict(file=path,encoding='u8',n=n,offset=0,values=list(data[:n])))
    for off in range(1,len(data)-n+1):
        old=data[off-1]; new=data[off+n-1]
        cnt[old]-=1
        if cnt[old]>=1: dup-=1
        if old>=n: bad-=1
        if cnt[new]>=1: dup+=1
        cnt[new]+=1
        if new>=n: bad+=1
        if bad==0 and dup==0:
            results.append(dict(file=path,encoding='u8',n=n,offset=off,values=list(data[off:off+n])))
            if len(results)>2000:return

files=[]
for dp,ds,fs in os.walk(root):
    for f in fs:
        p=os.path.join(dp,f)
        try:
            if os.path.getsize(p)<=80*1024*1024: files.append(p)
        except: pass
for p in files:
    try:data=open(p,'rb').read()
    except:continue
    rel=os.path.relpath(p,root)
    for n in sizes:
        scan_u32(data,rel,n)
        scan_u16(data,rel,n)
        if n in (250,256):scan_u8(data,rel,n)
    if len(results)>5000:break
json.dump(results,open(os.path.join(out,'permutation-candidates.json'),'w'),indent=2)
with open(os.path.join(out,'summary.txt'),'w') as f:
    f.write('files_scanned=%d\n'%len(files)); f.write('candidates=%d\n'%len(results))
    for r in results[:200]:f.write('%s n=%d enc=%s off=0x%x first=%s\n'%(r['file'],r['n'],r['encoding'],r['offset'],r['values'][:12]))
print(open(os.path.join(out,'summary.txt')).read())
