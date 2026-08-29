#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import ctypes
import importlib.util
import os
import re
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R74 requires Windows Python")

from ankigammon.utils.xg_auto.automator import XGAutomator
from ankigammon.thirdparty.xgdatatools import xgimport, xgstruct

user32 = ctypes.windll.user32
WM_COMMAND = 0x0111
MF_BYPOSITION = 0x0400

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


def _menu_text(hmenu: int, pos: int) -> str:
    n = int(user32.GetMenuStringW(hmenu, pos, None, 0, MF_BYPOSITION))
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetMenuStringW(hmenu, pos, buf, len(buf), MF_BYPOSITION)
    return buf.value


def enumerate_menu(hwnd: int) -> list[dict]:
    root = int(user32.GetMenu(hwnd) or 0)
    if not root:
        raise RuntimeError("XG main window has no native HMENU")

    out: list[dict] = []

    def walk(hmenu: int, prefix: list[str], depth: int) -> None:
        count = int(user32.GetMenuItemCount(hmenu))
        print(
            f"R74_MENU_CONTAINER depth={depth} hmenu=0x{hmenu:X} count={count} prefix={' > '.join(prefix)!r}",
            flush=True,
        )
        for pos in range(max(0, count)):
            text = _menu_text(hmenu, pos)
            clean = text.replace("&", "").strip()
            submenu = int(user32.GetSubMenu(hmenu, pos) or 0)
            item_id = int(user32.GetMenuItemID(hmenu, pos))
            path = prefix + ([clean] if clean else [f"#{pos}"])
            row = {
                "depth": depth,
                "position": pos,
                "hmenu": hmenu,
                "path": " > ".join(path),
                "text": text,
                "clean": clean,
                "id": item_id,
                "submenu": bool(submenu),
                "submenu_handle": submenu,
            }
            out.append(row)
            print(
                "R74_MENU_ALL "
                f"depth={depth} pos={pos} hmenu=0x{hmenu:X} "
                f"id={item_id} submenu={int(bool(submenu))} "
                f"submenu_h=0x{submenu:X} raw={text!r} path={row['path']!r}",
                flush=True,
            )
            if submenu:
                walk(submenu, path, depth + 1)

    walk(root, [], 0)
    print(f"R74_MENU_ALL_COUNT={len(out)}", flush=True)
    return out


def discover_ply_commands(hwnd: int) -> dict[int, int]:
    rows = enumerate_menu(hwnd)
    mapping: dict[int, int] = {}

    for digit in range(1, 5):
        candidates = []
        for r in rows:
            if r["submenu"] or r["id"] < 0:
                continue
            s = r["clean"].lower()
            compact = re.sub(r"[^a-z0-9+]", "", s)
            ply_match = (
                f"{digit}ply" in compact
                or bool(re.search(rf"(^|\D){digit}\s*-?\s*ply(\D|$)", s))
            )
            shortcut_match = f"ctrl+{digit}" in compact
            if ply_match or shortcut_match:
                score = 0
                if ply_match:
                    score += 10
                if shortcut_match:
                    score += 20
                if "eval" in s or "analy" in s:
                    score += 5
                candidates.append((score, r))

        candidates.sort(key=lambda x: (-x[0], x[1]["path"]))
        if not candidates:
            print(f"R74_DISCOVERY_MISS digit={digit}", flush=True)
            raise RuntimeError(f"no live XG menu command found for {digit}-ply")

        best_score = candidates[0][0]
        best = [r for score, r in candidates if score == best_score]
        ids = sorted({int(r["id"]) for r in best})
        if len(ids) != 1:
            detail = [(r["id"], r["path"]) for r in best]
            raise RuntimeError(f"ambiguous {digit}-ply live menu commands: {detail}")

        mapping[digit] = ids[0]
        chosen = next(r for r in best if int(r["id"]) == ids[0])
        print(
            f"R74_LIVE_CTRL{digit}_CMD={ids[0]} path={chosen['path']!r}",
            flush=True,
        )

    if len(set(mapping.values())) != 4:
        raise RuntimeError(f"non-unique live ply command mapping: {mapping}")
    return mapping


def send_menu_command(hwnd: int, cmd: int, digit: int) -> None:
    result = user32.SendMessageW(hwnd, WM_COMMAND, cmd & 0xFFFF, 0)
    print(
        f"R74_MENU_COMMAND_SENT ctrl={digit} cmd={cmd} result={int(result)}",
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
    send_menu_command(int(auto._hwnd), cmd, digit)
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

    helpers = load_r35_helpers()
    auto = XGAutomator(xg_path=exe, headless=True, poll_interval=0.25, timeout=60.0)
    auto.connect()
    records = []
    try:
        commands = discover_ply_commands(int(auto._hwnd))
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
                    "menu_command": commands[digit],
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
            f"{label}\trequested={target}\tcmd={commands[digit]}"
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
