import array, json, os, struct, sys

p=sys.argv[1]
out=sys.argv[2]
b=open(p,'rb').read()
results=[]

# Linear-time exact permutation scan.  A matching window of length n must contain
# every integer in the requested contiguous domain exactly once.  We maintain
# per-value counts and the number of out-of-domain values while sliding.
def scan_sequence(seq, n, width, one_based, byte_offset_scale, alignment_bias=0):
    lo=1 if one_based else 0
    hi=n if one_based else n-1
    counts=[0]*n
    distinct=0
    bad=0

    def add(v):
        nonlocal distinct,bad
        if lo <= v <= hi:
            idx=v-lo
            if counts[idx]==0: distinct += 1
            counts[idx]+=1
        else:
            bad+=1

    def rem(v):
        nonlocal distinct,bad
        if lo <= v <= hi:
            idx=v-lo
            counts[idx]-=1
            if counts[idx]==0: distinct -= 1
        else:
            bad-=1

    if len(seq)<n:
        return
    for v in seq[:n]: add(v)
    if bad==0 and distinct==n:
        vals=list(seq[:n])
        results.append({'n':n,'width':width,'one_based':one_based,'offset':alignment_bias,'offset_hex':hex(alignment_bias),'values':vals})
    for i in range(n,len(seq)):
        rem(seq[i-n]); add(seq[i])
        if bad==0 and distinct==n:
            start=i-n+1
            off=alignment_bias+start*byte_offset_scale
            vals=list(seq[start:start+n])
            results.append({'n':n,'width':width,'one_based':one_based,'offset':off,'offset_hex':hex(off),'values':vals})

# Byte tables can start at any byte offset.
byte_seq=b
for n in (218,250,252,256):
    scan_sequence(byte_seq,n,1,False,1,0)
    if n<256:
        scan_sequence(byte_seq,n,1,True,1,0)

# 16/32-bit tables are scanned at every possible byte alignment, not just native
# alignment. This remains linear and avoids missing packed/unaligned tables.
def words_for_alignment(width,bias):
    usable=((len(b)-bias)//width)*width
    if usable<=0:return []
    mv=memoryview(b)[bias:bias+usable]
    code='H' if width==2 else 'I'
    a=array.array(code)
    a.frombytes(mv.tobytes())
    if sys.byteorder!='little': a.byteswap()
    return a

for width in (2,4):
    for bias in range(width):
        seq=words_for_alignment(width,bias)
        for n in (218,250,252,256):
            scan_sequence(seq,n,width,False,width,bias)
            scan_sequence(seq,n,width,True,width,bias)

# De-duplicate in case a byte sequence is representable through overlapping views.
uniq=[];seen=set()
for r in results:
    key=(r['n'],r['width'],r['one_based'],r['offset'])
    if key not in seen:
        seen.add(key);uniq.append(r)
results=uniq
json.dump({'file':os.path.basename(p),'bytes':len(b),'method':'linear_sliding_exact_set_all_alignments','hits':results},open(out,'w'),indent=2)
print('PERM_SCAN_HITS='+str(len(results)))
for r in results:
    print(r['n'],r['width'],'1based' if r['one_based'] else '0based',r['offset_hex'])
