#!/usr/bin/env python3
import ctypes, ctypes.wintypes as wt, os, struct, sys, threading, time
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('Windows only')

k32=ctypes.WinDLL('kernel32', use_last_error=True)

DBG_CONTINUE=0x00010002
DBG_EXCEPTION_NOT_HANDLED=0x80010001
EXCEPTION_DEBUG_EVENT=1
EXIT_PROCESS_DEBUG_EVENT=5
PROCESS_ALL_ACCESS=0x1F0FFF
THREAD_ALL_ACCESS=0x1F03FF
CONTEXT_i386=0x00010000
CONTEXT_CONTROL=CONTEXT_i386|0x1
CONTEXT_INTEGER=CONTEXT_i386|0x2
CONTEXT_SEGMENTS=CONTEXT_i386|0x4
CONTEXT_FLOATING_POINT=CONTEXT_i386|0x8
CONTEXT_DEBUG_REGISTERS=CONTEXT_i386|0x10
CONTEXT_FULL=CONTEXT_CONTROL|CONTEXT_INTEGER|CONTEXT_SEGMENTS

class FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_=[('ControlWord',wt.DWORD),('StatusWord',wt.DWORD),('TagWord',wt.DWORD),
              ('ErrorOffset',wt.DWORD),('ErrorSelector',wt.DWORD),('DataOffset',wt.DWORD),
              ('DataSelector',wt.DWORD),('RegisterArea',ctypes.c_ubyte*80),('Cr0NpxState',wt.DWORD)]
class WOW64_CONTEXT(ctypes.Structure):
    _fields_=[('ContextFlags',wt.DWORD),('Dr0',wt.DWORD),('Dr1',wt.DWORD),('Dr2',wt.DWORD),('Dr3',wt.DWORD),
              ('Dr6',wt.DWORD),('Dr7',wt.DWORD),('FloatSave',FLOATING_SAVE_AREA),
              ('SegGs',wt.DWORD),('SegFs',wt.DWORD),('SegEs',wt.DWORD),('SegDs',wt.DWORD),
              ('Edi',wt.DWORD),('Esi',wt.DWORD),('Ebx',wt.DWORD),('Edx',wt.DWORD),('Ecx',wt.DWORD),('Eax',wt.DWORD),
              ('Ebp',wt.DWORD),('Eip',wt.DWORD),('SegCs',wt.DWORD),('EFlags',wt.DWORD),('Esp',wt.DWORD),('SegSs',wt.DWORD),
              ('ExtendedRegisters',ctypes.c_ubyte*512)]

k32.OpenProcess.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k32.OpenProcess.restype=wt.HANDLE
k32.OpenThread.argtypes=[wt.DWORD,wt.BOOL,wt.DWORD]; k32.OpenThread.restype=wt.HANDLE
k32.ReadProcessMemory.argtypes=[wt.HANDLE,wt.LPCVOID,wt.LPVOID,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]; k32.ReadProcessMemory.restype=wt.BOOL
k32.WriteProcessMemory.argtypes=[wt.HANDLE,wt.LPVOID,wt.LPCVOID,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]; k32.WriteProcessMemory.restype=wt.BOOL
k32.FlushInstructionCache.argtypes=[wt.HANDLE,wt.LPCVOID,ctypes.c_size_t]
k32.DebugActiveProcess.argtypes=[wt.DWORD]; k32.DebugActiveProcess.restype=wt.BOOL
k32.DebugActiveProcessStop.argtypes=[wt.DWORD]
k32.WaitForDebugEvent.argtypes=[wt.LPVOID,wt.DWORD]; k32.WaitForDebugEvent.restype=wt.BOOL
k32.ContinueDebugEvent.argtypes=[wt.DWORD,wt.DWORD,wt.DWORD]
k32.Wow64GetThreadContext.argtypes=[wt.HANDLE,ctypes.POINTER(WOW64_CONTEXT)]; k32.Wow64GetThreadContext.restype=wt.BOOL
k32.Wow64SetThreadContext.argtypes=[wt.HANDLE,ctypes.POINTER(WOW64_CONTEXT)]; k32.Wow64SetThreadContext.restype=wt.BOOL
k32.CloseHandle.argtypes=[wt.HANDLE]

# R36 proved the loaded image RVA and direct call site.
BP_RVA=0x5dc8e9  # before call xg_cube_efficiency dispatcher in main cubeful path

def rpm(h,addr,n):
    b=(ctypes.c_ubyte*n)(); got=ctypes.c_size_t()
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(addr),b,n,ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(),f'RPM 0x{addr:x}')
    return bytes(b[:got.value])
def wpm(h,addr,data):
    buf=(ctypes.c_ubyte*len(data)).from_buffer_copy(data); got=ctypes.c_size_t()
    if not k32.WriteProcessMemory(h,ctypes.c_void_p(addr),buf,len(data),ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(),f'WPM 0x{addr:x}')
    k32.FlushInstructionCache(h,ctypes.c_void_p(addr),len(data))
def f32(h,addr): return struct.unpack('<f',rpm(h,addr,4))[0]
def i32(h,addr): return struct.unpack('<i',rpm(h,addr,4))[0]
def u32(h,addr): return struct.unpack('<I',rpm(h,addr,4))[0]

def module_base(pid):
    # XG2 is non-ASLR in the observed build; verify MZ at canonical base first.
    h=k32.OpenProcess(PROCESS_ALL_ACCESS,False,pid)
    if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')
    try:
        if rpm(h,0x400000,2)==b'MZ': return 0x400000
    finally: k32.CloseHandle(h)
    raise RuntimeError('XG image base not 0x400000; R37 refuses to guess')

def trigger_ctrl1():
    time.sleep(3.0)
    import pyautogui
    import ctypes
    user32=ctypes.windll.user32
    hwnd=0
    # Find visible top-level window owned by this process indirectly via title/class is brittle;
    # foreground current XG window by enumerating windows.
    target_pid=PID
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(w,l):
        nonlocal hwnd
        p=wt.DWORD(); user32.GetWindowThreadProcessId(w,ctypes.byref(p))
        if p.value==target_pid and user32.IsWindowVisible(w):
            hwnd=w; return False
        return True
    user32.EnumWindows(cb,0)
    if not hwnd:
        print('R37_TRIGGER_FAIL no visible XG window',flush=True); return
    user32.ShowWindow(hwnd,5); user32.SetForegroundWindow(hwnd); time.sleep(.4)
    print(f'R37_TRIGGER_CTRL1 HWND=0x{int(hwnd):x}',flush=True)
    pyautogui.hotkey('ctrl','1')

PID=int(sys.argv[1]); OUT=Path(sys.argv[2]); OUT.parent.mkdir(parents=True,exist_ok=True)
base=module_base(PID); bp=base+BP_RVA
h=k32.OpenProcess(PROCESS_ALL_ACCESS,False,PID)
if not h: raise OSError(ctypes.get_last_error(),'OpenProcess')
orig=rpm(h,bp,1)
print(f'R37_ATTACH PID={PID} BASE=0x{base:x} BP=0x{bp:x} ORIG={orig.hex()}',flush=True)
if not k32.DebugActiveProcess(PID): raise OSError(ctypes.get_last_error(),'DebugActiveProcess')
try:
    wpm(h,bp,b'\xCC')
    threading.Thread(target=trigger_ctrl1,daemon=True).start()
    deadline=time.time()+90; captured=False
    with OUT.open('w',encoding='utf-8') as f:
        while time.time()<deadline and not captured:
            raw=ctypes.create_string_buffer(192)
            if not k32.WaitForDebugEvent(raw,1000): continue
            code,pid,tid=struct.unpack_from('<III',raw.raw,0)
            status=DBG_CONTINUE
            if code==EXCEPTION_DEBUG_EVENT:
                # EXCEPTION_DEBUG_INFO starts at offset 12; ExceptionCode is first DWORD.
                exc=struct.unpack_from('<I',raw.raw,12)[0]
                th=k32.OpenThread(THREAD_ALL_ACCESS,False,tid)
                if th:
                    ctx=WOW64_CONTEXT(); ctx.ContextFlags=CONTEXT_FULL
                    if k32.Wow64GetThreadContext(th,ctypes.byref(ctx)):
                        if exc==0x80000003 and ctx.Eip==bp+1:
                            ebp=ctx.Ebp; ebx=ctx.Ebx
                            # Restore instruction and rewind EIP.
                            wpm(h,bp,orig); ctx.Eip=bp
                            k32.Wow64SetThreadContext(th,ctypes.byref(ctx))
                            def dump_arr(addr,count):
                                return [f32(h,addr+4*i) for i in range(count)]
                            f.write(f'PID={PID}\nBASE=0x{base:08x}\nTHREAD={tid}\nEBP=0x{ebp:08x}\nEBX=0x{ebx:08x}\n')
                            f.write(f'LIVE_ENDPOINT_F8={f32(h,ebp-0x8):.9g}\n')
                            f.write(f'DEAD_ENDPOINT_F4={f32(h,ebp-0xc):.9g}\n')
                            f.write('KNOT_X_EBP_M90='+','.join(f'{x:.9g}' for x in dump_arr(ebp-0x90,4))+'\n')
                            f.write('KNOT_Y_EBP_M80='+','.join(f'{x:.9g}' for x in dump_arr(ebp-0x80,4))+'\n')
                            f.write('LOCAL_C0='+','.join(f'{x:.9g}' for x in dump_arr(ebp-0x40,8))+'\n')
                            # Main cubeful context copied at EDI=EBP-0xB4 immediately before endpoint call.
                            f.write('CTX_EBP_MB4_DWORDS='+','.join(f'0x{u32(h,ebp-0xb4+4*i):08x}' for i in range(24))+'\n')
                            f.write('CTX_EBP_MB4_FLOATS='+','.join(f'{f32(h,ebp-0xb4+4*i):.9g}' for i in range(24))+'\n')
                            f.write(f'EBX_CUBE_OWNER_FIELD_2C={i32(h,ebx+0x2c)}\n')
                            f.write(f'EBX_INPUT_48={f32(h,ebx+0x48):.9g}\n')
                            f.write(f'EBX_CURRENT_EQUITY_54={f32(h,ebx+0x54):.9g}\n')
                            f.flush(); captured=True
                            print('R37_BREAKPOINT_CAPTURED=PASS',flush=True)
                    k32.CloseHandle(th)
            elif code==EXIT_PROCESS_DEBUG_EVENT:
                break
            k32.ContinueDebugEvent(pid,tid,status)
        if not captured:
            f.write('R37_BREAKPOINT_CAPTURED=NO\n')
            raise RuntimeError('cubeful breakpoint not reached')
finally:
    try: wpm(h,bp,orig)
    except Exception: pass
    k32.DebugActiveProcessStop(PID)
    k32.CloseHandle(h)
print(f'R37_TRACE=PASS OUT={OUT}',flush=True)
