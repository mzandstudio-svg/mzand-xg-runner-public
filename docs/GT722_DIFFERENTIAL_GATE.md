# GT722 Differential Gate

This branch is a public clean-room/differential test harness. It does **not** commit or redistribute eXtreme Gammon binaries or data.

## XG side

GitHub Actions installs XG from the official `https://www.extremegammon.com/xg2install.exe` installer on an ephemeral Windows runner, then uses the repository's existing UI/export scripts to obtain structured analysis evidence.

## MZand/GT722 side

GT722 checker architecture under test:

1. legal full-turn move generation;
2. OpeningBook authority when a covered local record exists;
3. otherwise GNU-teacher candidate ranker + staged 2/3/selective-4-ply search;
4. GT719 A/B/C/D only for paired W/G/B, cubeless equity and Match MWC context;
5. finite-horizon 1-ply cubeful Match cube search; money auto-double remains unpromoted.

Measured local gate before this branch:

- 15 authoritative non-double opening rolls: GNU ranker 13/15, old SafeNative heuristic 4/15.
- GT722 Engine CTest: 17/17 PASS.
- Play↔Analyze final-board parity: 4/4 PASS.
- Match start cube: NO DOUBLE; finite-horizon cubeful 1-ply.

These numbers are **not** XG parity claims. The purpose of this branch is to replace internal proxies with direct XG differential evidence.

## Promotion rule

For each shared position/dice/match/cube context, record at least: Top-N moves, rank, equity/context scale, W/G/B when available, and cube action/response. Fix the first reproducible divergence in generic C++ code, add a regression, then rerun the frozen corpus. No stop/timestamp/position-specific production hacks.

The 500-game campaign will be sharded after the target-Mac GT722 build is confirmed, so the same production binary tested by the user is the MZand side of the evidence.
