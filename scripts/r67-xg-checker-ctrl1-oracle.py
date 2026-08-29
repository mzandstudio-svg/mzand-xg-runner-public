#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('R67 requires Windows')

TARGET=Path(__file__).resolve().with_name('r60-xg-checker-1ply-oracle.py')
spec=importlib.util.spec_from_file_location('r67_impl',TARGET)
if spec is None or spec.loader is None: raise SystemExit(f'cannot load {TARGET}')
mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod)

u32=ctypes.windll.user32
SW_RESTORE=9
VK_CONTROL=0x11
VK_1=0x31
KEYEVENTF_KEYUP=0x0002

def press_ctrl1(hwnd:int):
    u32.ShowWindow(hwnd,SW_RESTORE)
    u32.BringWindowToTop(hwnd)
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    fg=int(u32.GetForegroundWindow() or 0)
    print(f'R67_FOREGROUND=0x{fg:08X} TARGET=0x{hwnd:08X}',flush=True)
    # keybd_event injects into the system input queue, so the application's
    # normal accelerator translation runs. This is intentionally different
    # from PostMessage(WM_KEYDOWN), which bypasses TranslateAccelerator.
    u32.keybd_event(VK_CONTROL,0,0,0)
    u32.keybd_event(VK_1,0,0,0)
    u32.keybd_event(VK_1,0,KEYEVENTF_KEYUP,0)
    u32.keybd_event(VK_CONTROL,0,KEYEVENTF_KEYUP,0)
    print('R67_CTRL1_SENT=YES',flush=True)

def analyze_one(auto,helpers,xgid:str,out_xgp:Path):
    auto.import_xgid_from_file(xgid); time.sleep(0.8)
    auto.send_command(auto.cmd.CLEAR_ANALYZE); time.sleep(0.5)
    press_ctrl1(int(auto._hwnd))
    deadline=time.time()+15.0
    while time.time()<deadline:
        try: auto._dismiss_unexpected_dialogs(accept=True)
        except Exception: pass
        time.sleep(0.5)
    helpers.export_xgp(auto,out_xgp)
    result=mod.extract_move_analysis(out_xgp)
    levels=sorted({r['level'] for r in result['rows']})
    print('R67_BINARY_EVAL_LEVELS='+','.join(str(x) for x in levels),flush=True)
    if levels != [0]: raise RuntimeError(f'R67 Ctrl+1 produced levels {levels}, expected [0]')
    print('R67_BINARY_EXACT_1PLY_GATE=PASS',flush=True)
    return result

mod.analyze_one=analyze_one
raise SystemExit(mod.main())
