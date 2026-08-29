#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import ctypes
import importlib.util
import os
import struct
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R74 VCL oracle requires Windows Python")

import pymem
import pymem.memory
from ankigammon.utils.xg_auto.automator import XGAutomator
from ankigammon.thirdparty.xgdatatools import xgimport, xgstruct

u32 = ctypes.windll.user32
WM_COMMAND = 0x0111
SW_RESTORE = 9

# Delphi TShortCut = virtual key OR modifier mask; scCtrl=$4000.
CTRL_SHORTCUT = {
    1: 0x4031,
    2: 0x4032,
    3: 0x4033,
    4: 0x4034,
}

# Proven for the XG 2.10 Delphi XE TMenuItem layout used by AnkiGammon's
# command-profile recovery.  We re-validate the object class before trusting it.
TMENUITEM_FCOMMAND = 0x54
VMT_CLASS_NAME = -56

MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE_BASE_PROTECT = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}

DEFAULT_XGID = "XGID=---BBBBAAA---Ac-bbccbAA-A-:1:1:-1:63:4:3:0:5:8"
LEVELS = [
    ("1-ply", 0, 1, 20),
    ("2-ply", 1, 2, 50),
    ("3-ply", 2, 3, 180),
    ("4-ply", 3, 4, 600),
]


def load_r35_helpers():
    p = Path(__file__).resolve().with_name("r35-xg-1ply-oracle.py")
    spec = importlib.util.spec_from_file_location("r35_oracle_helpers", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extract_move_analysis(path: Path) -> dict:
    imp = xgimport.Import(str(path))
    version = -1
    candidates = []
    records_seen = []
    for seg in imp.getfilesegment():
        if seg.type != xgimport.Import.Segment.XG_GAMEFILE:
            continue
        seg.fd.seek(0)
        while True:
            rec = xgstruct.GameFileRecord(version=version).fromstream(seg.fd)
            if rec is None:
                break
            records_seen.append(type(rec).__name__)
            if isinstance(rec, xgstruct.HeaderMatchEntry):
                version = rec.Version
                continue
            if not isinstance(rec, xgstruct.MoveEntry):
                continue
            dm = getattr(rec, "DataMoves", None)
            if dm is None:
                continue
            n = int(getattr(dm, "NMoves", 0) or getattr(rec, "NMoveEval", 0) or 0)
            if n <= 0:
                continue
            n = min(n, 32)
            rows = []
            for i in range(n):
                lv = dm.EvalLevel[i]
                ev = list(dm.Eval[i])
                rows.append({
                    "slot": i,
                    "level": int(getattr(lv, "Level", -999)),
                    "is_double": int(bool(getattr(lv, "isDouble", False))),
                    "move_raw": tuple(int(x) for x in dm.Moves[i]),
                    "eval": tuple(float(x) for x in ev),
                })
            candidates.append({
                "rows": rows,
                "n": n,
                "choice0": int(getattr(dm, "Choice0", -1)),
                "choice3": int(getattr(dm, "Choice3", -1)),
            })
    if not candidates:
        print("R74_XGP_RECORD_TYPES=" + ",".join(records_seen), flush=True)
        raise RuntimeError("no analyzed MoveEntry/DataMoves found in XGP")
    return candidates[-1]


def move_text(raw) -> str:
    vals = list(raw)
    parts = []
    for j in range(0, min(8, len(vals)), 2):
        fr = vals[j]
        to = vals[j + 1] if j + 1 < len(vals) else -1
        if fr < 0:
            break
        parts.append(f"{fr}/{to}")
    return " ".join(parts)


class XGMemoryForensic:
    def __init__(self, hwnd: int):
        pid = ctypes.wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            raise RuntimeError("cannot resolve XG PID from HWND")
        self.pm = pymem.Pymem()
        self.pm.open_process_from_id(pid.value)
        self.handle = self.pm.process_handle
        self.pid = int(pid.value)
        print(f"R74_MEMORY_ATTACH=PASS pid={self.pid}", flush=True)

    def close(self):
        try:
            self.pm.close_process()
        except Exception:
            pass

    def read(self, addr: int, size: int) -> bytes:
        return self.pm.read_bytes(int(addr), int(size))

    def u16(self, addr: int) -> int:
        return struct.unpack("<H", self.read(addr, 2))[0]

    def u32(self, addr: int) -> int:
        return struct.unpack("<I", self.read(addr, 4))[0]

    def class_name(self, obj: int) -> str | None:
        try:
            if obj <= 0 or obj & 3:
                return None
            vmt = self.u32(obj)
            if vmt < 0x10000 or vmt >= 0x80000000:
                return None
            name_ptr = self.u32(vmt + VMT_CLASS_NAME)
            if name_ptr < 0x10000 or name_ptr >= 0x80000000:
                return None
            n = self.read(name_ptr, 1)[0]
            if n <= 0 or n > 120:
                return None
            raw = self.read(name_ptr + 1, n)
            name = raw.decode("ascii", errors="strict")
            if not name.startswith("T"):
                return None
            return name
        except Exception:
            return None

    def regions(self):
        addr = 0x10000
        ceiling = 0x7FFF0000
        while addr < ceiling:
            try:
                mbi = pymem.memory.virtual_query(self.handle, addr)
            except Exception:
                addr += 0x10000
                continue
            base = int(mbi.BaseAddress)
            size = int(mbi.RegionSize)
            if size <= 0:
                addr += 0x10000
                continue
            state = int(mbi.State)
            protect = int(mbi.Protect)
            base_protect = protect & 0xFF
            if (
                state == MEM_COMMIT
                and not (protect & PAGE_GUARD)
                and base_protect != PAGE_NOACCESS
                and base_protect in READABLE_BASE_PROTECT
            ):
                yield base, size
            nxt = base + size
            addr = nxt if nxt > addr else addr + 0x10000

    def find_bytes(self, needles: dict[str, bytes]) -> dict[str, list[int]]:
        hits = {k: [] for k in needles}
        chunk_size = 1 << 20
        overlap = max(len(v) for v in needles.values()) - 1
        for base, size in self.regions():
            pos = 0
            tail = b""
            while pos < size:
                n = min(chunk_size, size - pos)
                try:
                    data = self.read(base + pos, n)
                except Exception:
                    pos += n
                    tail = b""
                    continue
                blob = tail + data
                blob_base = base + pos - len(tail)
                for key, needle in needles.items():
                    start = 0
                    while True:
                        i = blob.find(needle, start)
                        if i < 0:
                            break
                        hits[key].append(blob_base + i)
                        start = i + 1
                tail = blob[-overlap:] if overlap else b""
                pos += n
        return hits

    def find_seed_menuitem(self) -> tuple[int, int]:
        # ANALYZE_DOUBLE=265 is a known XG 2.10 profile command. Find its
        # FCommand field in memory and require the enclosing object to identify
        # itself through the Delphi VMT as TMenuItem.
        needle = struct.pack("<H", 265)
        hits = self.find_bytes({"cmd265": needle})["cmd265"]
        matches = []
        for hit in hits:
            obj = hit - TMENUITEM_FCOMMAND
            if obj > 0 and not (obj & 3) and self.class_name(obj) == "TMenuItem":
                try:
                    vmt = self.u32(obj)
                except Exception:
                    continue
                matches.append((obj, vmt))
        uniq = sorted(set(matches))
        print(
            f"R74_TMENUITEM_SEED_HITS raw={len(hits)} validated={len(uniq)}",
            flush=True,
        )
        if not uniq:
            raise RuntimeError("could not validate TMenuItem seed from command 265")
        # All TMenuItem instances should share the same VMT. Prefer the first
        # validated seed, but require the VMT vote to be unambiguous.
        vmts = {}
        for _obj, vmt in uniq:
            vmts[vmt] = vmts.get(vmt, 0) + 1
        vmt = max(vmts, key=vmts.get)
        seed = next(obj for obj, vv in uniq if vv == vmt)
        print(
            f"R74_TMENUITEM_SEED=PASS object=0x{seed:08X} vmt=0x{vmt:08X}",
            flush=True,
        )
        return seed, vmt

    def all_menuitems(self, vmt: int) -> list[int]:
        needle = struct.pack("<I", vmt)
        hits = self.find_bytes({"vmt": needle})["vmt"]
        objs = []
        for addr in hits:
            if addr & 3:
                continue
            if self.class_name(addr) != "TMenuItem":
                continue
            try:
                cmd = self.u16(addr + TMENUITEM_FCOMMAND)
            except Exception:
                continue
            if 0 < cmd < 4096:
                objs.append(addr)
        objs = sorted(set(objs))
        print(f"R74_TMENUITEM_OBJECTS={len(objs)}", flush=True)
        if len(objs) < 20:
            raise RuntimeError(
                f"implausibly small TMenuItem population: {len(objs)}"
            )
        return objs

    def shortcuts_in_blob(self, obj: int, size: int = 0x120) -> set[int]:
        try:
            b = self.read(obj, size)
        except Exception:
            return set()
        out = set()
        for digit, code in CTRL_SHORTCUT.items():
            needle = struct.pack("<H", code)
            if needle in b:
                out.add(digit)
        return out

    def action_shortcuts(self, menu_obj: int) -> set[int]:
        # If a menu item's shortcut comes from an Action, Delphi explicitly does
        # not store it in TMenuItem.FShortCut. Follow pointer-looking fields one
        # and two hops, validate target Delphi class names, and inspect only
        # Action/ActionLink objects for the same TShortCut values.
        found = set()
        frontier = [(menu_obj, 0)]
        seen = {menu_obj}
        while frontier:
            obj, depth = frontier.pop(0)
            if depth >= 2:
                continue
            try:
                blob = self.read(obj, 0xA0)
            except Exception:
                continue
            for off in range(4, len(blob) - 3, 4):
                ptr = struct.unpack_from("<I", blob, off)[0]
                if ptr in seen or ptr < 0x10000 or ptr >= 0x80000000 or ptr & 3:
                    continue
                cls = self.class_name(ptr)
                if not cls:
                    continue
                seen.add(ptr)
                if "Action" in cls:
                    digs = self.shortcuts_in_blob(ptr, 0x140)
                    if digs:
                        print(
                            f"R74_ACTION_SHORTCUT menu=0x{menu_obj:08X} "
                            f"via_off=0x{off:X} target=0x{ptr:08X} "
                            f"class={cls} digits={sorted(digs)}",
                            flush=True,
                        )
                        found.update(digs)
                    frontier.append((ptr, depth + 1))
        return found

    def discover_ply_commands(self, digits: list[int]) -> dict[int, int]:
        _seed, vmt = self.find_seed_menuitem()
        objs = self.all_menuitems(vmt)
        candidates: dict[int, list[tuple[int, int, str]]] = {d: [] for d in digits}

        for obj in objs:
            try:
                cmd = self.u16(obj + TMENUITEM_FCOMMAND)
            except Exception:
                continue
            if not (0 < cmd < 4096):
                continue

            direct = self.shortcuts_in_blob(obj)
            for digit in digits:
                if digit in direct:
                    candidates[digit].append((cmd, obj, "menu"))

            needed = [d for d in digits if not candidates[d]]
            if needed:
                via_action = self.action_shortcuts(obj)
                for digit in needed:
                    if digit in via_action:
                        candidates[digit].append((cmd, obj, "action"))

        mapping = {}
        for digit in digits:
            rows = candidates[digit]
            unique_cmds = sorted({cmd for cmd, _obj, _src in rows})
            print(
                f"R74_CTRL{digit}_VCL_CANDIDATES="
                + ";".join(
                    f"cmd={cmd},obj=0x{obj:08X},src={src}"
                    for cmd, obj, src in rows
                ),
                flush=True,
            )
            if len(unique_cmds) != 1:
                raise RuntimeError(
                    f"Ctrl+{digit} VCL command not uniquely proven: {unique_cmds}"
                )
            mapping[digit] = unique_cmds[0]
            print(
                f"R74_CTRL{digit}_VCL_COMMAND={mapping[digit]}",
                flush=True,
            )

        if len(set(mapping.values())) != len(mapping):
            raise RuntimeError(f"non-unique ply command mapping: {mapping}")
        print(f"R74_VCL_PLY_COMMAND_MAP=PASS mapping={mapping}", flush=True)
        return mapping


def send_exact_ply_command(hwnd: int, digit: int, cmd: int) -> None:
    result = u32.SendMessageW(hwnd, WM_COMMAND, cmd & 0xFFFF, 0)
    print(
        f"R74_EXACT_PLY_COMMAND_SENT digit={digit} cmd={cmd} result={int(result)}",
        flush=True,
    )


def analyze_level(auto, helpers, xgid: str, label: str, target: int,
                  digit: int, wait_s: int, cmd: int, out_xgp: Path) -> dict:
    auto.import_xgid_from_file(xgid)
    time.sleep(1.2)
    auto.send_command(auto.cmd.CLEAR_ANALYZE)
    time.sleep(0.8)

    # Ctrl+1..4 are documented by XG as direct "N ply Evaluation" actions,
    # not persistent Analyze Session level selectors. Execute the VCL command
    # recovered from the live official XG process instead of relying on keyboard
    # focus/accelerator translation in a hosted headless desktop.
    send_exact_ply_command(int(auto._hwnd), digit, cmd)
    print(f"R74_EVAL_WAIT label={label} seconds={wait_s}", flush=True)

    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            auto._dismiss_unexpected_dialogs(accept=True)
        except Exception:
            pass
        time.sleep(min(1.0, max(0.05, deadline - time.time())))

    helpers.export_xgp(auto, out_xgp)
    print(
        f"R74_EXPORTED label={label} path={out_xgp} size={out_xgp.stat().st_size}",
        flush=True,
    )
    result = extract_move_analysis(out_xgp)
    levels = sorted({r["level"] for r in result["rows"]})
    print(
        f"R74_BINARY_LEVELS label={label} levels={levels} rows={result['n']}",
        flush=True,
    )
    if target not in levels:
        raise RuntimeError(
            f"{label} requested binary level {target} absent from {levels}"
        )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xgid", default=DEFAULT_XGID)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--xgp-dir", type=Path, required=True)
    a = ap.parse_args()

    exe = Path(os.environ.get("XG_EXE") or os.environ.get("xgexe") or "")
    if not exe.exists():
        raise SystemExit(f"XG executable missing: {exe}")

    helpers = load_r35_helpers()
    auto = XGAutomator(
        xg_path=exe,
        headless=True,
        poll_interval=0.25,
        timeout=90.0,
    )
    auto.connect()
    print(f"R74_XG_PROFILE={auto.cmd.version}", flush=True)

    forensic = XGMemoryForensic(int(auto._hwnd))
    try:
        digits = sorted({digit for _label, _target, digit, _wait in LEVELS})
        commands = forensic.discover_ply_commands(digits)
    finally:
        forensic.close()

    records = []
    try:
        for label, target, digit, wait_s in LEVELS:
            out_xgp = (a.xgp_dir / f"r74-{target}-{label}.xgp").resolve()
            out_xgp.parent.mkdir(parents=True, exist_ok=True)
            result = analyze_level(
                auto, helpers, a.xgid, label, target, digit,
                wait_s, commands[digit], out_xgp,
            )
            levels = sorted({r["level"] for r in result["rows"]})
            best = max(result["rows"], key=lambda r: r["eval"][6])
            choice = next(
                (r for r in result["rows"] if r["slot"] == result["choice0"]),
                None,
            )
            choice_level = choice["level"] if choice is not None else -999
            print(
                f"R74_RESULT label={label} requested={target} "
                f"binary_levels={levels} choice0={result['choice0']} "
                f"choice_level={choice_level} max_slot={best['slot']} "
                f"max_equity={best['eval'][6]:.9g}",
                flush=True,
            )
            for r in result["rows"]:
                records.append({
                    "requested_label": label,
                    "requested_level": target,
                    "vcl_command": commands[digit],
                    "rank_slot": r["slot"],
                    "is_choice0": int(r["slot"] == result["choice0"]),
                    "binary_level": r["level"],
                    "is_double": r["is_double"],
                    "move_raw": ",".join(str(x) for x in r["move_raw"]),
                    "move_text": move_text(r["move_raw"]),
                    "equity": f"{r['eval'][6]:.9g}",
                    "lose_bg": f"{r['eval'][0]:.9g}",
                    "lose_g": f"{r['eval'][1]:.9g}",
                    "lose_single": f"{r['eval'][2]:.9g}",
                    "win_single": f"{r['eval'][3]:.9g}",
                    "win_g": f"{r['eval'][4]:.9g}",
                    "win_bg": f"{r['eval'][5]:.9g}",
                })
    finally:
        try:
            auto.disconnect()
        except Exception:
            pass

    if not records:
        raise RuntimeError("R74 produced no checker records")

    a.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0])
    with a.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(records)

    summary = []
    for label, target, digit, _ in LEVELS:
        subset = [r for r in records if r["requested_level"] == target]
        levels = sorted({int(r["binary_level"]) for r in subset})
        choice = [r for r in subset if int(r["is_choice0"]) == 1]
        choice_level = int(choice[0]["binary_level"]) if choice else -999
        summary.append(
            f"{label}\trequested={target}\tcmd={commands[digit]}"
            f"\tbinary_levels={','.join(map(str,levels))}"
            f"\tchoice_level={choice_level}\trows={len(subset)}"
        )
    summary.append("R74_XG_CHECKER_DEPTH_VCL_ORACLE=PASS")
    a.output.with_suffix(".summary.txt").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    print("\n".join(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
