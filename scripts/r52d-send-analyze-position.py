#!/usr/bin/env python3
import ctypes
import ctypes.wintypes as wt
import sys
import time

if sys.platform != 'win32':
    raise SystemExit('Windows only')

PID=int(sys.argv[1])
WM_COMMAND=0x0111
ANALYZE_POSITION=266  # XG 2.10 command profile, upstream XGAutomator authority.
user32=ctypes.windll.user32
hwnd=0

@ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
def cb(w,_l):
    global hwnd
    p=wt.DWORD(); user32.GetWindowThreadProcessId(w,ctypes.byref(p))
    if p.value==PID and user32.IsWindowVisible(w):
        hwnd=w; return False
    return True

user32.EnumWindows(cb,0)
if not hwnd:
    raise SystemExit('R52D_TRIGGER_FAIL no visible XG window')
user32.ShowWindow(hwnd,5)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)
print(f'R52D_TRIGGER HWND=0x{int(hwnd):x} WM_COMMAND={ANALYZE_POSITION}',flush=True)
rv=user32.SendMessageW(hwnd,WM_COMMAND,ANALYZE_POSITION,0)
print(f'R52D_TRIGGER_ANALYZE_POSITION=PASS RETURN={rv}',flush=True)
