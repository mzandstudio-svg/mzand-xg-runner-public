#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("R50F requires Windows Python")

from ankigammon.utils.xg_auto.automator import XGAutomator

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149


def text_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def class_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def pid_of(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def combo_items(hwnd: int) -> list[str]:
    count = int(user32.SendMessageW(hwnd, CB_GETCOUNT, 0, 0))
    if count < 0 or count > 100:
        return []
    out: list[str] = []
    for i in range(count):
        n = int(user32.SendMessageW(hwnd, CB_GETLBTEXTLEN, i, 0))
        if n < 0 or n > 4096:
            out.append("")
            continue
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.SendMessageW(hwnd, CB_GETLBTEXT, i, ctypes.addressof(buf))
        out.append(buf.value)
    return out


def enum_children(root: int) -> list[int]:
    out: list[int] = []

    def cb(hwnd, _):
        out.append(int(hwnd))
        return True

    user32.EnumChildWindows(root, WNDENUMPROC(cb), 0)
    return out


def dump_xg_windows(xg_pid: int, main_hwnd: int) -> list[str]:
    tops: list[int] = []

    def top_cb(hwnd, _):
        if pid_of(hwnd) == xg_pid:
            tops.append(int(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(top_cb), 0)

    lines: list[str] = []
    lines.append(f"R50F_XG_PID={xg_pid}")
    lines.append(f"R50F_MAIN_HWND=0x{main_hwnd:08X}")
    lines.append(f"R50F_TOP_COUNT={len(tops)}")

    combo_total = 0
    for ti, hwnd in enumerate(tops):
        cls = class_of(hwnd)
        txt = text_of(hwnd)
        vis = int(bool(user32.IsWindowVisible(hwnd)))
        owner = int(user32.GetWindow(hwnd, 4))  # GW_OWNER
        lines.append(
            f"R50F_TOP index={ti} hwnd=0x{hwnd:08X} owner=0x{owner:08X} "
            f"visible={vis} class={cls!r} text={txt!r}"
        )
        children = enum_children(hwnd)
        lines.append(f"R50F_CHILD_COUNT top={ti} count={len(children)}")
        for ci, ch in enumerate(children):
            ccls = class_of(ch)
            ctxt = text_of(ch)
            cvis = int(bool(user32.IsWindowVisible(ch)))
            cid = int(user32.GetDlgCtrlID(ch))
            parent = int(user32.GetParent(ch))
            line = (
                f"R50F_CHILD top={ti} index={ci} hwnd=0x{ch:08X} "
                f"parent=0x{parent:08X} id={cid} visible={cvis} "
                f"class={ccls!r} text={ctxt!r}"
            )
            lines.append(line)
            if "combo" in ccls.lower():
                combo_total += 1
                sel = int(user32.SendMessageW(ch, CB_GETCURSEL, 0, 0))
                items = combo_items(ch)
                lines.append(
                    f"R50F_COMBO hwnd=0x{ch:08X} selected={sel} count={len(items)}"
                )
                for ii, item in enumerate(items):
                    lines.append(
                        f"R50F_COMBO_ITEM hwnd=0x{ch:08X} index={ii} text={item!r}"
                    )

    lines.append(f"R50F_COMBO_TOTAL={combo_total}")
    return lines


def main() -> int:
    env_path = os.environ.get("XG_EXE") or os.environ.get("xgexe")
    if not env_path:
        raise SystemExit("R50F requires XG_EXE/xgexe")
    xg = Path(env_path)

    auto = XGAutomator(xg_path=xg, headless=True, poll_interval=0.5, timeout=30.0)
    print("R50F_CONNECT_BEGIN")
    auto.connect()
    print(f"R50F_CONNECTED profile={auto.cmd.version}")

    xg_pid = pid_of(auto._hwnd)
    print(f"R50F_SET_ANALYZE_LEVEL_CMD={auto.cmd.SET_ANALYZE_LEVEL}")
    auto.send_command(auto.cmd.SET_ANALYZE_LEVEL)

    # Capture several snapshots because a VCL tool window can be created
    # asynchronously and may be hidden together with the main window.
    all_lines: list[str] = []
    for snap, delay in enumerate((0.25, 1.0, 2.0)):
        time.sleep(delay)
        all_lines.append(f"R50F_SNAPSHOT={snap} AFTER_DELAY={delay}")
        all_lines.extend(dump_xg_windows(xg_pid, auto._hwnd))

    out = Path("r50f-analysis-level-forensic.txt")
    out.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    print(out.read_text(encoding="utf-8"))

    try:
        auto._dismiss_unexpected_dialogs(accept=False)
    except Exception:
        pass
    try:
        auto.disconnect()
    except Exception:
        pass

    print("R50F_FORENSIC_CAPTURE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
