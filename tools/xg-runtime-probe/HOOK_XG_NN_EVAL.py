import ctypes
import csv
import json
import os
import pathlib
import time

import frida

OUT = pathlib.Path(os.environ.get('GITHUB_WORKSPACE', '.')) / 'xg-nn-hook-v4'
OUT.mkdir(parents=True, exist_ok=True)
report = OUT / 'report.txt'

def log(s):
    print(s, flush=True)
    with report.open('a', encoding='utf-8') as f:
        f.write(str(s) + '\n')

# Find XG process through Frida.
device = frida.get_local_device()
procs = [p for p in device.enumerate_processes() if p.name.lower() == 'extremegammon2.exe']
if not procs:
    raise SystemExit('eXtremeGammon2.exe not running')
pid = procs[0].pid
log(f'PID={pid}')

session = device.attach(pid)

js = r'''
const mod = Process.getModuleByName('eXtremeGammon2.exe');
const target = mod.base.add(0x301000);
send({kind:'ready', base:mod.base.toString(), target:target.toString(), size:mod.size});
let seq = 0;
Interceptor.attach(target, {
  onEnter(args) {
    try {
      const net = this.context.eax;
      if (net.isNull()) return;
      const n = net.readU32();
      const h = net.add(4).readU32();
      const o = net.add(8).readU32();
      if (![200, 218, 250, 252].includes(n)) return;
      if (h < 1 || h > 1024 || o < 1 || o > 16) return;
      const inp = net.add(0x40).readPointer();
      if (inp.isNull()) return;
      const v = [];
      for (let i=0; i<n; i++) v.push(inp.add(i*4).readFloat());
      send({kind:'eval', seq:seq++, tid:this.threadId, net:net.toString(), n:n, h:h, o:o, input:inp.toString(), values:v});
    } catch(e) {
      send({kind:'hook_error', error:String(e)});
    }
  }
});
'''
script = session.create_script(js)
events = []
ready = {'ok': False}

def on_message(message, data):
    if message.get('type') != 'send':
        log('FRIDA=' + json.dumps(message, sort_keys=True))
        return
    p = message.get('payload', {})
    kind = p.get('kind')
    if kind == 'ready':
        ready['ok'] = True
        log(f"HOOK_READY base={p.get('base')} target={p.get('target')} size={p.get('size')}")
    elif kind == 'eval':
        events.append(p)
        idx = len(events) - 1
        log(f"EVAL[{idx}] n={p['n']} h={p['h']} o={p['o']} net={p['net']} input={p['input']} tid={p['tid']}")
        jpath = OUT / f"eval-{idx:04d}-{p['n']}.json"
        jpath.write_text(json.dumps(p, indent=2), encoding='utf-8')
        cpath = OUT / f"eval-{idx:04d}-{p['n']}.csv"
        with cpath.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['index','value'])
            for i, x in enumerate(p['values']): w.writerow([i, repr(x)])
    else:
        log('EVENT=' + json.dumps(p, sort_keys=True))

script.on('message', on_message)
script.load()
for _ in range(50):
    if ready['ok']: break
    time.sleep(0.1)
if not ready['ok']:
    raise SystemExit('Frida hook did not become ready')

# Resolve XG main HWND and invoke Analyze -> Analyze Position by Win32 menu command.
user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
hwnds = []

def enum_cb(hwnd, lparam):
    procid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(procid))
    if procid.value == pid and user32.IsWindowVisible(hwnd):
        hwnds.append(hwnd)
    return True
user32.EnumWindows(EnumWindowsProc(enum_cb), 0)
if not hwnds:
    raise SystemExit('No visible XG window')
hwnd = hwnds[0]
menu = user32.GetMenu(hwnd)
if not menu:
    raise SystemExit('XG main menu missing')
analyze = user32.GetSubMenu(menu, 4)
if not analyze:
    raise SystemExit('Analyze submenu missing')
cmd = user32.GetMenuItemID(analyze, 1)
if cmd == 0xFFFFFFFF:
    raise SystemExit('Analyze Position command id missing')
log(f'HWND=0x{hwnd:X} ANALYZE_POSITION_COMMAND={cmd}')
user32.SendMessageW(hwnd, 0x0111, cmd, 0)
log('ANALYZE_POSITION_SENT=True')

# Let Analyze execute and capture all network calls.
deadline = time.time() + 15.0
last = -1
stable_since = time.time()
while time.time() < deadline:
    if len(events) != last:
        last = len(events); stable_since = time.time()
    if events and time.time() - stable_since > 3.0:
        break
    time.sleep(0.1)

summary = {
    'pid': pid,
    'eval_count': len(events),
    'dimensions': [{'n':e['n'],'h':e['h'],'o':e['o'],'net':e['net'],'input':e['input']} for e in events],
}
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
log('EVAL_COUNT=' + str(len(events)))
log('COUNTS=' + json.dumps({str(n):sum(1 for e in events if e['n']==n) for n in [200,218,250,252]}, sort_keys=True))
session.detach()

if not events:
    raise SystemExit('No NN evaluator calls captured')
