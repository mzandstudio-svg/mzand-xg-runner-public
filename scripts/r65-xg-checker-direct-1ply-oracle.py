#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import importlib.util
import sys
import time
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('R65 requires Windows')

TARGET = Path(__file__).resolve().with_name('r60-xg-checker-1ply-oracle.py')
spec = importlib.util.spec_from_file_location('r65_oracle_impl', TARGET)
if spec is None or spec.loader is None:
    raise SystemExit(f'cannot load {TARGET}')
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

u32 = ctypes.windll.user32
WM_COMMAND = 0x0111
MF_BYPOSITION = 0x0400

u32.GetMenu.argtypes = [ctypes.c_void_p]
u32.GetMenu.restype = ctypes.c_void_p
u32.GetMenuItemCount.argtypes = [ctypes.c_void_p]
u32.GetMenuItemCount.restype = ctypes.c_int
u32.GetSubMenu.argtypes = [ctypes.c_void_p, ctypes.c_int]
u32.GetSubMenu.restype = ctypes.c_void_p
u32.GetMenuItemID.argtypes = [ctypes.c_void_p, ctypes.c_int]
u32.GetMenuItemID.restype = ctypes.c_uint
u32.GetMenuStringW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint]
u32.GetMenuStringW.restype = ctypes.c_int
u32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u32.PostMessageW.restype = ctypes.c_bool


def _clean(s: str) -> str:
    return ' '.join(s.replace('&', '').replace('\t', ' ').replace('-', ' ').lower().split())


def _walk_menu(menu, path=()):
    count = u32.GetMenuItemCount(menu)
    for i in range(max(0, count)):
        buf = ctypes.create_unicode_buffer(512)
        u32.GetMenuStringW(menu, i, buf, len(buf), MF_BYPOSITION)
        text = buf.value
        sub = u32.GetSubMenu(menu, i)
        item_id = int(u32.GetMenuItemID(menu, i))
        here = path + (text,)
        yield here, item_id, int(sub or 0)
        if sub:
            yield from _walk_menu(sub, here)


def find_direct_1ply_command(hwnd: int) -> tuple[int, str]:
    menu = u32.GetMenu(hwnd)
    if not menu:
        raise RuntimeError('R65 main window has no Win32 menu')
    seen = []
    candidates = []
    for path, item_id, sub in _walk_menu(menu):
        label = path[-1] if path else ''
        norm = _clean(label)
        seen.append((path, item_id, sub, norm))
        if item_id not in (0, 0xFFFFFFFF) and '1 ply' in norm:
            score = 0
            if 'evaluation' in norm or 'evaluate' in norm:
                score += 4
            if 'analysis' in norm or 'analyze' in norm:
                score += 2
            if norm.startswith('1 ply'):
                score += 1
            candidates.append((score, item_id, ' > '.join(path), norm))
    if not candidates:
        preview = '\n'.join(f'id={iid} sub={sub} path={" > ".join(p)}' for p, iid, sub, _ in seen[:250])
        raise RuntimeError('R65 could not find a 1-ply menu command. Menu dump:\n' + preview)
    candidates.sort(reverse=True)
    score, item_id, path, norm = candidates[0]
    print(f'R65_DIRECT_1PLY_MENU_CMD={item_id} score={score} path={path!r} norm={norm!r}', flush=True)
    return item_id, path


def analyze_one_direct(auto, helpers, xgid: str, out_xgp: Path):
    auto.import_xgid_from_file(xgid)
    time.sleep(0.8)
    auto.send_command(auto.cmd.CLEAR_ANALYZE)
    time.sleep(0.5)

    cmd, _ = find_direct_1ply_command(int(auto._hwnd))
    ok = u32.PostMessageW(auto._hwnd, WM_COMMAND, cmd, 0)
    print(f'R65_DIRECT_1PLY_POST={int(bool(ok))}', flush=True)
    if not ok:
        raise RuntimeError('R65 PostMessageW direct 1-ply failed')

    deadline = time.time() + 15.0
    while time.time() < deadline:
        try:
            auto._dismiss_unexpected_dialogs(accept=True)
        except Exception:
            pass
        time.sleep(0.5)

    helpers.export_xgp(auto, out_xgp)
    result = mod.extract_move_analysis(out_xgp)
    levels = sorted({r['level'] for r in result['rows']})
    print('R65_BINARY_EVAL_LEVELS=' + ','.join(str(x) for x in levels), flush=True)
    if levels != [0]:
        raise RuntimeError(f'R65 direct 1-ply produced levels {levels}, expected [0]')
    print('R65_BINARY_EXACT_1PLY_GATE=PASS', flush=True)
    return result


mod.analyze_one = analyze_one_direct
raise SystemExit(mod.main())
