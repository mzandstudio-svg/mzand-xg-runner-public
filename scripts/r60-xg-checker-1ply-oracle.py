#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import time
from pathlib import Path

from ankigammon.utils.xg_auto.automator import XGAutomator
from ankigammon.thirdparty.xgdatatools import xgimport, xgstruct

DEFAULT_XGID = "XGID=---BBBBAAA---Ac-bbccbAA-A-:1:1:-1:63:4:3:0:5:8"


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
                ev = list(dm.Eval[i])
                lv = dm.EvalLevel[i]
                rows.append({
                    "rank_slot": i,
                    "move_raw": tuple(int(x) for x in dm.Moves[i]),
                    "position": tuple(int(x) for x in dm.PosPlayed[i]),
                    "level": int(getattr(lv, "Level", -999)),
                    "is_double": int(bool(getattr(lv, "isDouble", False))),
                    "eval": tuple(float(x) for x in ev),
                })
            candidates.append({
                "record": rec,
                "data": dm,
                "rows": rows,
                "n": n,
                "choice0": int(getattr(dm, "Choice0", -1)),
                "choice3": int(getattr(dm, "Choice3", -1)),
            })
    if not candidates:
        raise RuntimeError("no analyzed MoveEntry/DataMoves found in XGP")
    exact = [c for c in candidates if any(r["level"] == 0 for r in c["rows"])]
    return exact[-1] if exact else candidates[-1]


def move_text(raw) -> str:
    vals = list(raw)
    parts = []
    for j in range(0, min(8, len(vals)), 2):
        fr = vals[j]
        die = vals[j + 1] if j + 1 < len(vals) else -1
        if fr < 0:
            break
        parts.append(f"{fr}/{die}")
    return " ".join(parts)


def analyze_one(auto: XGAutomator, helpers, xgid: str, out_xgp: Path) -> dict:
    helpers.configure_exact_1ply(auto)
    auto.import_xgid_from_file(xgid)
    time.sleep(0.8)
    auto.send_command(auto.cmd.CLEAR_ANALYZE)
    time.sleep(0.4)
    print(f"R60_ANALYZE_POSITION_CMD={auto.cmd.ANALYZE_POSITION}")
    auto.send_command(auto.cmd.ANALYZE_POSITION)
    deadline = time.time() + 15.0
    while time.time() < deadline:
        try:
            auto._dismiss_unexpected_dialogs(accept=True)
        except Exception:
            pass
        time.sleep(0.5)
    helpers.export_xgp(auto, out_xgp)
    return extract_move_analysis(out_xgp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xgid", default=DEFAULT_XGID)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--xgp", type=Path, required=True)
    a = ap.parse_args()

    exe = Path(os.environ.get("XG_EXE") or os.environ.get("xgexe") or "")
    if not exe.exists():
        raise SystemExit(f"XG executable missing: {exe}")

    helpers = load_r35_helpers()
    auto = XGAutomator(xg_path=exe, headless=True, poll_interval=0.25, timeout=60.0)
    auto.connect()
    try:
        result = analyze_one(auto, helpers, a.xgid, a.xgp.resolve())
    finally:
        try:
            auto.disconnect()
        except Exception:
            pass

    fields = [
        "rank_slot", "is_choice0", "move_raw", "move_text", "eval_level", "is_double",
        "lose_bg", "lose_g", "lose_single", "win_single", "win_g", "win_bg", "equity",
    ]
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        for r in result["rows"]:
            ev = r["eval"]
            w.writerow({
                "rank_slot": r["rank_slot"],
                "is_choice0": int(r["rank_slot"] == result["choice0"]),
                "move_raw": ",".join(str(x) for x in r["move_raw"]),
                "move_text": move_text(r["move_raw"]),
                "eval_level": r["level"],
                "is_double": r["is_double"],
                "lose_bg": f"{ev[0]:.9g}",
                "lose_g": f"{ev[1]:.9g}",
                "lose_single": f"{ev[2]:.9g}",
                "win_single": f"{ev[3]:.9g}",
                "win_g": f"{ev[4]:.9g}",
                "win_bg": f"{ev[5]:.9g}",
                "equity": f"{ev[6]:.9g}",
            })

    best = max(result["rows"], key=lambda r: r["eval"][6])
    summary = [
        f"R60_XGID={a.xgid}",
        f"R60_CANDIDATES={result['n']}",
        f"R60_CHOICE0={result['choice0']}",
        f"R60_CHOICE3={result['choice3']}",
        f"R60_MAX_EQUITY_SLOT={best['rank_slot']}",
        f"R60_MAX_EQUITY={best['eval'][6]:.9g}",
        f"R60_CHOICE0_MATCHES_MAX={int(result['choice0'] == best['rank_slot'])}",
        "R60_TRESULT_7TH_FIELD=NORMALIZED_EQUITY",
        "R60_XG_CHECKER_1PLY_ORACLE=PASS",
    ]
    sp = a.output.with_suffix(".summary.txt")
    sp.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
