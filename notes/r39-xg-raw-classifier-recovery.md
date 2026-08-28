# XG2 raw position classifier recovery

Status: standard path recovered from live unpacked XG2 memory and validated by the initial portable self-test. This classifier is the direct `0x6F9580` result consumed by the cube-efficiency dispatcher `0x9DAD30`.

## Entry and canonical board arrays

`0x6F9580` receives the 26-byte signed XG state in EAX and builds two 25-int arrays.

For valid XG states the portable mapping is:

```text
side0[d-1]  = state[d]     when state[d] > 0, d=1..25
side1[24-d] = -state[d]    when state[d] <= 0, d=0..24
```

It then calls:

```text
0x6F9C18(arrays, features)
0x6FBF1C(arrays, features)
```

## Feature extractor 0x6F9C18

For each side it computes:
- total active checker count,
- zero-based weighted pip sum `sum(i * count[i])`,
- highest occupied canonical point (`back`),
- bit mask of points containing more than one checker,
- lowest singleton index,
- highest singleton index.

The feature blocks are symmetric, 0x1c bytes apart.

## Standard base classifier 0x6FBD38

If either side has no active checker, return class 0.

For contact geometry (`back0 + back1 > 22`):
1. run the symmetric crash test on both sides; if either matches, return class 5,
2. if `back0 + back1 == 24` and both back points contain more than one checker, return class 6,
3. if `abs(pip0-pip1) >= 45`, count made points in canonical indices 19..23; if either side has at least two, return class 7, otherwise class 4,
4. otherwise return class 4.

For non-contact geometry (`back0 + back1 <= 22`):
1. if either `back > 5`, return class 3,
2. if one side has all 15 active checkers while the other has fewer than 7, return class 3,
3. compute the six-point bearoff rank for both sides,
4. if either rank exceeds 54263, return class 3,
5. if either rank exceeds 923, return class 2,
6. otherwise return class 1.

## Crash test

For each canonical side with active checker count `total`:

```text
if total <= 6: crashed
else if point0 > 1:
    if total - point0 <= 6: crashed
    if point1 > 1 and total + 1 - point0 - point1 <= 6: crashed
else:
    if total - (point1 - 1) <= 6: crashed
```

## Bearoff rank helper 0x70074C

R39 live dump proves the helper uses `A0EC74=6` points and the Pascal/combination table at `B04068`. It is the same combinatorial encoding as GNU-style `PositionBearoff`, with active checker count implied by the first six point counts.

The rank recursion `0x700708` adds `C(n-1,r)` when bit `n-1` is set.

This explains the exact observed classifier boundaries:

```text
C(12,6)-1 = 923      # all six-checker / six-point distributions
C(21,6)-1 = 54263    # all fifteen-checker / six-point distributions
```

## 0x6FBF1C override layer

`0x6FBF1C` first calls `0x6FBD38`.

The proven normal startup global is `A0D700=0`; in that state it returns the base class unchanged. The optional `A0D700=1` path can introduce classes 8 and 9 and contains a special class-6-to-4 correction. It is not used by the standard dispatcher configuration and must not be silently mixed into the standard portable path.

## Portable implementation

`scripts/r39-portable-xg-raw-classifier.py`

Initial oracle self-test covers the previously observed START/RACE/BEAR/CONTACT/MIDRACE cases. R40 performs direct XG internal cross-checks of targeted standard classes 0..7.

No BG1 production behavior has been changed by this recovery work.
