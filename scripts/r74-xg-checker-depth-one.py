#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import time
from pathlib import Path

from ankigammon.utils.xg_auto.automator import XGAutomator

p = Path(__file__).resolve().with_name("r74-xg-checker-depth-keyboard-oracle.py")
spec = importlib.util.spec_from_file_location("r74_keyboard_impl", p)
if spec is None or spec.loader is None:
    raise SystemExit(f"cannot load {p}")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

# R74 matrix runs in a fresh isolated Windows VM, so clipboard import is safe
# and avoids the flaky common-file-dialog path used by import_xgid_from_file().
# The underlying XGAutomator.import_xgid() still validates the XGID, sends the
# official IMPORT_POS_CLIPBOARD command, and waits for the position to load.
# Keep retries local to the capture harness; exported XGP EvalLevel remains the
# only authority for accepting a depth result.
def _matrix_import_xgid(self: XGAutomator, xgid: str) -> None:
    last = None
    for attempt in range(1, 4):
        try:
            print(
                f"R74_IMPORT_XGID mode=clipboard attempt={attempt}",
                flush=True,
            )
            self.import_xgid(xgid)
            print(
                f"R74_IMPORT_XGID=PASS mode=clipboard attempt={attempt}",
                flush=True,
            )
            return
        except Exception as exc:
            last = exc
            print(
                f"R74_IMPORT_XGID=RETRY attempt={attempt} error={exc}",
                flush=True,
            )
            try:
                self._dismiss_unexpected_dialogs(accept=False)
            except Exception:
                pass
            time.sleep(1.0)
    raise RuntimeError(f"R74 clipboard XGID import failed after retries: {last}")


XGAutomator.import_xgid_from_file = _matrix_import_xgid

# R74 matrix runs exactly one position in a fresh Windows VM.  The legacy
# R35 fallback recursively walks USERPROFILE/TEMP/LOCALAPPDATA/APPDATA looking
# for a misnamed XGP.  That is useful for broad forensic recovery but can make
# a one-position oracle spend minutes crawling unrelated files.  Keep the
# proven headless Save-As operation, but bound fallback discovery to the
# requested directory and current workspace and require export-time freshness.
_orig_load_helpers = mod.load_r35_helpers


def _load_helpers_bounded():
    helpers = _orig_load_helpers()

    def export_xgp_bounded(auto, out: Path) -> None:
        out = out.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()

        # XG headless commonly ignores the requested basename and writes
        # Position.xgp / Position N.xgp beside the requested destination.
        for q in out.parent.glob("Position*.xgp"):
            try:
                if q.resolve() != out:
                    q.unlink()
            except OSError:
                pass

        started = time.time()
        print(f"R74_EXPORT_BEGIN path={out}", flush=True)
        auto._headless_file_operation(out, auto.cmd.EXPORT_POS_XGP, "save")
        time.sleep(1.0)
        auto._wait_for_dialogs_cleared(max_wait=5.0)

        if out.exists() and out.stat().st_size > 0:
            print(
                f"R74_XGP_DIRECT=YES path={out} size={out.stat().st_size}",
                flush=True,
            )
            return

        seen = {}
        roots = [out.parent, Path.cwd()]
        for root in roots:
            try:
                root = root.resolve()
            except Exception:
                continue
            if not root.exists():
                continue
            for q in root.glob("*.xgp"):
                try:
                    rq = q.resolve()
                    st = rq.stat()
                except OSError:
                    continue
                if rq == out or st.st_size <= 0 or st.st_mtime < started - 2.0:
                    continue
                seen[str(rq).lower()] = (st.st_mtime, rq)

        candidates = [q for _, q in sorted(seen.values(), reverse=True)]
        print(f"R74_XGP_LOCAL_CANDIDATES={len(candidates)}", flush=True)
        for i, q in enumerate(candidates[:10]):
            st = q.stat()
            print(
                f"R74_XGP_LOCAL index={i} path={q} size={st.st_size} mtime={st.st_mtime}",
                flush=True,
            )

        if not candidates:
            raise RuntimeError(
                f"XGP export produced no fresh local file for requested {out}"
            )

        src = candidates[0]
        shutil.copy2(src, out)
        if not out.exists() or out.stat().st_size <= 0:
            raise RuntimeError(f"failed to recover XGP src={src} dst={out}")
        print(
            f"R74_XGP_RECOVERED=YES src={src} dst={out} size={out.stat().st_size}",
            flush=True,
        )

    helpers.export_xgp = export_xgp_bounded
    return helpers


mod.load_r35_helpers = _load_helpers_bounded

level = int(os.environ["R74_ONLY_LEVEL"])
rows = [r for r in mod.LEVELS if r[1] == level]
if len(rows) != 1:
    raise SystemExit(f"invalid R74_ONLY_LEVEL={level}")
mod.LEVELS = rows
print(f"R74_MATRIX_ONLY_LEVEL={level}", flush=True)
raise SystemExit(mod.main())
