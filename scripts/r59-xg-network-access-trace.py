#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R59 requires Windows")

from capstone import Cs, CS_ARCH_X86, CS_MODE_32

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_ALL_ACCESS = 0x1F0FFF
THREAD_ALL_ACCESS = 0x1F03FF
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
MEM_MAPPED = 0x40000
MEM_IMAGE = 0x1000000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

DBG_CONTINUE = 0x00010002
EXCEPTION_DEBUG_EVENT = 1
CREATE_THREAD_DEBUG_EVENT = 2
CREATE_PROCESS_DEBUG_EVENT = 3
EXIT_PROCESS_DEBUG_EVENT = 5
EXCEPTION_BREAKPOINT = 0x80000003
EXCEPTION_SINGLE_STEP = 0x80000004

CONTEXT_i386 = 0x00010000
CONTEXT_CONTROL = CONTEXT_i386 | 0x1
CONTEXT_INTEGER = CONTEXT_i386 | 0x2
CONTEXT_SEGMENTS = CONTEXT_i386 | 0x4
CONTEXT_FLOATING_POINT = CONTEXT_i386 | 0x8
CONTEXT_DEBUG_REGISTERS = CONTEXT_i386 | 0x10
CONTEXT_FULL = CONTEXT_CONTROL | CONTEXT_INTEGER | CONTEXT_SEGMENTS

WM_COMMAND = 0x0111
ANALYZE_POSITION_XG210 = 266
CLEAR_ANALYZE_XG210 = 272

# Recovered native tensor boundaries in the float payload after the 12-byte file
# header. Only the first four are watched because x86 exposes four DR slots.
TENSOR_FLOAT_OFFSETS = [0, 53261, 110101, 166941, 172716]
SIGNATURE_BYTES = 24


class FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [
        ("ControlWord", wt.DWORD), ("StatusWord", wt.DWORD),
        ("TagWord", wt.DWORD), ("ErrorOffset", wt.DWORD),
        ("ErrorSelector", wt.DWORD), ("DataOffset", wt.DWORD),
        ("DataSelector", wt.DWORD), ("RegisterArea", ctypes.c_ubyte * 80),
        ("Cr0NpxState", wt.DWORD),
    ]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", wt.DWORD),
        ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD),
        ("Dr3", wt.DWORD), ("Dr6", wt.DWORD), ("Dr7", wt.DWORD),
        ("FloatSave", FLOATING_SAVE_AREA),
        ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD),
        ("SegDs", wt.DWORD), ("Edi", wt.DWORD), ("Esi", wt.DWORD),
        ("Ebx", wt.DWORD), ("Edx", wt.DWORD), ("Ecx", wt.DWORD),
        ("Eax", wt.DWORD), ("Ebp", wt.DWORD), ("Eip", wt.DWORD),
        ("SegCs", wt.DWORD), ("EFlags", wt.DWORD), ("Esp", wt.DWORD),
        ("SegSs", wt.DWORD), ("ExtendedRegisters", ctypes.c_ubyte * 512),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("PartitionId", wt.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenThread.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.VirtualQueryEx.argtypes = [wt.HANDLE, wt.LPCVOID, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.DebugActiveProcess.argtypes = [wt.DWORD]
k32.DebugActiveProcess.restype = wt.BOOL
k32.DebugActiveProcessStop.argtypes = [wt.DWORD]
k32.DebugActiveProcessStop.restype = wt.BOOL
k32.DebugSetProcessKillOnExit.argtypes = [wt.BOOL]
k32.DebugSetProcessKillOnExit.restype = wt.BOOL
k32.WaitForDebugEvent.argtypes = [wt.LPVOID, wt.DWORD]
k32.WaitForDebugEvent.restype = wt.BOOL
k32.ContinueDebugEvent.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD]
k32.ContinueDebugEvent.restype = wt.BOOL
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64GetThreadContext.restype = wt.BOOL
k32.Wow64SetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64SetThreadContext.restype = wt.BOOL
k32.SuspendThread.argtypes = [wt.HANDLE]
k32.SuspendThread.restype = wt.DWORD
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.ResumeThread.restype = wt.DWORD
k32.CloseHandle.argtypes = [wt.HANDLE]

u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.PostMessageW.restype = wt.BOOL
u32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
u32.EnumWindows.restype = wt.BOOL
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.GetWindowThreadProcessId.restype = wt.DWORD
u32.IsWindowVisible.argtypes = [wt.HWND]
u32.IsWindowVisible.restype = wt.BOOL


@dataclass
class MemMatch:
    tensor: int
    file_offset: int
    address: int
    region_base: int
    region_size: int
    protect: int
    mem_type: int


def rpm(h, addr: int, n: int) -> bytes:
    b = (ctypes.c_ubyte * n)()
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), b, n, ctypes.byref(got)):
        return b""
    return bytes(b[:got.value])


def find_model_file(exe: Path) -> Path:
    root = exe.parent
    exact = list(root.rglob("eXtremeGammon v2.dat"))
    if exact:
        return exact[0]
    loose = [p for p in root.rglob("*.dat") if "v2" in p.name.lower() and "extremegammon" in p.name.lower()]
    if loose:
        return loose[0]
    raise RuntimeError(f"eXtremeGammon v2.dat not found under {root}")


def iter_regions(h):
    addr = 0
    limit = 0x80000000
    mbi = MEMORY_BASIC_INFORMATION()
    while addr < limit:
        got = k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if not got:
            addr += 0x1000
            continue
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize)
        if size <= 0:
            addr += 0x1000
            continue
        yield base, size, int(mbi.State), int(mbi.Protect), int(mbi.Type)
        nxt = base + size
        addr = nxt if nxt > addr else addr + 0x1000


def scan_signatures(h, model: bytes) -> list[MemMatch]:
    sigs = []
    for ti, foff in enumerate(TENSOR_FLOAT_OFFSETS):
        off = 12 + 4 * foff
        if off + SIGNATURE_BYTES <= len(model):
            sigs.append((ti, off, model[off:off + SIGNATURE_BYTES]))
    matches: list[MemMatch] = []
    chunk_size = 2 * 1024 * 1024
    max_matches = 80
    for base, size, state, protect, mem_type in iter_regions(h):
        if state != MEM_COMMIT or (protect & PAGE_NOACCESS) or (protect & PAGE_GUARD):
            continue
        pos = 0
        carry = b""
        while pos < size:
            n = min(chunk_size, size - pos)
            data = rpm(h, base + pos, n)
            if not data:
                pos += n
                carry = b""
                continue
            buf = carry + data
            buf_base = base + pos - len(carry)
            for ti, off, sig in sigs:
                start = 0
                while True:
                    j = buf.find(sig, start)
                    if j < 0:
                        break
                    addr = buf_base + j
                    matches.append(MemMatch(ti, off, addr, base, size, protect, mem_type))
                    if len(matches) >= max_matches:
                        return matches
                    start = j + 1
            carry = buf[-(SIGNATURE_BYTES - 1):] if len(buf) >= SIGNATURE_BYTES else buf
            pos += n
    return matches


def choose_watch_addresses(matches: list[MemMatch]) -> list[MemMatch]:
    # Prefer private decoded model storage, then mapped storage, and prefer one
    # independent tensor start per DR slot.
    type_rank = {MEM_PRIVATE: 0, MEM_MAPPED: 1, MEM_IMAGE: 2}
    ordered = sorted(matches, key=lambda m: (type_rank.get(m.mem_type, 3), m.tensor, m.address))
    out: list[MemMatch] = []
    used_tensor = set()
    used_addr = set()
    for m in ordered:
        if m.tensor in used_tensor or m.address in used_addr:
            continue
        if m.address & 3:
            continue
        out.append(m)
        used_tensor.add(m.tensor)
        used_addr.add(m.address)
        if len(out) == 4:
            break
    if not out:
        for m in ordered:
            if m.address not in used_addr and not (m.address & 3):
                out.append(m)
                used_addr.add(m.address)
                if len(out) == 4:
                    break
    return out


def set_hw_watchpoints(tid: int, addresses: list[int]) -> bool:
    th = k32.OpenThread(THREAD_ALL_ACCESS, False, tid)
    if not th:
        return False
    suspended = False
    try:
        r = k32.SuspendThread(th)
        suspended = r != 0xFFFFFFFF
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = CONTEXT_DEBUG_REGISTERS | CONTEXT_CONTROL | CONTEXT_INTEGER
        if not k32.Wow64GetThreadContext(th, ctypes.byref(ctx)):
            return False
        regs = addresses[:4] + [0] * (4 - len(addresses))
        ctx.Dr0, ctx.Dr1, ctx.Dr2, ctx.Dr3 = regs
        ctx.Dr6 = 0
        dr7 = 0
        for i in range(len(addresses[:4])):
            dr7 |= 1 << (2 * i)       # local enable
            dr7 |= 3 << (16 + 4 * i) # read/write
            dr7 |= 3 << (18 + 4 * i) # 4-byte length
        ctx.Dr7 = dr7
        return bool(k32.Wow64SetThreadContext(th, ctypes.byref(ctx)))
    finally:
        if suspended:
            k32.ResumeThread(th)
        k32.CloseHandle(th)


def clear_dr6_and_get_context(tid: int) -> WOW64_CONTEXT | None:
    th = k32.OpenThread(THREAD_ALL_ACCESS, False, tid)
    if not th:
        return None
    try:
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = CONTEXT_FULL | CONTEXT_DEBUG_REGISTERS
        if not k32.Wow64GetThreadContext(th, ctypes.byref(ctx)):
            return None
        ctx.Dr6 = 0
        k32.Wow64SetThreadContext(th, ctypes.byref(ctx))
        return ctx
    finally:
        k32.CloseHandle(th)


def find_main_hwnd(pid: int) -> int:
    found = ctypes.c_void_p(0)
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            found.value = int(hwnd)
            return False
        return True
    u32.EnumWindows(cb, 0)
    return int(found.value or 0)


def trigger(pid: int, delay: float, log_path: Path):
    time.sleep(delay)
    hwnd = find_main_hwnd(pid)
    lines = [f"R59_TRIGGER_HWND=0x{hwnd:08X}"]
    if not hwnd:
        lines.append("R59_TRIGGER=FAIL_NO_HWND")
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    # Clear again immediately before the measured analysis.
    rc0 = u32.PostMessageW(hwnd, WM_COMMAND, CLEAR_ANALYZE_XG210, 0)
    time.sleep(0.5)
    rc1 = u32.PostMessageW(hwnd, WM_COMMAND, ANALYZE_POSITION_XG210, 0)
    lines += [
        f"R59_CLEAR_POST={int(bool(rc0))} CMD={CLEAR_ANALYZE_XG210}",
        f"R59_ANALYZE_POST={int(bool(rc1))} CMD={ANALYZE_POSITION_XG210}",
    ]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--xg-exe", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=55.0)
    ap.add_argument("--max-hits", type=int, default=24)
    a = ap.parse_args()
    a.outdir.mkdir(parents=True, exist_ok=True)

    h = k32.OpenProcess(PROCESS_ALL_ACCESS, False, a.pid)
    if not h:
        raise OSError(ctypes.get_last_error(), "OpenProcess")

    summary = [f"R59_PID={a.pid}"]
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.skipdata = True
    try:
        if rpm(h, 0x400000, 2) != b"MZ":
            raise RuntimeError("R59 XG image-base contract failed")
        model_path = find_model_file(a.xg_exe)
        model = model_path.read_bytes()
        summary += [f"R59_MODEL_PATH={model_path}", f"R59_MODEL_SIZE={len(model)}"]
        model_lines = ["tensor\tfloat_offset\tfile_offset\tf0\tf1\tf2\tf3\tf4\tf5\tsighex"]
        for ti, foff in enumerate(TENSOR_FLOAT_OFFSETS):
            off = 12 + 4 * foff
            if off + SIGNATURE_BYTES > len(model):
                continue
            fs = struct.unpack_from("<6f", model, off)
            model_lines.append(
                f"{ti}\t{foff}\t{off}\t" + "\t".join(f"{v:.9g}" for v in fs) + "\t" + model[off:off + SIGNATURE_BYTES].hex()
            )
        (a.outdir / "r59-model-signatures.tsv").write_text("\n".join(model_lines) + "\n", encoding="utf-8")

        matches = scan_signatures(h, model)
        summary.append(f"R59_MODEL_SIGNATURE_MATCHES={len(matches)}")
        match_lines = ["tensor\tfile_offset\taddress\tregion_base\tregion_size\tprotect\ttype"]
        for m in matches:
            match_lines.append(
                f"{m.tensor}\t{m.file_offset}\t0x{m.address:08X}\t0x{m.region_base:08X}\t0x{m.region_size:X}\t0x{m.protect:X}\t0x{m.mem_type:X}"
            )
        (a.outdir / "r59-memory-matches.tsv").write_text("\n".join(match_lines) + "\n", encoding="utf-8")

        watches = choose_watch_addresses(matches)
        if not watches:
            summary.append("R59_NETWORK_WEIGHT_LOCATE=FAIL")
            (a.outdir / "r59-summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
            print("\n".join(summary))
            return 3

        addresses = [m.address for m in watches]
        for i, m in enumerate(watches):
            summary.append(f"R59_DR{i}=0x{m.address:08X} tensor={m.tensor} type=0x{m.mem_type:X}")
        summary.append("R59_NETWORK_WEIGHT_LOCATE=PASS")

        if not k32.DebugActiveProcess(a.pid):
            raise OSError(ctypes.get_last_error(), "DebugActiveProcess")
        k32.DebugSetProcessKillOnExit(False)
        trigger_log = a.outdir / "r59-trigger.txt"
        threading.Thread(target=trigger, args=(a.pid, 4.0, trigger_log), daemon=True).start()

        deadline = time.time() + a.seconds
        hits = []
        armed_tids = set()
        code_dumps = {}
        raw = ctypes.create_string_buffer(256)
        while time.time() < deadline and len(hits) < a.max_hits:
            if not k32.WaitForDebugEvent(raw, 1000):
                continue
            code, pid, tid = struct.unpack_from("<III", raw.raw, 0)
            status = DBG_CONTINUE
            try:
                if pid != a.pid:
                    continue
                if code in (CREATE_PROCESS_DEBUG_EVENT, CREATE_THREAD_DEBUG_EVENT):
                    if set_hw_watchpoints(tid, addresses):
                        armed_tids.add(tid)
                elif code == EXCEPTION_DEBUG_EVENT:
                    exc = struct.unpack_from("<I", raw.raw, 12)[0]
                    if exc == EXCEPTION_SINGLE_STEP:
                        ctx = clear_dr6_and_get_context(tid)
                        if ctx is not None:
                            eip = int(ctx.Eip)
                            rec = {
                                "index": len(hits), "tid": tid, "eip": eip,
                                "eax": int(ctx.Eax), "ebx": int(ctx.Ebx), "ecx": int(ctx.Ecx),
                                "edx": int(ctx.Edx), "esi": int(ctx.Esi), "edi": int(ctx.Edi),
                                "ebp": int(ctx.Ebp), "esp": int(ctx.Esp),
                            }
                            hits.append(rec)
                            if eip not in code_dumps:
                                start = max(0x400000, eip - 96)
                                blob = rpm(h, start, 256)
                                lines = [
                                    f"0x{i.address:08X}\t{i.bytes.hex():<24}\t{i.mnemonic:<9}\t{i.op_str}"
                                    for i in md.disasm(blob, start)
                                ]
                                code_dumps[eip] = "\n".join(lines) + "\n"
                    elif exc == EXCEPTION_BREAKPOINT:
                        # Debugger attach breakpoint; normal and not evidence.
                        pass
            finally:
                k32.ContinueDebugEvent(pid, tid, status)

        for eip, text in code_dumps.items():
            (a.outdir / f"r59-code-around-{eip:08X}.txt").write_text(text, encoding="utf-8")

        hit_lines = ["index\ttid\teip\teax\tebx\tecx\tedx\tesi\tedi\tebp\tesp"]
        for r in hits:
            hit_lines.append(
                f"{r['index']}\t{r['tid']}\t0x{r['eip']:08X}\t0x{r['eax']:08X}\t0x{r['ebx']:08X}\t"
                f"0x{r['ecx']:08X}\t0x{r['edx']:08X}\t0x{r['esi']:08X}\t0x{r['edi']:08X}\t0x{r['ebp']:08X}\t0x{r['esp']:08X}"
            )
        (a.outdir / "r59-watch-hits.tsv").write_text("\n".join(hit_lines) + "\n", encoding="utf-8")
        summary.append(f"R59_ARMED_THREAD_COUNT={len(armed_tids)}")
        summary.append(f"R59_WEIGHT_READ_HITS={len(hits)}")
        summary.append(f"R59_UNIQUE_EIP_COUNT={len(code_dumps)}")
        if hits:
            summary.append("R59_NETWORK_FORWARD_ANCHOR=PASS")
        else:
            summary.append("R59_NETWORK_FORWARD_ANCHOR=NO_HIT")
        (a.outdir / "r59-summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
        print("\n".join(summary))
        return 0 if hits else 2
    finally:
        try:
            k32.DebugActiveProcessStop(a.pid)
        except Exception:
            pass
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
