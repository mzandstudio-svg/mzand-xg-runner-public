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

Recovered numeric transform:

```text
a = helper_9D7C10(state, +1)
b = helper_9D7C10(state, -1)
M = helper_463A00(&a, 1)
eff = 0.5 + (0.72 - 0.5) * (M - 30) / 90
eff = clamp(eff, 0.5, 0.75)
return eff
```

The semantics/portable implementation of `0x9D7C10` and `0x463A00` remain the only unresolved part of the class-3 efficiency branch. R36.30 is dedicated to dumping those two helper bodies.

## Classifier override

R36.29 observed `A0D700=0` in the standard startup state, so the normal path does not force the classifier override.

## Production gate

Do not replace BG1 live-cube logic with a fitted Janowski scalar. Port only after:
1. class-3 helper semantics are recovered,
2. classifier is ported/validated,
3. the dispatcher matches the internal oracle,
4. the 68-position XG regression passes the required tolerance/action parity.
