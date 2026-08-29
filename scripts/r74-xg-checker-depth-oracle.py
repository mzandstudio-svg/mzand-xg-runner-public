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
    raise SystemExit("R74 requires Windows Python")

import pefile
from ankigammon.utils.xg_auto.automator import XGAutomator
from ankigammon.thirdparty.xgdatatools import xgimport, xgstruct

user32 = ctypes.windll.user32
WM_COMMAND = 0x0111
RT_ACCELERATOR = 9
FVIRTKEY = 0x01
FSHIFT = 0x04
FCONTROL = 0x08
FALT = 0x10

DEFAULT_XGID = "XGID=---BBBBAAA---Ac-bbccbAA-A-:1:1:-1:63:4:3:0:5:8"
LEVELS = [
    ("1-ply", 0, 1, 20),
    ("2-ply", 1, 2, 45),
    ("3-ply", 2, 3, 150),
    ("4-ply", 3, 4, 420),
]


def load_r35_helpers():
    p = Path(__file__).resolve().with_name("r35-xg-1ply-oracle.py")
    spec = importlib.util.spec_from_file_location("r35_oracle_helpers", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load R35 helper module: {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extract_move_analysis(path: Path) -> dict:
    imp = xgimport.Import(str(path))
    version = -1
    candidates = []
    for seg in imp.getfilesegment():
        if seg.type != xgimport.Import.Segment.XG_GAMEFILE:
            continue
        seg.fd.seek(0)
        while True:
            rec = xgstruct.GameFileRecord(version=version).fromstream(seg.fd)
            if rec is None:
                break
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
        raise RuntimeError("no analyzed MoveEntry/DataMoves found")
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


def accelerator_commands(exe: Path) -> dict[int, int]:
    """Recover XG Ctrl+1..4 WM_COMMAND IDs from its PE accelerator table."""
    pe = pefile.PE(str(exe), fast_load=False)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
    )
    root = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    if root is None:
        raise RuntimeError("official XG EXE has no resource directory")

    tables = []
    for typ in root.entries:
        if typ.id != RT_ACCELERATOR or not hasattr(typ, "directory"):
            continue
        for name in typ.directory.entries:
            if not hasattr(name, "directory"):
                continue
            for lang in name.directory.entries:
                data = lang.data.struct
                blob = pe.get_data(data.OffsetToData, data.Size)
                mapping: dict[int, int] = {}
                for off in range(0, len(blob) - 7, 8):
                    flags, key, cmd, _padding = struct.unpack_from("<HHHH", blob, off)
                    pure_ctrl = (
                        bool(flags & FCONTROL)
                        and not bool(flags & FALT)
                        and not bool(flags & FSHIFT)
                    )
                    if pure_ctrl and bool(flags & FVIRTKEY) and key in map(ord, "1234"):
                        mapping[key - ord("0")] = cmd
                tables.append((name.id, lang.id, mapping))

    viable = [t for t in tables if set(t[2]) == {1, 2, 3, 4}]
    if not viable:
        for rid, lid, mapping in tables:
            print(
                f"R74_ACCEL_TABLE resource={rid} lang={lid} map={mapping}",
                flush=True,
            )
        raise RuntimeError("no accelerator table contains Ctrl+1..4")

    rid, lid, mapping = viable[0]
    print(f"R74_ACCEL_TABLE_SELECTED resource={rid} lang={lid}", flush=True)
    for digit in range(1, 5):
        print(f"R74_ACCEL_CTRL{digit}_CMD={mapping[digit]}", flush=True)
    return mapping


def send_accelerator_command(hwnd: int, cmd: int, digit: int) -> None:
    # TranslateAccelerator posts WM_COMMAND with HIWORD(wParam)=1.
    wparam = (1 << 16) | (cmd & 0xFFFF)
    ok = user32.PostMessageW(hwnd, WM_COMMAND, wparam, 0)
    if not ok:
        raise RuntimeError(f"PostMessage Ctrl+{digit} command failed")
    print(
        f"R74_ACCEL_COMMAND_SENT ctrl={digit} cmd={cmd} wparam=0x{wparam:08X}",
        flush=True,
    )


def analyze_level(
    auto,
    helpers,
    xgid: str,
    label: str,
    target: int,
    digit: int,
    wait_s: int,
    cmd: int,
    out_xgp: Path,
) -> dict:
    auto.import_xgid_from_file(xgid)
    time.sleep(1.0)
    auto.send_command(auto.cmd.CLEAR_ANALYZE)
    time.sleep(0.6)

    send_accelerator_command(int(auto._hwnd), cmd, digit)
    print(f"R74_EVAL_WAIT label={label} seconds={wait_s}", flush=True)

    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            auto._dismiss_unexpected_dialogs(accept=True)
        except Exception:
            pass
        time.sleep(min(1.0, max(0.05, deadline - time.time())))

    helpers.export_xgp(auto, out_xgp)
    result = extract_move_analysis(out_xgp)
    levels = sorted({r["level"] for r in result["rows"]})

    # XG's search interval can leave lower-ranked candidates at shallower levels.
    # The requested target must nevertheless appear in the exported binary data.
    if target not in levels:
        raise RuntimeError(
            f"{label} binary levels {levels} do not contain requested {target}"
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

    commands = accelerator_commands(exe)
    helpers = load_r35_helpers()
    auto = XGAutomator(xg_path=exe, headless=True, poll_interval=0.25, timeout=60.0)
    auto.connect()
    records = []
    try:
        for label, target, digit, wait_s in LEVELS:
            out_xgp = (a.xgp_dir / f"r74-{target}-{label}.xgp").resolve()
            out_xgp.parent.mkdir(parents=True, exist_ok=True)
            result = analyze_level(
                auto,
                helpers,
                a.xgid,
                label,
                target,
                digit,
                wait_s,
                commands[digit],
                out_xgp,
            )
            levels = sorted({r["level"] for r in result["rows"]})
            best = max(result["rows"], key=lambda r: r["eval"][6])
            choice = next(
                (r for r in result["rows"] if r["slot"] == result["choice0"]),
                None,
            )
            choice_level = choice["level"] if choice is not None else -999
            print(
                f"R74_RESULT label={label} requested_level={target} "
                f"binary_levels={levels} candidates={result['n']} "
                f"choice0={result['choice0']} choice_level={choice_level} "
                f"max_slot={best['slot']} max_equity={best['eval'][6]:.9g}",
                flush=True,
            )
            for r in result["rows"]:
                records.append({
                    "requested_label": label,
                    "requested_level": target,
                    "accelerator_digit": digit,
                    "accelerator_command": commands[digit],
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

    a.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0].keys()) if records else []
    with a.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(records)

    summary = []
    for label, target, digit, _wait_s in LEVELS:
        subset = [r for r in records if r["requested_level"] == target]
        binary = sorted({int(r["binary_level"]) for r in subset})
        choice = [r for r in subset if int(r["is_choice0"]) == 1]
        choice_level = int(choice[0]["binary_level"]) if choice else -999
        summary.append(
            f"{label}\trequested={target}\tctrl={digit}\tcmd={commands[digit]}"
            f"\tbinary_levels={','.join(map(str,binary))}"
            f"\tchoice_level={choice_level}\trows={len(subset)}"
        )
    summary.append("R74_XG_CHECKER_DEPTH_ORACLE=PASS")
    sp = a.output.with_suffix(".summary.txt")
    sp.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
