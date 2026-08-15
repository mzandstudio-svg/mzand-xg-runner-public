import sys,time,json,os,struct,zlib
import frida
pid=int(sys.argv[1])
model=os.environ['NIP_MODEL']
out=os.environ['NIP_HOOK_OUT']
os.makedirs(out,exist_ok=True)
b=zlib.decompress(open(model,'rb').read())
# slot0 first weight pattern (16 bytes is long enough and proven present in runtime memory)
pat=' '.join(f'{x:02x}' for x in b[24:24+16])
js=r'''
const pattern = __PATTERN__;
let target = null;
for (const r of Process.enumerateRanges('rw-')) {
  try {
    const hits = Memory.scanSync(r.base, r.size, pattern);
    if (hits.length) { target = hits[0].address; break; }
  } catch (e) {}
}
if (target === null) { send({type:'fatal',error:'weight pattern not found'}); }
else {
  send({type:'weight',address:target.toString()});
  MemoryAccessMonitor.enable({base: target.and(ptr('0xfffff000')), size: 4096}, {
    onAccess(details) {
      try { MemoryAccessMonitor.disable(); } catch(e) {}
      const from = details.from;
      send({type:'access',from:from.toString(),operation:details.operation,address:details.address.toString(),instruction:Instruction.parse(from).toString()});
      let captured=false;
      try {
        Interceptor.attach(from, {
          onEnter(args) {
            if (captured) return;
            captured=true;
            const c=this.context;
            const regs={eax:c.eax,ebx:c.ebx,ecx:c.ecx,edx:c.edx,esi:c.esi,edi:c.edi,ebp:c.ebp,esp:c.esp,eip:c.eip};
            const meta={type:'context',from:from.toString(),instruction:Instruction.parse(from).toString(),regs:{}};
            for (const k in regs) meta.regs[k]=regs[k].toString();
            send(meta);
            for (const k in regs) {
              try {
                const p=ptr(regs[k]);
                const buf=p.readByteArray(4096);
                send({type:'dump',reg:k,address:p.toString()},buf);
              } catch(e) {}
            }
            try {
              const sp=ptr(c.esp);
              const sb=sp.readByteArray(16384);
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
'''.replace('__PATTERN__',json.dumps(pat))
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
for _ in range(180):
    if os.path.exists(os.path.join(out,'DONE')) or os.path.exists(os.path.join(out,'FATAL')): break
    time.sleep(1)
try: script.unload(); session.detach()
except: pass
