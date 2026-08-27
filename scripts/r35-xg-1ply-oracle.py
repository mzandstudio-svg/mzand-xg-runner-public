#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import ctypes
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R35 oracle requires Windows Python")

from ankigammon.utils.xg_auto.automator import XGAutomator
from ankigammon.thirdparty.xgdatatools import xgimport, xgstruct

user32 = ctypes.windll.user32
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_CONTROL = 0x11
VK_1 = 0x31


def fget(obj, key, default=None):
    try:
        return obj.get(key, default)
    except Exception:
        return getattr(obj, key, default)


def arr7(v):
    if v is None:
        return [float("nan")] * 7
    try:
        a = list(v)
    except Exception:
        return [float("nan")] * 7
    return [float(a[i]) if i < len(a) else float("nan") for i in range(7)]


def extract_raw_cube(path: Path) -> dict:
    imp = xgimport.Import(str(path))
    version = -1
    cubes = []
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
            elif isinstance(rec, xgstruct.CubeEntry):
                doubled = fget(rec, "Doubled")
                if not doubled:
                    continue
                flag = fget(doubled, "FlagDouble", -1000)
                level = fget(doubled, "Level", None)
                cubes.append({
                    "flag": int(flag) if flag is not None else -1000,
                    "level": int(level) if level is not None else -9999,
                    "equB": float(fget(doubled, "equB", float("nan"))),
                    "equDouble": float(fget(doubled, "equDouble", float("nan"))),
                    "equDrop": float(fget(doubled, "equDrop", float("nan"))),
                    "Eval": arr7(fget(doubled, "Eval")),
                    "EvalDouble": arr7(fget(doubled, "EvalDouble")),
                    "activeP": int(fget(rec, "ActiveP", 0)),
                    "cubeB": int(fget(rec, "CubeB", 0)),
                })
    analyzed = [c for c in cubes if c["flag"] not in (-100, -1000)]
    if not analyzed:
        raise RuntimeError("no analyzed CubeEntry in XGP")
    exact = [c for c in analyzed if c["level"] == 0]
    return exact[-1] if exact else analyzed[-1]


def ctrl_1(hwnd: int) -> None:
    # Post keyboard messages to XG's own GUI thread. Delphi's accelerator
    # handling maps Ctrl+1 to the documented 1-ply Evaluation action.
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_CONTROL, 0)
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_1, 0)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_1, 0)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_CONTROL, 0)
    time.sleep(0.5)


def export_xgp(auto: XGAutomator, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    auto._headless_file_operation(out, auto.cmd.EXPORT_POS_XGP, "save")
    time.sleep(0.8)
    auto._wait_for_dialogs_cleared(max_wait=5.0)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"XGP export failed: {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xg-exe", required=True, type=Path)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--xgp-dir", required=True, type=Path)
    ap.add_argument("--count", type=int, default=0)
    args = ap.parse_args()

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if args.count:
        rows = rows[:args.count]

    fields = [
        "id","group","context","xgid","status","error","level","flag","activeP","cubeB",
        "equB","equDouble","equDrop",
        "nd_lose_bg","nd_lose_g","nd_lose_total","nd_win_total","nd_win_g","nd_win_bg","nd_eval7",
        "dt_lose_bg","dt_lose_g","dt_lose_total","dt_win_total","dt_win_g","dt_win_bg","dt_eval7",
    ]

    auto = XGAutomator(xg_path=args.xg_exe, headless=True, poll_interval=0.5, timeout=60.0)
    print("R35_CONNECT_BEGIN")
    auto.connect()
    print(f"R35_CONNECTED profile={auto.cmd.version}")

    ok = fail = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.xgp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("w", encoding="utf-8", newline="") as outf:
            w = csv.DictWriter(outf, fieldnames=fields, delimiter="\t")
            w.writeheader()
            for i, row in enumerate(rows):
                rid = row["id"]
                rec = {"id": rid, "group": row["group"], "context": row["context"], "xgid": row["xgid"], "status": "FAIL", "error": ""}
                try:
                    print(f"R35_BEGIN index={i} id={rid}")
                    auto.import_xgid_from_file(row["xgid"])
                    ctrl_1(int(auto._hwnd))
                    xgp = args.xgp_dir / f"{rid}.xgp"
                    export_xgp(auto, xgp)
                    c = extract_raw_cube(xgp)
                    rec.update(level=c["level"], flag=c["flag"], activeP=c["activeP"], cubeB=c["cubeB"], equB=c["equB"], equDouble=c["equDouble"], equDrop=c["equDrop"])
                    for k, v in zip(["nd_lose_bg","nd_lose_g","nd_lose_total","nd_win_total","nd_win_g","nd_win_bg","nd_eval7"], c["Eval"]): rec[k] = v
                    for k, v in zip(["dt_lose_bg","dt_lose_g","dt_lose_total","dt_win_total","dt_win_g","dt_win_bg","dt_eval7"], c["EvalDouble"]): rec[k] = v
                    if c["level"] != 0:
                        raise RuntimeError(f"binary Level={c['level']} expected 0")
                    rec["status"] = "PASS"
                    ok += 1
                    print(f"R35_PASS id={rid} ND={c['equB']:.9g} DT={c['equDouble']:.9g} DP={c['equDrop']:.9g}")
                except Exception as e:
                    fail += 1
                    rec["error"] = str(e).replace("\t", " ").replace("\n", " ")
                    print(f"R35_FAIL id={rid} error={rec['error']}")
                finally:
                    w.writerow(rec); outf.flush()
                    try: auto.close_match()
                    except Exception: pass
    finally:
        try: auto.disconnect()
        except Exception: pass

    print(f"R35_DONE PASS={ok} FAIL={fail}")
    return 0 if ok and fail == 0 else 2

if __name__ == "__main__":
    raise SystemExit(main())
