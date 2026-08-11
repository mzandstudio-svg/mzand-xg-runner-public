#!/usr/bin/env python3
import importlib.util
import sys
from pathlib import Path

P=Path(__file__).with_name('mzand-engine-v27.py')
spec=importlib.util.spec_from_file_location('eng',P); eng=importlib.util.module_from_spec(spec); sys.modules['eng']=eng; spec.loader.exec_module(eng)


def board(own=None, opp=None, bar_own=0, bar_opp=0, off_own=0, off_opp=0):
    return {
        'own': list(own or [0]*24), 'opp': list(opp or [0]*24),
        'barOwn': bar_own, 'barOpp': bar_opp, 'offOwn': off_own, 'offOpp': off_opp,
    }


def test_bar_priority():
    own=[0]*24; opp=[0]*24
    own[10]=14
    b=board(own,opp,bar_own=1)
    cs=eng.generate_legal_candidates(b,[6,1])
    assert cs and all(c['moves'][0]['moveKind']=='reenter' for c in cs)
    assert all(c['moves'][0]['to'] in (19,24) for c in cs)


def test_blocked_bar_pass():
    own=[0]*24; opp=[0]*24
    own[10]=14
    opp[23]=2; opp[22]=2
    b=board(own,opp,bar_own=1)
    cs=eng.generate_legal_candidates(b,[1,2])
    assert len(cs)==1 and cs[0]['forcedPass']


def test_higher_die_rule_bearoff():
    own=[0]*24; own[0]=1
    b=board(own,[0]*24,off_own=14)
    cs=eng.generate_legal_candidates(b,[1,6])
    assert cs and all(c['usedDice']==[6] for c in cs), cs


def test_maximum_dice_two_moves():
    own=[0]*24; own[7]=1; own[5]=1
    b=board(own,[0]*24,off_own=13)
    cs=eng.generate_legal_candidates(b,[2,1])
    assert cs and max(len(c['usedDice']) for c in cs)==2
    assert all(len(c['usedDice'])==2 for c in cs)


def test_double_four_plays_when_available():
    own=[0]*24; own[7]=4
    b=board(own,[0]*24,off_own=11)
    cs=eng.generate_legal_candidates(b,[1,1])
    assert cs and all(len(c['usedDice'])==4 for c in cs)


def test_flip_involution():
    own=list(range(24)); opp=list(reversed(range(24)))
    b=board(own,opp,bar_own=2,bar_opp=3,off_own=4,off_opp=5)
    assert eng.flip_board(eng.flip_board(b))==b


def test_terminal_points():
    own=[0]*24; opp=[0]*24
    assert eng.terminal_points_for_mover(board(own,opp,off_own=15,off_opp=1))==1
    opp[10]=15
    assert eng.terminal_points_for_mover(board(own,opp,off_own=15,off_opp=0))==2
    opp=[0]*24; opp[2]=1; opp[10]=14
    assert eng.terminal_points_for_mover(board(own,opp,off_own=15,off_opp=0))==3


if __name__=='__main__':
    for name,fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS',name)
