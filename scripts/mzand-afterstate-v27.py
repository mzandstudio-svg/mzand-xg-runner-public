#!/usr/bin/env python3
"""Canonical, self-contained afterstate encoding for MZand v27.

The value model sees only the board after a candidate play. It does not see move
notation, move order, or the dice that produced the afterstate. That makes the
value function suitable for MZand-generated moves and deeper search.
"""
from __future__ import annotations

from typing import Dict, Sequence
import numpy as np


def longest_prime(values: Sequence[float]) -> int:
    best = cur = 0
    for v in values:
        if v >= 2:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def board_derived(own, opp, bar_own, bar_opp, off_own, off_opp):
    own=np.asarray(own,dtype=np.float32); opp=np.asarray(opp,dtype=np.float32)
    pip_own=sum((i+1)*float(own[i]) for i in range(24))+25.0*bar_own
    pip_opp=sum((24-i)*float(opp[i]) for i in range(24))+25.0*bar_opp
    made_own=int(np.sum(own>=2)); made_opp=int(np.sum(opp>=2))
    blots_own=int(np.sum(own==1)); blots_opp=int(np.sum(opp==1))
    home_made_own=int(np.sum(own[:6]>=2)); home_made_opp=int(np.sum(opp[18:]>=2))
    home_checkers_own=float(np.sum(own[:6])); home_checkers_opp=float(np.sum(opp[18:]))
    anchors_own=int(np.sum(own[18:]>=2)); anchors_opp=int(np.sum(opp[:6]>=2))
    prime_own=longest_prime(own); prime_opp=longest_prime(opp)
    own_idx=np.where(own>0)[0]; opp_idx=np.where(opp>0)[0]
    contact=1.0 if len(own_idx) and len(opp_idx) and int(np.max(own_idx))>int(np.min(opp_idx)) else 0.0
    return np.asarray([
        pip_own/200.0,pip_opp/200.0,(pip_own-pip_opp)/200.0,
        made_own/12.0,made_opp/12.0,blots_own/15.0,blots_opp/15.0,
        home_made_own/6.0,home_made_opp/6.0,home_checkers_own/15.0,home_checkers_opp/15.0,
        anchors_own/6.0,anchors_opp/6.0,prime_own/6.0,prime_opp/6.0,
        bar_own/15.0,bar_opp/15.0,off_own/15.0,off_opp/15.0,contact,
    ],dtype=np.float32)


def afterstate_from_hint(board: Dict, hint: Dict) -> Dict:
    own=np.asarray(board['own'],dtype=np.float32).copy(); opp=np.asarray(board['opp'],dtype=np.float32).copy()
    bar_own=float(board.get('barOwn',0)); bar_opp=float(board.get('barOpp',0))
    off_own=float(board.get('offOwn',0)); off_opp=float(board.get('offOpp',0))
    for move in hint.get('moves',[]):
        kind=move.get('moveKind','point-to-point'); fr=move.get('from'); to=move.get('to'); hit=bool(move.get('isHit',False))
        if kind=='reenter':
            if bar_own>0: bar_own-=1
            if isinstance(to,(int,float)) and 1<=int(to)<=24:
                ti=int(to)-1
                if hit and opp[ti]==1: opp[ti]=0; bar_opp+=1
                own[ti]+=1
        elif kind=='bear-off':
            if isinstance(fr,(int,float)) and 1<=int(fr)<=24:
                fi=int(fr)-1
                if own[fi]>0: own[fi]-=1; off_own+=1
        else:
            if isinstance(fr,(int,float)) and isinstance(to,(int,float)):
                fi=int(fr)-1; ti=int(to)-1
                if 0<=fi<24 and own[fi]>0: own[fi]-=1
                if 0<=ti<24:
                    if hit and opp[ti]==1: opp[ti]=0; bar_opp+=1
                    own[ti]+=1
    return {
        'own':[int(round(x)) for x in own], 'opp':[int(round(x)) for x in opp],
        'barOwn':int(round(bar_own)), 'barOpp':int(round(bar_opp)),
        'offOwn':int(round(off_own)), 'offOpp':int(round(off_opp)),
    }


def afterstate_features_from_board(board: Dict) -> np.ndarray:
    own=np.asarray(board['own'],dtype=np.float32); opp=np.asarray(board['opp'],dtype=np.float32)
    bar_own=float(board.get('barOwn',0)); bar_opp=float(board.get('barOpp',0)); off_own=float(board.get('offOwn',0)); off_opp=float(board.get('offOpp',0))
    return np.concatenate([
        own/5.0,opp/5.0,
        np.asarray([bar_own/5.0,bar_opp/5.0,off_own/15.0,off_opp/15.0],dtype=np.float32),
        board_derived(own,opp,bar_own,bar_opp,off_own,off_opp),
    ]).astype(np.float32)


def afterstate_features(row: Dict, hint: Dict) -> np.ndarray:
    return afterstate_features_from_board(afterstate_from_hint(row['board'],hint))


def feature_count() -> int:
    empty={'own':[0]*24,'opp':[0]*24,'barOwn':0,'barOpp':0,'offOwn':0,'offOpp':0}
    return int(len(afterstate_features_from_board(empty)))
