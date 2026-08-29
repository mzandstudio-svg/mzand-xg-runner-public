#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import threading
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R52 requires Windows")

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

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
STATIC_TARGETS = {
    "dead_eval_9D5C80": (0x009D5C80, 0x0800),
    "cube_core_9DA770": (0x009DA770, 0x0300),
    "cube_mid_9DBA90": (0x009DBA90, 0x0D00),
    "live_builder_9DC690": (0x009DC690, 0x00E0),
    "cube_driver_9DC770": (0x009DC770, 0x08A9),
}
SCAN_START = 0x009D0000
SCAN_END = 0x009E4000

BPS = {
    "live_call_owner_plus1": 0x009DC835,
    "live_post_owner_plus1": 0x009DC83E,
    "live_call_centered": 0x009DC859,
    "live_post_centered": 0x009DC862,
    "live_call_owner_minus1": 0x009DC87D,
    "live_post_owner_minus1": 0x009DC886,
    "dead_call_A": 0x009DC8CD,
    "dead_post_A": 0x009DC8D8,
    "eff_call_A": 0x009DC8E9,
    "eff_post_A": 0x009DC8F1,
    "blend_post_A": 0x009DC909,
}


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
    return bytes(buf[: got.value])


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


def verify_image(h) -> None:
    if rpm(h, IMAGE_BASE, 2) != b"MZ":
        raise RuntimeError("R52 image-base contract failed: expected MZ at 0x00400000")


def disasm(md: Cs, blob: bytes, start: int) -> list[str]:
    return [
        f"0x{ins.address:08X}\t{ins.bytes.hex():<20}\t{ins.mnemonic:<8}\t{ins.op_str}"
        for ins in md.disasm(blob, start)
    ]


def scan_rel32_calls(blob: bytes, base: int, targets: set[int]) -> list[tuple[int, int]]:
    out = []
    for i in range(max(0, len(blob) - 5)):
        if blob[i] != 0xE8:
            continue
        rel = struct.unpack_from("<i", blob, i + 1)[0]
        src = base + i
        dst = (src + 5 + rel) & 0xFFFFFFFF
        if dst in targets:
            out.append((src, dst))
    return out


def dump_static(h, outdir: Path) -> list[str]:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = False
    md.skipdata = True
    summary = []
    for name, (addr, size) in STATIC_TARGETS.items():
        blob = rpm(h, addr, size)
        p = outdir / f"r52-{name}-disasm.txt"
        p.write_text("\n".join(disasm(md, blob, addr)) + "\n", encoding="utf-8")
        summary.append(f"R52_STATIC_{name}=0x{addr:08X} bytes={len(blob)} file={p.name}")

    target_addrs = {0x009DC690, 0x009D5C80, 0x009DBA90, 0x009DA770, 0x009DAD30}
    scan_blob = rpm(h, SCAN_START, SCAN_END - SCAN_START)
    calls = scan_rel32_calls(scan_blob, SCAN_START, target_addrs)
    lines = ["caller_va\ttarget_va"] + [f"0x{s:08X}\t0x{d:08X}" for s, d in sorted(calls)]
    (outdir / "r52-producer-xrefs.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary.append(f"R52_PRODUCER_XREFS={len(calls)}")
    return summary


def trigger_analyze_position(pid: int) -> None:
    time.sleep(3.0)
    import pyautogui
    from pywinauto import Desktop

    user32 = ctypes.windll.user32
    hwnd = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(w, _l):
        nonlocal hwnd
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(w, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(w):
            hwnd = w
            return False
        return True

    user32.EnumWindows(cb, 0)
    if not hwnd:
        print("R52_TRIGGER_FAIL no visible XG window", flush=True)
        return
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.7)
    pyautogui.hotkey("alt", "a")
    time.sleep(1.0)

    items = []
    desktop = Desktop(backend="uia")
    for w in desktop.windows():
        try:
            for e in w.descendants(control_type="MenuItem"):
                try:
                    name = (e.window_text() or "").strip()
                    if name:
                        items.append((name, e))
                except Exception:
                    pass
        except Exception:
            pass

    target = None
    for name, e in items:
        n = " ".join(name.lower().split())
        if n in ("analyze position", "analyse position"):
            target = e
            break
    if target is None:
        for name, e in items:
            n = " ".join(name.lower().split())
            if "analy" in n and "position" in n:
                target = e
                break
    if target is None:
        print("R52_TRIGGER_FAIL Analyze Position menu item not found", flush=True)
        return
    print(f"R52_TRIGGER_CLICK name={target.window_text()!r}", flush=True)
    target.click_input()


def capture_common(h, ctx: WOW64_CONTEXT) -> list[str]:
    out = [
        f"EAX=0x{ctx.Eax:08X}", f"EBX=0x{ctx.Ebx:08X}", f"ECX=0x{ctx.Ecx:08X}",
        f"EDX=0x{ctx.Edx:08X}", f"ESI=0x{ctx.Esi:08X}", f"EDI=0x{ctx.Edi:08X}",
        f"EBP=0x{ctx.Ebp:08X}", f"ESP=0x{ctx.Esp:08X}",
    ]
    if ctx.Ebx:
        for off, label in [(0x20, "STATE20"), (0x24, "STATE24"), (0x28, "CUBE_VALUE28"),
                           (0x2C, "CUBE_OWNER2C"), (0x30, "STATE30"), (0x34, "STATE34")]:
            out.append(f"EBX_{label}={safe_i32(h, ctx.Ebx + off)}")
        out.append(f"EBX_INPUT48_F32={safe_f32(h, ctx.Ebx + 0x48)}")
        out.append(f"EBX_EQUITY54_F32={safe_f32(h, ctx.Ebx + 0x54)}")
    out.append("STACK_DWORDS=" + ",".join(safe_u32(h, ctx.Esp + 4 * i) for i in range(10)))
    return out


def capture_bp(h, name: str, ctx: WOW64_CONTEXT) -> list[str]:
    out = [f"===== {name} VA=0x{BPS[name]:08X} ====="]
    out.extend(capture_common(h, ctx))

    if name.startswith("live_call_"):
        out.append("LIVE_CALL_STACK_CONTRACT=ESP0_parent_ebp,ESP4_input48,ESP8_argA,ESP12_argB,ESP16_argC")
        if ctx.Ebp:
            out.append("KNOT_X_EBP_M90=" + ",".join(safe_f32(h, ctx.Ebp - 0x90 + 4 * i) for i in range(4)))
            out.append("KNOT_Y_EBP_M80=" + ",".join(safe_f32(h, ctx.Ebp - 0x80 + 4 * i) for i in range(4)))
            out.append("LOCAL_C0_EBP_M40=" + ",".join(safe_f32(h, ctx.Ebp - 0x40 + 4 * i) for i in range(8)))
    elif name.startswith("live_post_"):
        out.append(f"LIVE_ENDPOINT_EBP_M8_F32={safe_f32(h, ctx.Ebp - 0x8)}")
    elif name == "dead_call_A":
        out.append("DEAD_PRODUCER_REG_CONTRACT=EAX_global_B0AD18,EDX_board_or_side,ECX_temp_state")
        if ctx.Edi:
            out.append("DEAD_TEMP_DWORDS=" + ",".join(safe_u32(h, ctx.Edi + 4 * i) for i in range(9)))
            out.append(f"DEAD_TEMP_INPUT_1C_F32={safe_f32(h, ctx.Edi + 0x1C)}")
            out.append(f"DEAD_TEMP_INPUT_20_F32={safe_f32(h, ctx.Edi + 0x20)}")
    elif name == "dead_post_A":
        out.append(f"DEAD_ENDPOINT_EBP_MC_F32={safe_f32(h, ctx.Ebp - 0xC)}")
        if ctx.Edi:
            out.append(f"DEAD_PRODUCER_RESULT_EDI_1C_F32={safe_f32(h, ctx.Edi + 0x1C)}")
    elif name == "eff_call_A":
        out.append(f"EFF_STACK_ARG0={safe_u32(h, ctx.Esp)}")
        out.append(f"EFF_STACK_ARG1={safe_u32(h, ctx.Esp + 4)}")
        out.append("EFF_REGISTER_CONTRACT=ECX_1,EDX_state_EBX,EAX_context")
    elif name == "eff_post_A":
        out.append(f"EFFICIENCY_EBP_M10_F32={safe_f32(h, ctx.Ebp - 0x10)}")
    elif name == "blend_post_A":
        out.append(f"BLEND_LIVE_EBP_M8_F32={safe_f32(h, ctx.Ebp - 0x8)}")
        out.append(f"BLEND_DEAD_EBP_MC_F32={safe_f32(h, ctx.Ebp - 0xC)}")
        out.append(f"BLEND_EFF_EBP_M10_F32={safe_f32(h, ctx.Ebp - 0x10)}")
        if ctx.Ebx:
            out.append(f"BLEND_RESULT_EBX_54_F32={safe_f32(h, ctx.Ebx + 0x54)}")
    return out


def dynamic_trace(h, pid: int, outdir: Path) -> list[str]:
    originals = {name: rpm(h, addr, 1) for name, addr in BPS.items()}
    for name, addr in BPS.items():
        if originals[name] == b"\xCC":
            raise RuntimeError(f"R52 refuses pre-existing INT3 at {name} 0x{addr:08X}")

    if not k32.DebugActiveProcess(pid):
        raise OSError(ctypes.get_last_error(), "DebugActiveProcess")

    captured: dict[str, list[str]] = {}
    armed = set(BPS)
    trace_path = outdir / "r52-live-endpoint-origin-trace.txt"
    try:
        for name, addr in BPS.items():
            wpm(h, addr, b"\xCC")
        threading.Thread(target=trigger_analyze_position, args=(pid,), daemon=True).start()
        deadline = time.time() + 100.0

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
                                captured[hit_name] = capture_bp(h, hit_name, ctx)
                                print(f"R52_CAPTURED={hit_name}", flush=True)
                    finally:
                        k32.CloseHandle(th)
            elif code == EXIT_PROCESS_DEBUG_EVENT:
                k32.ContinueDebugEvent(ev_pid, tid, DBG_CONTINUE)
                break
            k32.ContinueDebugEvent(ev_pid, tid, DBG_CONTINUE)

            live_calls = [n for n in captured if n.startswith("live_call_")]
            live_posts = [n for n in captured if n.startswith("live_post_")]
            required = {"dead_call_A", "dead_post_A", "eff_call_A", "eff_post_A", "blend_post_A"}
            if live_calls and live_posts and required.issubset(captured):
                break
    finally:
        for name in list(armed):
            try:
                wpm(h, BPS[name], originals[name])
            except Exception:
                pass
        try:
            k32.DebugActiveProcessStop(pid)
        except Exception:
            pass

    lines = [f"R52_PID={pid}"]
    for name in BPS:
        if name in captured:
            lines.extend(captured[name])
    lines.append("R52_CAPTURE_SET=" + ",".join(captured.keys()))
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    live_calls = [n for n in captured if n.startswith("live_call_")]
    live_posts = [n for n in captured if n.startswith("live_post_")]
    required = {"dead_call_A", "dead_post_A", "eff_call_A", "eff_post_A", "blend_post_A"}
    if not live_calls or not live_posts or not required.issubset(captured):
        missing = sorted(required - set(captured))
        raise RuntimeError(f"R52 incomplete trace: live_calls={live_calls} live_posts={live_posts} missing={missing}")

    return [
        "R52_LIVE_PRODUCER=0x009DC690",
        "R52_DEAD_PRODUCER=0x009D5C80",
        "R52_LIVE_STORE_SLOT=[ebp-0x08]",
        "R52_DEAD_STORE_SLOT=[ebp-0x0c]",
        "R52_EFF_STORE_SLOT=[ebp-0x10]",
        f"R52_LIVE_CALLSITE_CAPTURE={live_calls[0]}",
        f"R52_LIVE_POST_CAPTURE={live_posts[0]}",
        "R52_LIVE_ENDPOINT_ORIGIN_TRACE=PASS",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--outdir", required=True, type=Path)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    h = k32.OpenProcess(PROCESS_ALL_ACCESS, False, args.pid)
    if not h:
        raise OSError(ctypes.get_last_error(), "OpenProcess")
    summary = [f"R52_PID={args.pid}", "R52_IMAGE_BASE=0x00400000"]
    try:
        verify_image(h)
        summary.extend(dump_static(h, args.outdir))
        summary.extend(dynamic_trace(h, args.pid, args.outdir))
        summary.append("R52_PRODUCTION_BEHAVIOR_CHANGED=NO")
        summary.append("R52_XG_ENDPOINT_ORIGIN=PASS")
        (args.outdir / "r52-summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
        print("\n".join(summary))
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
