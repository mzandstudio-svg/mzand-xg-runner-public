# XG2 cube-efficiency dispatcher recovery

Status: proven from live XG2 memory dumps + internal oracle. No BG1 production change implied.

## Dispatcher

Entry: `0x009DAD30`

Observed calling convention in the recovered build:
- `EDX = state*`
- `ECX = side/context selector`
- stack byte at `[ebp+0x0c]` participates in helper flag inversion
- returns `double` in x87 ST0

## Constants

Live globals from R36.27:
- `A1262C = 0.705f`
- `A12630 = 0.85f`
- `A12634 = 0.72f`
- `A12638 = 0.5f`

Local constants:
- `9DAD20 = 90.0f`
- `9DAD24 = 0.75f`
- `9DAD28 = 0.5f`
- `9DADEC = 1.0f`

## Proven branch structure

Equivalent structure of `0x9DAD30`:

```text
if (global_A12628 != 0)
    return 1.0;

if (state[0x20] == 2 && state[0x24] == 2)
    return board_efficiency_9DABA0(state, side, !flag) * 1.0;

cls = classifier_6F9580(state);

switch (cls) {
  case 3:
    return class3_efficiency_9DAC90(state);
  case 4:
  case 5:
    return 0.705;
  case 7:
    return 0.85;
  default:
    return board_efficiency_9DABA0(state, side, !flag) * 0.705;
}
```

Therefore class 2 follows the default position-dependent branch.

## Internal-oracle validation

R36.26 direct calls to `0x6F9580` and `0x9DAD30`:

```text
START   flag=1 class=4 eff=0.704999983310699
START   flag=0 class=4 eff=0.704999983310699
RACE    flag=1 class=4 eff=0.704999983310699
RACE    flag=0 class=4 eff=0.704999983310699
BEAR    flag=1 class=2 eff=0.622058808806047
BEAR    flag=0 class=2 eff=0.622058808806047
CONTACT flag=1 class=4 eff=0.704999983310699
CONTACT flag=0 class=4 eff=0.704999983310699
MIDRACE flag=1 class=4 eff=0.704999983310699
MIDRACE flag=0 class=4 eff=0.704999983310699
```

The BEAR value is explained by the recovered board helper's `0.88235294118` branch multiplied by `0.705`, matching the oracle within float/double rounding.

## `0x9DABA0` board-efficiency helper

Dependencies:
- `0x9DAB60`: finds front-most checker geometry for positive/negative side.
- `0x9DAB20`: sums checker count for requested sign.

Recovered return set:
- `0.0`
- `0.25`
- `0.5`
- `0.75`
- `0.88235294118`
- `1.0`

The first geometry test can return `1.0` when the two checker fronts satisfy the recovered non-overlap/front relation.

For selector `side == 1`, the remaining branch is count-bucketed. With helper flag clear the count buckets are:
- 0 -> 0.0
- 1..2 -> 0.25
- 3..4 -> 0.5
- 5..6 -> 0.75
- >=7 -> 0.88235294118

With helper flag set the same thresholds are shifted by two checkers:
- <3 -> 0.0
- 3..4 -> 0.25
- 5..6 -> 0.5
- 7..8 -> 0.75
- >=9 -> 0.88235294118

For the other selector branch, checker count <2 returns `0.0`; otherwise it returns `0.88235294118`, subject to the same leading geometry test that may return `1.0`.

## Class 3 helper `0x9DAC90`

R36.30 recovered both dependencies completely.

`0x9D7C10(state, side)` computes a pip-distance metric. For `side=+1` it uses the raw 26-byte board. For `side=-1` it first mirrors the board through `0x9D7AE0`, then applies the same calculation. The calculation is:

```text
pip_metric(board) = sum(i * board[i]) for i=0..25 where board[i] > 0
```

`0x463A00(ptr, n)` is an integer maximum helper. With `n=1` and `ptr=&a`, it returns `max(a,b)` over the two adjacent int32 values.

Therefore the portable class-3 transform is exactly:

```text
P1 = pip_metric(raw_board)
P2 = pip_metric(mirror_for_opponent(raw_board))
M  = max(P1, P2)

eff = 0.5 + (0.72 - 0.5) * (M - 30) / 90
eff = clamp(eff, 0.5, 0.75)
return eff
```

No unresolved arithmetic remains in the class-3 efficiency branch.

## Classifier override

R36.29 observed `A0D700=0` in the standard startup state, so the normal path does not force the classifier override.

## Remaining production gate

The efficiency dispatcher arithmetic is now recovered. Remaining work before BG1 production promotion:
1. recover/port the final classifier semantics, including the proven class-3 promotion wrapper where applicable,
2. recover the live/dead endpoint consumption around the `0x9DBA90 -> 0x9DC770` caller chain,
3. validate the portable dispatcher against direct XG internal-oracle calls,
4. run the 68-position XG regression and require tolerance/action parity.

Do not replace BG1 live-cube logic with a fitted Janowski scalar.
