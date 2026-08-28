#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from math import comb
from typing import Sequence

@dataclass
class SideFeatures:
    total: int = 0
    pip: int = 0
    back: int = -1
    made_mask: int = 0
    bearoff_id: int = -1
    low_singleton: int = -1
    high_singleton: int = -1


def xg_state_to_arrays(board: Sequence[int]) -> tuple[list[int], list[int]]:
    if len(board) != 26:
        raise ValueError('expected 26 signed XG state bytes')
    a0 = [0] * 25
    a1 = [0] * 25
    for d, raw in enumerate(board):
        v = int(raw)
        if v > 0:
            j = d - 1
            if 0 <= j < 25:
                a0[j] = v
        else:
            j = 24 - d
            if 0 <= j < 25:
                a1[j] = -v
    return a0, a1


def side_features(a: Sequence[int]) -> SideFeatures:
    if len(a) != 25:
        raise ValueError('canonical side must contain 25 ints')
    f = SideFeatures()
    bit = 1
    for i in range(24):
        n = int(a[i])
        if n:
            f.back = i
            f.total += n
            f.pip += n * i
            if n > 1:
                f.made_mask |= bit
            else:
                f.high_singleton = i
                if f.low_singleton < 0:
                    f.low_singleton = i
        bit <<= 1
    n = int(a[24])
    if n:
        f.back = 24
        f.total += n
        f.pip += n * 24
        if n > 1:
            f.made_mask |= 0x01000000
    return f


def _position_f(bits: int, n: int, r: int) -> int:
    out = 0
    while n != r:
        if bits & (1 << (n - 1)):
            out += comb(n - 1, r)
            n -= 1
            r -= 1
        else:
            n -= 1
    return out


def position_bearoff6(a: Sequence[int]) -> int:
    if len(a) < 6:
        raise ValueError('need at least six points')
    npoints = 6
    j = npoints - 1 + sum(int(x) for x in a[:npoints])
    bits = 1 << j
    n = j + 1
    for i in range(npoints - 1):
        j -= int(a[i]) + 1
        bits |= 1 << j
    return _position_f(bits, n, npoints)


def _crashed_side(a: Sequence[int], total: int) -> bool:
    if total <= 6:
        return True
    p0 = int(a[0])
    if p0 > 1:
        if total - p0 <= 6:
            return True
        if int(a[1]) > 1 and total + 1 - p0 - int(a[1]) <= 6:
            return True
    else:
        if total - (int(a[1]) - 1) <= 6:
            return True
    return False


def classify_base_arrays(a0: Sequence[int], a1: Sequence[int]) -> int:
    f0 = side_features(a0)
    f1 = side_features(a1)

    if f0.back < 0 or f1.back < 0:
        return 0

    if f0.back + f1.back > 22:
        if _crashed_side(a0, f0.total) or _crashed_side(a1, f1.total):
            return 5
        if f0.back + f1.back == 24:
            if int(a1[f1.back]) > 1 and int(a0[f0.back]) > 1:
                return 6
        if abs(f0.pip - f1.pip) >= 45:
            made0 = sum(1 for i in range(19, 24) if int(a0[i]) > 1)
            made1 = sum(1 for i in range(19, 24) if int(a1[i]) > 1)
            return 7 if made0 >= 2 or made1 >= 2 else 4
        return 4

    if f0.back > 5 or f1.back > 5:
        return 3
    if (f0.total == 15 or f1.total == 15) and (f0.total < 7 or f1.total < 7):
        return 3

    f0.bearoff_id = position_bearoff6(a0)
    f1.bearoff_id = position_bearoff6(a1)
    if f0.bearoff_id > 54263 or f1.bearoff_id > 54263:
        return 3
    if f0.bearoff_id > 923 or f1.bearoff_id > 923:
        return 2
    return 1


def classify_raw(board: Sequence[int], override_global: int = 0) -> int:
    if override_global != 0:
        raise NotImplementedError('optional A0D700=1 override policy is not production-authorized')
    a0, a1 = xg_state_to_arrays(board)
    return classify_base_arrays(a0, a1)


def _blank() -> list[int]:
    return [0] * 26


def _targeted_oracle() -> list[tuple[str, list[int], int]]:
    cases: list[tuple[str, list[int], int]] = []
    b = _blank(); b[1] = 15
    cases.append(('C0_ONE_SIDE', b, 0))
    b = _blank(); b[1] = 6; b[24] = -6
    cases.append(('C1_SMALL_BEAROFF', b, 1))
    cases.append(('C2_FULL_BEAROFF', [0,3,3,3,3,3,0,0,0,0,0,0,0,0,0,0,0,0,0,0,-3,-3,-3,-3,-3,0], 2))
    b = _blank(); b[7] = 15; b[18] = -15
    cases.append(('C3_RACE_OUTSIDE_HOME', b, 3))
    cases.append(('C4_START', [0,2,0,0,0,0,-5,0,-3,0,0,0,5,-5,0,0,0,3,0,5,0,0,0,0,-2,0], 4))
    b = _blank(); b[13] = 6; b[12] = -15
    cases.append(('C5_CRASHED', b, 5))
    b = _blank(); b[13] = 15; b[12] = -15
    cases.append(('C6_BACK_SUM_24', b, 6))
    b = _blank(); b[20] = 7; b[24] = 8; b[22] = -15
    cases.append(('C7_DEEP_CONTACT', b, 7))
    return cases


def selftest() -> None:
    assert comb(12, 6) - 1 == 923
    assert comb(21, 6) - 1 == 54263
    cases = _targeted_oracle()
    for name, board, expected in cases:
        got = classify_raw(board)
        print(f'{name}\tgot={got}\texpected={expected}')
        if got != expected:
            raise AssertionError(f'{name}: got class {got}, expected {expected}')
    print(f'R40_PORTABLE_XG_RAW_CLASSIFIER_ALL_CLASSES=PASS cases={len(cases)}')


if __name__ == '__main__':
    selftest()
