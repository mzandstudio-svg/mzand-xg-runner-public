import sys,time,json,os,zlib
import frida
pid=int(sys.argv[1])
model=os.environ['NIP_MODEL']
out=os.environ['NIP_HOOK_OUT']
os.makedirs(out,exist_ok=True)
b=zlib.decompress(open(model,'rb').read())
pat=' '.join(f'{x:02x}' for x in b[24:24+16])
slot0_bytes=262188
js=r'''
const pattern = __PATTERN__;
const blockSize = __BLOCKSIZE__;
const ranges=[];
const seen={};
const scanRanges=Process.enumerateRanges('rw-').filter(r => {
  const a=r.base.toUInt32();
  return a < 0x20000000 && r.size >= 0x30000 && r.size <= 0x1000000;
});
send({type:'scan_ranges',count:scanRanges.length,total_bytes:scanRanges.reduce((s,r)=>s+r.size,0)});
for (const r of scanRanges) {
  try {
    const hits = Memory.scanSync(r.base, r.size, pattern);
    for (const h of hits) {
      const base=h.address.sub(24);
      const key=base.toString();
      if (!seen[key]) { seen[key]=true; ranges.push({base:base,size:blockSize}); send({type:'weight_copy',base:key,region:r.base.toString(),region_size:r.size}); }
    }
  } catch (e) {}
}
if (ranges.length===0) { send({type:'fatal',error:'slot0 weight copies not found in filtered heap ranges'}); }
else {
  send({type:'monitoring',copies:ranges.length});
  let fired=false;
  MemoryAccessMonitor.enable(ranges, {
    onAccess(details) {
      if (fired) return;
      fired=true;
      try { MemoryAccessMonitor.disable(); } catch(e) {}
      const from = details.from;
      let ins=''; try { ins=Instruction.parse(from).toString(); } catch(e) { ins='parse_failed'; }
      send({type:'access',from:from.toString(),operation:details.operation,address:details.address.toString(),instruction:ins});
      let captured=false;
      try {
        Interceptor.attach(from, {
          onEnter(args) {
            if (captured) return;
            captured=true;
            const c=this.context;
            const regs={eax:c.eax,ebx:c.ebx,ecx:c.ecx,edx:c.edx,esi:c.esi,edi:c.edi,ebp:c.ebp,esp:c.esp,eip:c.eip};
            const meta={type:'context',from:from.toString(),instruction:ins,regs:{}};
            for (const k in regs) meta.regs[k]=regs[k].toString();
            send(meta);
            for (const k in regs) {
              try {
                const p=ptr(regs[k]);
                const buf=p.readByteArray(8192);
                send({type:'dump',reg:k,address:p.toString()},buf);
              } catch(e) {}
            }
            try {
              const sp=ptr(c.esp);
              const sb=sp.readByteArray(32768);
              send({type:'stack',address:sp.toString()},sb);
            } catch(e) {}
            send({type:'done'});
          }
        });
      } catch(e) { send({type:'fatal',error:'attach '+e}); }
    }
  });
  send({type:'ready'});
}
'''.replace('__PATTERN__',json.dumps(pat)).replace('__BLOCKSIZE__',str(slot0_bytes))
session=frida.attach(pid)
script=session.create_script(js)
state={'n':0}
def on_message(message,data):
    if message.get('type')!='send':
        open(os.path.join(out,'frida-errors.txt'),'a').write(json.dumps(message)+'\n');return
    p=message['payload']; typ=p.get('type','unknown')
    open(os.path.join(out,'events.jsonl'),'a').write(json.dumps(p)+'\n')
    if typ=='ready': open(os.path.join(out,'READY'),'w').write('1')
    if typ=='access': open(os.path.join(out,'ACCESS'),'w').write(json.dumps(p))
    if typ in ('dump','stack') and data is not None:
        state['n']+=1
        name=f"{state['n']:02d}_{typ}_{p.get('reg','')}_{p.get('address','').replace('0x','')}.bin"
        open(os.path.join(out,name),'wb').write(data)
    if typ=='done': open(os.path.join(out,'DONE'),'w').write('1')
    if typ=='fatal': open(os.path.join(out,'FATAL'),'w').write(p.get('error','fatal'))
script.on('message',on_message)
script.load()
for _ in range(240):
    if os.path.exists(os.path.join(out,'DONE')) or os.path.exists(os.path.join(out,'FATAL')): break
    time.sleep(1)
try: script.unload(); session.detach()
except: pass
