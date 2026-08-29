#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R57 requires Windows")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

DBG_CONTINUE = 0x00010002
EXCEPTION_DEBUG_EVENT = 1
EXIT_PROCESS_DEBUG_EVENT = 5
EXCEPTION_BREAKPOINT = 0x80000003
PROCESS_ALL_ACCESS = 0x1F0FFF
THREAD_ALL_ACCESS = 0x1F03FF
CONTEXT_i386 = 0x00010000
CONTEXT_CONTROL = CONTEXT_i386 | 0x1
CONTEXT_INTEGER = CONTEXT_i386 | 0x2
CONTEXT_SEGMENTS = CONTEXT_i386 | 0x4
CONTEXT_FULL = CONTEXT_CONTROL | CONTEXT_INTEGER | CONTEXT_SEGMENTS
IMAGE_BASE = 0x00400000

BPS = {
    "driver_entry": 0x009DC770,
    "recursive_call_A": 0x009DC963,
    "recursive_call_B": 0x009DCF29,
    "wrapper_entry": 0x009DD030,
    "root_call": 0x009DD039,
}

RETURN_TO_CALLER = {
    0x009DC968: "recursive_A_return",
    0x009DCF2E: "recursive_B_return",
    0x009DD03E: "root_return",
}

STATE_FIELDS = [
    (0x20, "STATE20", "i32"),
    (0x24, "STATE24", "i32"),
    (0x28, "CUBE_VALUE28", "i32"),
    (0x2C, "CUBE_OWNER2C", "i32"),
    (0x30, "STATE30", "i32"),
    (0x34, "STATE34", "i32"),
    (0x38, "STATE38", "i32"),
    (0x48, "INPUT48", "f32"),
    (0x54, "EQUITY54", "f32"),
]


class FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [
        ("ControlWord", wt.DWORD), ("StatusWord", wt.DWORD), ("TagWord", wt.DWORD),
        ("ErrorOffset", wt.DWORD), ("ErrorSelector", wt.DWORD), ("DataOffset", wt.DWORD),
        ("DataSelector", wt.DWORD), ("RegisterArea", ctypes.c_ubyte * 80), ("Cr0NpxState", wt.DWORD),
    ]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", wt.DWORD),
        ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD), ("Dr3", wt.DWORD),
        ("Dr6", wt.DWORD), ("Dr7", wt.DWORD), ("FloatSave", FLOATING_SAVE_AREA),
        ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD), ("SegDs", wt.DWORD),
        ("Edi", wt.DWORD), ("Esi", wt.DWORD), ("Ebx", wt.DWORD), ("Edx", wt.DWORD),
        ("Ecx", wt.DWORD), ("Eax", wt.DWORD), ("Ebp", wt.DWORD), ("Eip", wt.DWORD),
        ("SegCs", wt.DWORD), ("EFlags", wt.DWORD), ("Esp", wt.DWORD), ("SegSs", wt.DWORD),
        ("ExtendedRegisters", ctypes.c_ubyte * 512),
    ]


k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenThread.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.WriteProcessMemory.argtypes = [wt.HANDLE, wt.LPVOID, wt.LPCVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.restype = wt.BOOL
k32.FlushInstructionCache.argtypes = [wt.HANDLE, wt.LPCVOID, ctypes.c_size_t]
k32.DebugActiveProcess.argtypes = [wt.DWORD]
k32.DebugActiveProcess.restype = wt.BOOL
k32.DebugActiveProcessStop.argtypes = [wt.DWORD]
k32.WaitForDebugEvent.argtypes = [wt.LPVOID, wt.DWORD]
k32.WaitForDebugEvent.restype = wt.BOOL
k32.ContinueDebugEvent.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD]
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64GetThreadContext.restype = wt.BOOL
k32.Wow64SetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64SetThreadContext.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]


def rpm(h, addr: int, n: int) -> bytes:
    buf = (ctypes.c_ubyte * n)()
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(), f"ReadProcessMemory 0x{addr:08X}")
    return bytes(buf[:got.value])


def wpm(h, addr: int, data: bytes) -> None:
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    got = ctypes.c_size_t()
    if not k32.WriteProcessMemory(h, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(got)):
        raise OSError(ctypes.get_last_error(), f"WriteProcessMemory 0x{addr:08X}")
    k32.FlushInstructionCache(h, ctypes.c_void_p(addr), len(data))


def u32(h, addr: int) -> int:
    return struct.unpack("<I", rpm(h, addr, 4))[0]


def i32(h, addr: int) -> int:
    return struct.unpack("<i", rpm(h, addr, 4))[0]


def f32(h, addr: int) -> float:
    return struct.unpack("<f", rpm(h, addr, 4))[0]


def safe_u32(h, addr: int) -> str:
    try:
        return f"0x{u32(h, addr):08X}"
    except Exception as exc:
        return f"ERR({exc})"


def safe_i32(h, addr: int) -> str:
    try:
        return str(i32(h, addr))
    except Exception as exc:
        return f"ERR({exc})"


def safe_f32(h, addr: int) -> str:
    try:
        return f"{f32(h, addr):.9g}"
    except Exception as exc:
        return f"ERR({exc})"


def dump_state(h, state: int, prefix: str) -> list[str]:
    lines = [f"{prefix}_PTR=0x{state:08X}"]
    if not state:
        return lines
    for off, label, kind in STATE_FIELDS:
        if kind == "f32":
            value = safe_f32(h, state + off)
        else:
            value = safe_i32(h, state + off)
        lines.append(f"{prefix}_{label}={value}")
    return lines


def capture(h, name: str, ctx: WOW64_CONTEXT) -> list[str]:
    lines = [
        f"===== {name} VA=0x{BPS[name]:08X} =====",
        f"EAX=0x{ctx.Eax:08X}", f"EBX=0x{ctx.Ebx:08X}", f"ECX=0x{ctx.Ecx:08X}",
        f"EDX=0x{ctx.Edx:08X}", f"ESI=0x{ctx.Esi:08X}", f"EDI=0x{ctx.Edi:08X}",
        f"EBP=0x{ctx.Ebp:08X}", f"ESP=0x{ctx.Esp:08X}",
        "STACK_DWORDS=" + ",".join(safe_u32(h, ctx.Esp + 4 * i) for i in range(12)),
    ]

    if name == "driver_entry":
        ret = 0
        try:
            ret = u32(h, ctx.Esp)
        except Exception:
            pass
        lines.append(f"DRIVER_RETURN_ADDRESS=0x{ret:08X}")
        lines.append(f"DRIVER_CALLER_CLASS={RETURN_TO_CALLER.get(ret, 'unknown')}")
        lines.append(f"DRIVER_INPUT_FLAG={safe_u32(h, ctx.Esp + 4)}")
        lines.append("DRIVER_ENTRY_CONTRACT=ECX_state,EDX_board_or_side,EAX_evaluator,STACK4_flag")
        lines.extend(dump_state(h, ctx.Ecx, "ENTRY_STATE"))
    elif name in ("recursive_call_A", "recursive_call_B", "root_call"):
        lines.append("PRECALL_CONTRACT=ECX_state,EDX_board_or_side,EAX_evaluator,STACK0_flag_or_existing_stack")
        lines.extend(dump_state(h, ctx.Ecx, "PRECALL_STATE"))
    elif name == "wrapper_entry":
        lines.append(f"WRAPPER_RETURN_ADDRESS={safe_u32(h, ctx.Esp)}")
        lines.append(f"WRAPPER_STACK_ARG0={safe_u32(h, ctx.Esp + 4)}")
        lines.append(f"WRAPPER_STACK_ARG1={safe_u32(h, ctx.Esp + 8)}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=45.0)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    h = k32.OpenProcess(PROCESS_ALL_ACCESS, False, args.pid)
    if not h:
        raise OSError(ctypes.get_last_error(), "OpenProcess")

    originals = {}
    captured: dict[str, list[str]] = {}
    armed = set(BPS)
    attached = False
    try:
        if rpm(h, IMAGE_BASE, 2) != b"MZ":
            raise RuntimeError("R57 expected XG image at 0x00400000")
        originals = {name: rpm(h, va, 1) for name, va in BPS.items()}
        for name, b in originals.items():
            if b == b"\xCC":
                raise RuntimeError(f"R57 refuses pre-existing INT3 at {name}")

        if not k32.DebugActiveProcess(args.pid):
            raise OSError(ctypes.get_last_error(), "DebugActiveProcess")
        attached = True
        for name, va in BPS.items():
            wpm(h, va, b"\xCC")

        print(f"R57_ATTACH=PASS PID={args.pid}", flush=True)
        print("R57_ARMED=" + ",".join(f"{n}@0x{BPS[n]:08X}" for n in BPS), flush=True)
        deadline = time.time() + args.seconds

        while time.time() < deadline:
            raw = ctypes.create_string_buffer(192)
            if not k32.WaitForDebugEvent(raw, 1000):
                continue
            code, ev_pid, tid = struct.unpack_from("<III", raw.raw, 0)
            if code == EXCEPTION_DEBUG_EVENT:
                exc = struct.unpack_from("<I", raw.raw, 12)[0]
                th = k32.OpenThread(THREAD_ALL_ACCESS, False, tid)
                if th:
                    try:
                        ctx = WOW64_CONTEXT()
                        ctx.ContextFlags = CONTEXT_FULL
                        if k32.Wow64GetThreadContext(th, ctypes.byref(ctx)) and exc == EXCEPTION_BREAKPOINT:
                            hit_va = (ctx.Eip - 1) & 0xFFFFFFFF
                            hit_name = next((n for n in armed if BPS[n] == hit_va), None)
                            if hit_name is not None:
                                wpm(h, hit_va, originals[hit_name])
                                armed.remove(hit_name)
                                ctx.Eip = hit_va
                                if not k32.Wow64SetThreadContext(th, ctypes.byref(ctx)):
                                    raise OSError(ctypes.get_last_error(), "Wow64SetThreadContext")
                                captured[hit_name] = capture(h, hit_name, ctx)
                                print(f"R57_CAPTURE={hit_name}", flush=True)
                    finally:
                        k32.CloseHandle(th)
            elif code == EXIT_PROCESS_DEBUG_EVENT:
                k32.ContinueDebugEvent(ev_pid, tid, DBG_CONTINUE)
                break
            k32.ContinueDebugEvent(ev_pid, tid, DBG_CONTINUE)

            if "root_call" in captured and "driver_entry" in captured:
                # We have the decisive root-to-driver transition; do not wait out the full window.
                break
    finally:
        for name in list(armed):
            try:
                if name in originals:
                    wpm(h, BPS[name], originals[name])
            except Exception:
                pass
        if attached:
            try:
                k32.DebugActiveProcessStop(args.pid)
            except Exception:
                pass
        k32.CloseHandle(h)

    lines = [f"R57_PID={args.pid}"]
    for name in BPS:
        if name in captured:
            lines.extend(captured[name])
    lines.append("R57_CAPTURE_SET=" + ",".join(captured.keys()))
    reached = "driver_entry" in captured or "root_call" in captured or "wrapper_entry" in captured
    lines.append(f"R57_DRIVER_REACHED={'PASS' if reached else 'NO'}")
    lines.append("R57_PRODUCTION_BEHAVIOR_CHANGED=NO")
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0 if reached else 2


if __name__ == "__main__":
    raise SystemExit(main())
