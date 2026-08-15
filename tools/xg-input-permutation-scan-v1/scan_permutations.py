import json, os, struct, sys
p=sys.argv[1]; out=sys.argv[2]
b=open(p,'rb').read()
results=[]

def scan(n,width,one_based=False):
    target=set(range(1,n+1)) if one_based else set(range(n))
    step=width
    fmt={1:'B',2:'<H',4:'<I'}[width]
    maxoff=len(b)-n*width
    # Restrict candidates cheaply by first value being in domain; exact-set verification is decisive.
    for off in range(0,maxoff+1):
        if width==1:
            first=b[off]
            if first not in target: continue
            vals=b[off:off+n]
            if len(set(vals))==n and set(vals)==target:
                results.append({'n':n,'width':width,'one_based':one_based,'offset':off,'offset_hex':hex(off),'values':list(vals)})
        else:
            try:first=struct.unpack_from(fmt,b,off)[0]
            except:continue
            if first not in target:continue
            vals=[struct.unpack_from(fmt,b,off+i*width)[0] for i in range(n)]
            if len(set(vals))==n and set(vals)==target:
                results.append({'n':n,'width':width,'one_based':one_based,'offset':off,'offset_hex':hex(off),'values':vals})

# Byte tables are cheap and the most likely compact representation.
for n in (218,250,252,256):
    scan(n,1,False)
    if n<256: scan(n,1,True)
# Wider exact tables: align to 2/4 bytes by scanning offsets with native alignment.
def scan_aligned(n,width,one_based=False):
    target=set(range(1,n+1)) if one_based else set(range(n)); fmt={2:'<H',4:'<I'}[width]
    for off in range(0,len(b)-n*width+1,width):
        vals=struct.unpack_from('<'+('H' if width==2 else 'I')*n,b,off)
        if len(set(vals))==n and set(vals)==target:
            results.append({'n':n,'width':width,'one_based':one_based,'offset':off,'offset_hex':hex(off),'values':list(vals)})
for n in (218,250,252,256):
    for w in (2,4):
        scan_aligned(n,w,False)
        scan_aligned(n,w,True)
json.dump({'file':os.path.basename(p),'bytes':len(b),'hits':results},open(out,'w'),indent=2)
print('PERM_SCAN_HITS='+str(len(results)))
for r in results:print(r['n'],r['width'],'1based' if r['one_based'] else '0based',r['offset_hex'])
