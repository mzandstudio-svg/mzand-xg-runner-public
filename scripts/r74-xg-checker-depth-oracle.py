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
    raise SystemExit("R74 requires Windows Python")

from ankigammon.utils.xg_auto.automator import XGAutomator
from ankigammon.thirdparty.xgdatatools import xgimport, xgstruct

user32 = ctypes.windll.user32

DEFAULT_XGID = "XGID=---BBBBAAA---Ac-bbccbAA-A-:1:1:-1:63:4:3:0:5:8"
LEVELS = [("1-ply",0),("2-ply",1),("3-ply",2),("4-ply",3)]


def load_r35_helpers():
    p = Path(__file__).resolve().with_name("r35-xg-1ply-oracle.py")
    spec = importlib.util.spec_from_file_location("r35_oracle_helpers", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load R35 helper module: {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fget(obj,key,default=None):
    try:
        return obj.get(key,default)
    except Exception:
        return getattr(obj,key,default)


def extract_move_analysis(path: Path) -> dict:
    imp=xgimport.Import(str(path))
    version=-1
    candidates=[]
    for seg in imp.getfilesegment():
        if seg.type != xgimport.Import.Segment.XG_GAMEFILE:
            continue
        seg.fd.seek(0)
        while True:
            rec=xgstruct.GameFileRecord(version=version).fromstream(seg.fd)
            if rec is None:
                break
            if isinstance(rec,xgstruct.HeaderMatchEntry):
                version=rec.Version
                continue
            if not isinstance(rec,xgstruct.MoveEntry):
                continue
            dm=getattr(rec,"DataMoves",None)
            if dm is None:
                continue
            n=int(getattr(dm,"NMoves",0) or getattr(rec,"NMoveEval",0) or 0)
            if n<=0:
                continue
            n=min(n,32)
            rows=[]
            for i in range(n):
                lv=dm.EvalLevel[i]
                ev=list(dm.Eval[i])
                rows.append({
                    "slot":i,
                    "level":int(getattr(lv,"Level",-999)),
                    "is_double":int(bool(getattr(lv,"isDouble",False))),
                    "move_raw":tuple(int(x) for x in dm.Moves[i]),
                    "eval":tuple(float(x) for x in ev),
                })
            candidates.append({
                "rows":rows,
                "n":n,
                "choice0":int(getattr(dm,"Choice0",-1)),
                "choice3":int(getattr(dm,"Choice3",-1)),
            })
    if not candidates:
        raise RuntimeError("no analyzed MoveEntry/DataMoves found")
    return candidates[-1]


def move_text(raw) -> str:
    vals=list(raw)
    parts=[]
    for j in range(0,min(8,len(vals)),2):
        fr=vals[j]
        to=vals[j+1] if j+1<len(vals) else -1
        if fr<0:
            break
        parts.append(f"{fr}/{to}")
    return " ".join(parts)


def configure_level(auto: XGAutomator,label: str) -> None:
    CB_GETCURSEL=0x0147
    CB_GETLBTEXTLEN=0x0149
    CB_GETLBTEXT=0x0148

    auto.analysis_level=label
    auto.send_command(auto.cmd.SET_ANALYZE_LEVEL)

    pid=ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(auto._hwnd,ctypes.byref(pid))
    xg_pid=pid.value
    dlg=0
    deadline=time.time()+10.0
    while time.time()<deadline:
        try:
            candidate=auto._find_xg_dialog(xg_pid,auto._hwnd,skip=set(auto._skip_hwnds))
        except Exception:
            candidate=0
        if candidate:
            try:
                combos=auto._enum_combo_boxes(candidate)
            except Exception:
                combos=[]
            if combos:
                dlg=candidate
                break
        time.sleep(0.25)
    if not dlg:
        raise RuntimeError(f"analysis-level dialog not found for {label}")

    auto._set_analysis_level(dlg,label)
    combos=auto._enum_combo_boxes(dlg)
    if not combos:
        raise RuntimeError(f"no combo after selecting {label}")

    verified=0
    for combo in combos:
        idx=user32.SendMessageW(combo,CB_GETCURSEL,0,0)
        if idx<0:
            continue
        n=user32.SendMessageW(combo,CB_GETLBTEXTLEN,idx,0)
        if n<0:
            continue
        buf=ctypes.create_unicode_buffer(n+1)
        user32.SendMessageW(combo,CB_GETLBTEXT,idx,ctypes.addressof(buf))
        display=buf.value.split(":",1)[0].strip()
        print(f"R74_LEVEL_VERIFY requested={label!r} selected={display!r}")
        if display.lower()==label.lower():
            verified+=1
    if verified==0:
        raise RuntimeError(f"failed to verify selected level {label}")

    class _HwndWrap:
        def __init__(self,h): self.handle=h
    auto._click_button(_HwndWrap(dlg),["OK","Ok"])
    time.sleep(0.8)


def analyze_level(auto,helpers,xgid: str,label: str,out_xgp: Path) -> dict:
    auto.import_xgid_from_file(xgid)
    time.sleep(0.8)
    auto.send_command(auto.cmd.CLEAR_ANALYZE)
    time.sleep(0.4)
    configure_level(auto,label)
    print(f"R74_ANALYZE_POSITION label={label} cmd={auto.cmd.ANALYZE_POSITION}")
    auto.send_command(auto.cmd.ANALYZE_POSITION)
    deadline=time.time()+45.0
    while time.time()<deadline:
        try:
            auto._dismiss_unexpected_dialogs(accept=True)
        except Exception:
            pass
        time.sleep(0.5)
    helpers.export_xgp(auto,out_xgp)
    return extract_move_analysis(out_xgp)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--xgid",default=DEFAULT_XGID)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--xgp-dir",type=Path,required=True)
    a=ap.parse_args()

    exe=Path(os.environ.get("XG_EXE") or os.environ.get("xgexe") or "")
    if not exe.exists():
        raise SystemExit(f"XG executable missing: {exe}")

    helpers=load_r35_helpers()
    auto=XGAutomator(xg_path=exe,headless=True,poll_interval=0.25,timeout=60.0)
    auto.connect()
    records=[]
    try:
        for label,target in LEVELS:
            out_xgp=(a.xgp_dir/f"r74-{target}-{label}.xgp").resolve()
            out_xgp.parent.mkdir(parents=True,exist_ok=True)
            result=analyze_level(auto,helpers,a.xgid,label,out_xgp)
            levels=sorted({r["level"] for r in result["rows"]})
            best=max(result["rows"],key=lambda r:r["eval"][6])
            print(
                f"R74_RESULT label={label} requested_level={target} "
                f"binary_levels={levels} candidates={result['n']} "
                f"choice0={result['choice0']} max_slot={best['slot']} "
                f"max_equity={best['eval'][6]:.9g}"
            )
            for r in result["rows"]:
                records.append({
                    "requested_label":label,
                    "requested_level":target,
                    "rank_slot":r["slot"],
                    "is_choice0":int(r["slot"]==result["choice0"]),
                    "binary_level":r["level"],
                    "is_double":r["is_double"],
                    "move_raw":",".join(str(x) for x in r["move_raw"]),
                    "move_text":move_text(r["move_raw"]),
                    "equity":f"{r['eval'][6]:.9g}",
                    "lose_bg":f"{r['eval'][0]:.9g}",
                    "lose_g":f"{r['eval'][1]:.9g}",
                    "lose_single":f"{r['eval'][2]:.9g}",
                    "win_single":f"{r['eval'][3]:.9g}",
                    "win_g":f"{r['eval'][4]:.9g}",
                    "win_bg":f"{r['eval'][5]:.9g}",
                })
    finally:
        try: auto.disconnect()
        except Exception: pass

    a.output.parent.mkdir(parents=True,exist_ok=True)
    fields=list(records[0].keys()) if records else []
    with a.output.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t")
        w.writeheader()
        w.writerows(records)

    summary=[]
    for label,target in LEVELS:
        subset=[r for r in records if r["requested_level"]==target]
        binary=sorted({int(r["binary_level"]) for r in subset})
        summary.append(
            f"{label}\trequested={target}\tbinary_levels={','.join(map(str,binary))}"
            f"\trows={len(subset)}"
        )
    summary.append("R74_XG_CHECKER_DEPTH_ORACLE=PASS")
    sp=a.output.with_suffix(".summary.txt")
    sp.write_text("\n".join(summary)+"\n",encoding="utf-8")
    print("\n".join(summary))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
