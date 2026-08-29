#!/usr/bin/env python3
from __future__ import annotations

import os
import time
from pathlib import Path

from ankigammon.utils.xg_auto.automator import XGAutomator

# Public XGID with real dice (6-3). We only need a deterministic checker-analysis
# trigger; the R59 trace does not use the resulting equities as training data.
CHECKER_XGID = "XGID=---BBBBAAA---Ac-bbccbAA-A-:1:1:-1:63:4:3:0:5:8"


def main() -> int:
    exe = Path(os.environ.get("XG_EXE") or os.environ.get("xgexe") or "")
    if not exe.exists():
        raise SystemExit(f"XG executable missing: {exe}")

    auto = XGAutomator(xg_path=exe, headless=True, poll_interval=0.25, timeout=45.0)
    auto.connect()
    try:
        print(f"R59_XG_PROFILE={auto.cmd.version}")
        print(f"R59_CHECKER_XGID={CHECKER_XGID}")
        auto.import_xgid_from_file(CHECKER_XGID)
        time.sleep(1.0)
        # Clear any analysis inherited from an exported/imported position so the
        # subsequent ANALYZE_POSITION command must execute the evaluator again.
        auto.send_command(auto.cmd.CLEAR_ANALYZE)
        time.sleep(0.8)
        print(f"R59_CLEAR_ANALYZE_CMD={auto.cmd.CLEAR_ANALYZE}")
        print(f"R59_ANALYZE_POSITION_CMD={auto.cmd.ANALYZE_POSITION}")
        print("R59_CHECKER_POSITION_READY=PASS")
    finally:
        auto.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
