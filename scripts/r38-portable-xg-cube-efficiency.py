#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

XG_EFF_DEFAULT = float.fromhex('0x1.68f5c2p-1')  # exact float32 0.705 promoted to Python float
XG_EFF_CLASS7 = float.fromhex('0x1.b33334p-1')   # exact float32 0.85 promoted to Python float
XG_CLASS3_BASE = float.fromhex('0x1.000000p-1')  # 0.5f
XG_CLASS3_TOP = float.fromhex('0x1.800000p-1')   # 0.75f
XG_CLASS3_TARGET = float.fromhex('0x1.70a3d8p-1')# 0.72f
XG_RACE_MAX = 0.88235294118


def _require_board(board: Sequence[int]) -> None:
    if len(board) != 26:
        raise ValueError(f'XG board must contain 26 signed entries, got {len(board)}')
    for v in board:
        if v < -127 or v > 127:
            raise ValueError(f'board entry outside int8 range: {v}')


def mirror_board(board: Sequence[int]) -> list[int]:
    """Portable equivalent of XG 0x9D7AE0: reverse 26 points and negate signs."""
    _require_board(board)
    return [-int(board[25 - i]) for i in range(26)]


def pip_metric(board: Sequence[int]) -> int:
    """Portable equivalent of XG 0x9D7C10 on an already-oriented board."""
    _require_board(board)
    return sum(i * int(v) for i, v in enumerate(board) if v > 0)


def class3_efficiency(board: Sequence[int]) -> float:
    """Portable equivalent of XG 0x9DAC90."""
    p1 = pip_metric(board)
    p2 = pip_metric(mirror_board(board))
    m = max(p1, p2)
    eff = XG_CLASS3_BASE + (XG_CLASS3_TARGET - XG_CLASS3_BASE) * (m - 30) / 90.0
    return max(XG_CLASS3_BASE, min(XG_CLASS3_TOP, eff))


def _positive_front(board: Sequence[int]) -> int:
    for i in range(25, -1, -1):
        if board[i] > 0:
            return i
    return 0


def _lowest_negative_index(board: Sequence[int]) -> int:
    for i in range(26):
        if board[i] < 0:
            return i
    return 25


def _checker_count(board: Sequence[int], sign: int) -> int:
    if sign == 1:
        return sum(int(v) for v in board if v > 0)
    if sign == -1:
        return sum(-int(v) for v in board if v < 0)
    raise ValueError('sign must be +1 or -1')


def board_efficiency(board: Sequence[int], side: int, helper_flag: bool) -> float:
    """Portable equivalent of XG 0x9DABA0."""
    _require_board(board)
    if _positive_front(board) > _lowest_negative_index(board):
        return 1.0

    if side == 1:
        n = _checker_count(board, -1)
        if helper_flag:
            n -= 2
        if n <= 0:
            return 0.0
        if n <= 2:
            return 0.25
        if n <= 4:
            return 0.5
        if n <= 6:
            return 0.75
        return XG_RACE_MAX

    n = _checker_count(board, -side)
    return XG_RACE_MAX if n >= 2 else 0.0


def cube_efficiency(
    board: Sequence[int],
    raw_class: int,
    *,
    side: int = 1,
    flag: bool = False,
    global_force_one: bool = False,
    state20: int = -1,
    state24: int = -1,
) -> float:
    """Portable arithmetic equivalent of XG 0x9DAD30."""
    _require_board(board)
    if global_force_one:
        return 1.0

    helper_flag = not flag
    if state20 == 2 and state24 == 2:
        return board_efficiency(board, side, helper_flag)

    if raw_class == 3:
        return class3_efficiency(board)
    if raw_class in (4, 5):
        return XG_EFF_DEFAULT
    if raw_class == 7:
        return XG_EFF_CLASS7
    return board_efficiency(board, side, helper_flag) * XG_EFF_DEFAULT


def blend_live_dead(live_endpoint: float, dead_endpoint: float, efficiency: float) -> float:
    """Recovered caller formula at both 0x9DC8E9 and 0x9DCE97."""
    return efficiency * live_endpoint + (1.0 - efficiency) * dead_endpoint


ORACLE_CASES = [
    ('START',   [0,2,0,0,0,0,-5,0,-3,0,0,0,5,-5,0,0,0,3,0,5,0,0,0,0,-2,0], 4, 0.704999983310699),
    ('RACE',    [0,0,0,0,0,-5,-5,0,0,0,0,-5,0,0,0,0,0,5,5,5,0,0,0,0,0,0], 4, 0.704999983310699),
    ('BEAR',    [0,3,3,3,3,3,0,0,0,0,0,0,0,0,0,0,0,0,0,0,-3,-3,-3,-3,-3,0], 2, 0.622058808806047),
    ('CONTACT', [0,2,0,0,0,-2,-3,0,-2,0,0,0,5,-5,0,0,0,3,0,5,0,2,0,0,-2,0], 4, 0.704999983310699),
    ('MIDRACE', [0,0,0,0,-2,-3,-5,0,0,0,-5,0,0,0,0,5,5,3,2,0,0,0,0,0,0,0], 4, 0.704999983310699),
]


def selftest() -> None:
    tol = 3e-8
    for name, board, raw_class, expected in ORACLE_CASES:
        for flag in (False, True):
            got = cube_efficiency(board, raw_class, side=1, flag=flag)
            err = abs(got - expected)
            print(f'{name}\tflag={int(flag)}\tclass={raw_class}\tgot={got:.15g}\texpected={expected:.15g}\terr={err:.3g}')
            if err > tol:
                raise AssertionError(f'{name} mismatch: {got} vs {expected}')

    assert abs(cube_efficiency(ORACLE_CASES[0][1], 7) - XG_EFF_CLASS7) < 1e-15
    assert cube_efficiency(ORACLE_CASES[0][1], 4, global_force_one=True) == 1.0
    assert abs(blend_live_dead(0.8, 0.2, 0.75) - 0.65) < 1e-15
    print('R38_PORTABLE_XG_CUBE_EFFICIENCY_SELFTEST=PASS')


if __name__ == '__main__':
    selftest()
