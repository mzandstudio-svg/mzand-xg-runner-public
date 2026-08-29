#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import ctypes
import importlib.util
import os
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R74 keyboard oracle requires Windows Python")

from ankigammon.utils.xg_auto.automator import XGAutomator
from ankigammon.thirdparty.xgdatatools import xgimport, xgstruct

u32 = ctypes.windll.user32
SW_RESTORE = 9
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11

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


def foreground(hwnd: int) -> None:
    u32.ShowWindow(hwnd, SW_RESTORE)
    u32.BringWindowToTop(hwnd)
    u32.SetForegroundWindow(hwnd)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        fg = int(u32.GetForegroundWindow() or 0)
        if fg == hwnd:
            print(f"R74_FOREGROUND=PASS hwnd=0x{hwnd:08X}", flush=True)
            return
        time.sleep(0.1)
    fg = int(u32.GetForegroundWindow() or 0)
    raise RuntimeError(
        f"could not foreground XG target=0x{hwnd:08X} actual=0x{fg:08X}"
    )


def press_ctrl_digit(hwnd: int, digit: int) -> None:
    foreground(hwnd)
    vk = ord(str(digit))
    u32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.04)
    u32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)
    u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    print(f"R74_CTRL{digit}_SENT=YES", flush=True)


def analyze_level(auto, helpers, xgid: str, label: str, target: int,
                  digit: int, wait_s: int, out_xgp: Path) -> dict:
    auto.import_xgid_from_file(xgid)
    time.sleep(1.2)
    auto.send_command(auto.cmd.CLEAR_ANALYZE)
    time.sleep(0.8)

    press_ctrl_digit(int(auto._hwnd), digit)
    print(f"R74_WAIT label={label} seconds={wait_s}", flush=True)

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
    records = []
    try:
        for label, target, digit, wait_s in LEVELS:
            out_xgp = (a.xgp_dir / f"r74-{target}-{label}.xgp").resolve()
            out_xgp.parent.mkdir(parents=True, exist_ok=True)
            result = analyze_level(
                auto, helpers, a.xgid, label, target, digit, wait_s, out_xgp
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
                    "shortcut": f"Ctrl+{digit}",
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
            f"{label}\trequested={target}\tshortcut=Ctrl+{digit}"
            f"\tbinary_levels={','.join(map(str,levels))}"
            f"\tchoice_level={choice_level}\trows={len(subset)}"
        )
    summary.append("R74_XG_CHECKER_DEPTH_KEYBOARD_ORACLE=PASS")
    a.output.with_suffix(".summary.txt").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    print("\n".join(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
