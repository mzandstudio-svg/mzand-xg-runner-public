import json, os, sys, time
import frida

pid=int(sys.argv[1]); target=sys.argv[2].strip().upper(); meta_path=sys.argv[3]; out=sys.argv[4]
os.makedirs(out, exist_ok=True)
meta=json.load(open(meta_path,'r',encoding='utf-8-sig'))
recs=[r for r in meta.get('records',[]) if str(r.get('network','')).upper()==target]
if not recs:
    raise SystemExit(f'no descriptors for target {target}')
for r in recs:
    r['ci']=int(r['dims'][0]); r['co']=int(r['dims'][2])
compact=[dict(network=target,object=r['object'],ci=r['ci'],co=r['co'],input_ptr=r['input_ptr'],wih_ptr=r['wih_ptr'],output_ptr=r['output_ptr']) for r in recs]
js=r'''
const recs=__RECS__;
let fired=false;
function f32s(p,n){ const a=[]; for(let i=0;i<n;i++) a.push(p.add(i*4).readFloat()); return a; }
function regs(c){ const o={}; for (const k of ['eax','ebx','ecx','edx','esi','edi','ebp','esp','eip']) { try{o[k]=c[k].toString();}catch(e){} } return o; }
const ranges=[];
for (const r of recs) {
  const n=Math.min(4096, r.ci*256*4);
  ranges.push({base:ptr(r.wih_ptr),size:n});
}
send({type:'ready',target:recs[0].network,descriptors:recs.length,ranges:ranges.map(x=>({base:x.base.toString(),size:x.size}))});
MemoryAccessMonitor.enable(ranges,{
 onAccess(details){
   if(fired) return;
   const a=parseInt(details.address.toString(),16);
   let hit=null;
   for(const r of recs){ const s=parseInt(r.wih_ptr,16), e=s+Math.min(4096,r.ci*256*4); if(a>=s && a<e){hit=r;break;} }
   if(!hit) return;
   fired=true;
   let ins=''; try{ins=Instruction.parse(details.from).toString();}catch(e){ins='parse_failed';}
   let input=[], out0=[];
   try{input=f32s(ptr(hit.input_ptr),hit.ci);}catch(e){send({type:'error',where:'input',error:String(e)});}
   try{out0=f32s(ptr(hit.output_ptr),hit.co);}catch(e){}
   send({type:'capture',network:hit.network,object:hit.object,weight_ptr:hit.wih_ptr,input_ptr:hit.input_ptr,output_ptr:hit.output_ptr,access:details.address.toString(),from:details.from.toString(),operation:details.operation,instruction:ins,regs:regs(details.context),input:input,output_before:out0});
   try{MemoryAccessMonitor.disable();}catch(e){}
   [0,1,2,5,10].forEach(ms=>setTimeout(function(){
      try{send({type:'output_sample',ms:ms,network:hit.network,object:hit.object,values:f32s(ptr(hit.output_ptr),hit.co)});}catch(e){}
   },ms));
   send({type:'captured'});
 }
});
'''.replace('__RECS__',json.dumps(compact))

session=frida.attach(pid)
script=session.create_script(js)
state={'captured':False}

def emit(p):
    with open(os.path.join(out,'events.jsonl'),'a',encoding='utf-8') as f: f.write(json.dumps(p,separators=(',',':'))+'\n')

def on_message(message,data):
    if message.get('type')!='send':
        emit({'type':'frida_message','message':message}); return
    p=message.get('payload',{}); emit(p)
    t=p.get('type')
    if t=='ready': open(os.path.join(out,'READY'),'w').write('1')
    elif t=='capture':
        json.dump(p,open(os.path.join(out,'capture.json'),'w',encoding='utf-8'),indent=2)
        vals=p.get('input',[])
        with open(os.path.join(out,f'input_{target}_{len(vals)}.txt'),'w',encoding='utf-8') as f:
            for i,v in enumerate(vals): f.write(f'{i} {v:.17g}\n')
        state['captured']=True
        open(os.path.join(out,'CAPTURED'),'w').write('1')
    elif t=='output_sample':
        with open(os.path.join(out,'output_samples.jsonl'),'a',encoding='utf-8') as f: f.write(json.dumps(p,separators=(',',':'))+'\n')
    elif t=='error': open(os.path.join(out,'ERROR'),'a',encoding='utf-8').write(json.dumps(p)+'\n')

script.on('message',on_message); script.load()
for _ in range(1800):
    if state['captured']:
        time.sleep(0.25)
        break
    time.sleep(0.1)
try: script.unload(); session.detach()
except Exception: pass
if not state['captured']:
    open(os.path.join(out,'NO_CAPTURE'),'w').write('1')
