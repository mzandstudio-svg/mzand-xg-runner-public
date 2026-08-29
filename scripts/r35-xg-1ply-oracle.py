#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import ctypes
import os
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


def configure_exact_1ply(auto: XGAutomator) -> None:
    """
    Open XG's analysis-level dialog through the authoritative
    SET_ANALYZE_LEVEL WM_COMMAND path, select the built-in "1-ply"
    entry by live ComboBox text, verify the selected entry, and commit.
    """
    import ctypes

    WM_GETTEXT = 0x000D
    CB_GETCURSEL = 0x0147
    CB_GETLBTEXTLEN = 0x0149
    CB_GETLBTEXT = 0x0148

    auto.analysis_level = "1-ply"

    print(
        f"R50E_SET_ANALYZE_LEVEL_CMD={auto.cmd.SET_ANALYZE_LEVEL} "
        f"profile={auto.cmd.version}"
    )

    auto.send_command(auto.cmd.SET_ANALYZE_LEVEL)

    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(auto._hwnd, ctypes.byref(pid))
    xg_pid = pid.value

    dlg = 0
    deadline = time.time() + 10.0

    while time.time() < deadline:
        try:
            candidate = auto._find_xg_dialog(
                xg_pid, auto._hwnd, skip=set(auto._skip_hwnds)
            )
        except Exception:
            candidate = 0

        if candidate:
            try:
                combos = auto._enum_combo_boxes(candidate)
            except Exception:
                combos = []

            if combos:
                dlg = candidate
                break

        time.sleep(0.25)

    if not dlg:
        raise RuntimeError(
            "R50E analysis-level dialog with TComboBox not found"
        )

    auto._set_analysis_level(dlg, "1-ply")

    combos = auto._enum_combo_boxes(dlg)
    if not combos:
        raise RuntimeError("R50E no analysis-level ComboBox after selection")

    verified = 0

    for i, combo in enumerate(combos):
        idx = user32.SendMessageW(combo, CB_GETCURSEL, 0, 0)
        if idx < 0:
            raise RuntimeError(
                f"R50E combo {i} has no selected analysis level"
            )

        n = user32.SendMessageW(combo, CB_GETLBTEXTLEN, idx, 0)
        if n < 0:
            raise RuntimeError(
                f"R50E failed reading selected level from combo {i}"
            )

        buf = ctypes.create_unicode_buffer(n + 1)
        user32.SendMessageW(
            combo, CB_GETLBTEXT, idx, ctypes.addressof(buf)
        )

        raw = buf.value
        display = raw.split(":", 1)[0].strip()

        print(
            f"R50E_LEVEL_VERIFY combo={i} "
            f"index={idx} display={display!r}"
        )

        if display.lower() != "1-ply":
            raise RuntimeError(
                f"R50E expected 1-ply, got {display!r}"
            )

        verified += 1

    # Commit dialog using the already-proven helper behavior.
    class _HwndWrap:
        def __init__(self, h):
            self.handle = h

    auto._click_button(_HwndWrap(dlg), ["OK", "Ok"])
    time.sleep(0.8)

    print(
        f"R50E_EXACT_1PLY_CONFIGURED=YES combos={verified}"
    )


def analyze_cube_exact(auto: XGAutomator) -> None:
    """
    Trigger XG cube analysis through the authoritative WM_COMMAND path.

    Do not rely on Ctrl+1 accelerator translation in the hidden/headless
    window: posted key messages can reach the VCL window without producing
    the menu command.  ANALYZE_DOUBLE is taken from the detected XG command
    profile (2.10 => 265).
    """
    print(
        f"R50D_ANALYZE_DOUBLE_CMD={auto.cmd.ANALYZE_DOUBLE} "
        f"profile={auto.cmd.version}"
    )

    auto.send_command(auto.cmd.ANALYZE_DOUBLE)

    # Give the evaluator time to create/update the analyzed CubeEntry.
    # Cube 1-ply evaluation is fast, but the runner/XG GUI state update is
    # asynchronous.
    deadline = time.time() + 12.0

    while time.time() < deadline:
        try:
            auto._dismiss_unexpected_dialogs(accept=True)
        except Exception:
            pass
        time.sleep(0.5)

    print("R50D_ANALYZE_DOUBLE_SETTLED=YES")


def _recent_xgp_candidates(start_time: float, wanted: Path) -> list[Path]:
    roots = []

    for root in (
        Path.cwd(),
        Path.home(),
        Path(os.environ.get("USERPROFILE", "")),
        Path(os.environ.get("TEMP", "")),
        Path(os.environ.get("LOCALAPPDATA", "")),
        Path(os.environ.get("APPDATA", "")),
    ):
        try:
            root = root.resolve()
        except Exception:
            continue
        if not str(root) or not root.exists():
            continue
        if root not in roots:
            roots.append(root)

    found = {}
    for root in roots:
        try:
            for q in root.rglob("*.xgp"):
                try:
                    st = q.stat()
                except OSError:
                    continue
                if st.st_size <= 0:
                    continue
                if st.st_mtime < start_time - 2.0:
                    continue
                try:
                    rq = q.resolve()
                except Exception:
                    rq = q
                if rq == wanted:
                    continue
                found[str(rq).lower()] = (st.st_mtime, rq)
        except (OSError, PermissionError):
            pass

    return [
        q for _, q in
        sorted(found.values(), key=lambda x: x[0], reverse=True)
    ]


def export_xgp(auto: XGAutomator, out: Path) -> None:
    import shutil

    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.exists():
        out.unlink()

    # XG headless ignores the requested basename and commonly writes
    # Position.xgp / Position 2.xgp in the target directory.  Leaving
    # those behind causes Confirm Save As on the next oracle row.
    removed = 0
    for q in out.parent.glob("Position*.xgp"):
        try:
            rq = q.resolve()
            if rq != out:
                q.unlink()
                removed += 1
        except OSError:
            pass

    print(f"R50E_FALLBACK_CLEANUP removed={removed}")

    started = time.time()

    auto._headless_file_operation(out, auto.cmd.EXPORT_POS_XGP, "save")
    time.sleep(1.0)
    auto._wait_for_dialogs_cleared(max_wait=5.0)

    if out.exists() and out.stat().st_size > 0:
        print(
            f"R50C_XGP_DIRECT=YES path={out} "
            f"size={out.stat().st_size}"
        )
        return

    candidates = _recent_xgp_candidates(started, out)

    print(f"R50C_XGP_DIRECT=NO wanted={out}")
    print(f"R50C_XGP_CANDIDATES={len(candidates)}")

    for i, q in enumerate(candidates[:20]):
        try:
            st = q.stat()
            print(
                f"R50C_XGP_CANDIDATE index={i} "
                f"path={q} size={st.st_size} mtime={st.st_mtime}"
            )
        except OSError:
            pass

    if not candidates:
        raise RuntimeError(
            f"XGP export failed and no recent fallback XGP found: {out}"
        )

    src = candidates[0]

    # Require freshness attributable to this export operation.
    st = src.stat()
    if st.st_mtime < started - 2.0:
        raise RuntimeError(
            f"Fallback XGP is stale: {src}"
        )

    shutil.copy2(src, out)

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(
            f"Fallback XGP recovery failed: src={src} dst={out}"
        )

    print(
        f"R50C_XGP_RECOVERED=YES src={src} dst={out} "
        f"size={out.stat().st_size}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xg-exe", type=Path, default=None)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--xgp-dir", required=True, type=Path)
    ap.add_argument("--count", type=int, default=0)
    args = ap.parse_args()

    if args.xg_exe is None:
        env_path = os.environ.get("XG_EXE") or os.environ.get("xgexe")
        if not env_path:
            raise SystemExit("R35 oracle requires --xg-exe or XG_EXE/xgexe environment variable")
        args.xg_exe = Path(env_path)
    if not args.xg_exe.exists():
        raise SystemExit(f"XG executable not found: {args.xg_exe}")

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
    args.output = args.output.resolve()
    args.xgp_dir = args.xgp_dir.resolve()

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
                    configure_exact_1ply(auto)
                    auto.import_xgid_from_file(row["xgid"])
                    analyze_cube_exact(auto)
                    xgp = (args.xgp_dir / f"{rid}.xgp").resolve()
                    print(f"R35_XGP_ABSOLUTE={xgp}")
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
