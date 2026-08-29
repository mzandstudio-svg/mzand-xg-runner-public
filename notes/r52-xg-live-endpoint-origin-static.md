# R52 XG2 live-endpoint origin — static recovery

Status: proven from unpacked XG2 memory disassembly captured by R51/R52. This is reverse-engineering evidence only; BG1 production money-cube guard remains closed.

## Proven producer chain

For the money branch in `0x009DC770` (`state+0x20 == -1`):

```text
0x9DC770
  -> 0x9DBA90  builds live-cube threshold/payoff knot data
       -> 0x9DA770 evaluates mode 2 and mode 3 terminal multipliers
            -> 0x9D5C20
  -> 0x9DC690  evaluates the live endpoint by piecewise interpolation
  -> FSTP [ebp-0x08]  materializes live endpoint as float32
```

The dead endpoint is independent:

```text
copy state into temporary state
set temp+0x1c = -1.0f
copy current state+0x54 into temp+0x20
0x9D5C80(temp, board/side)
read temp+0x1c
FSTP/MOV [ebp-0x0c]  dead endpoint float32
```

The recovered blend remains:

```text
state+0x54 = eff * live + (1-eff) * dead
```

with `eff` from `0x9DAD30` stored at `[ebp-0x10]` before blending.

## `0x9DA770`: mode-2 / mode-3 source values

Calling convention at the proven money caller:

- `ECX = state*`
- `EDX = board/side argument`
- `EAX = evaluator/context`
- stack byte `[ebp+8]` controls whether copied `state+0x30` is zeroed
- output pointers at `[ebp+0x0c]` and `[ebp+0x10]`

The function copies state fields `+0x20,+0x24,+0x28,+0x2c,+0x30,+0x34,+0x3c,+0x40,+0x44,+0x48,+0x4c,+0x50` into a local evaluation state, sets local `+0x18=0`, then performs:

```text
local+0x34 = 2
0x9D5C20(...)
mode2 = float32(local+0x38), promoted/stored as qword

local+0x34 = 3
0x9D5C20(...)
mode3 = float32(local+0x38), promoted/stored as qword
```

Thus later x87 formulas consume double slots whose values originated from float32 evaluator results.

## `0x9DBA90`: exact money live-cube knots used by `0x9DC770`

The proven caller uses the early-return form (`[ebp+0x0c] != 0`) of `0x9DBA90`. Let:

```text
A = mode2
B = mode3
S = A + B
C = state+0x28          // integer cube-value field
F = state+0x30          // rule/flag field
```

The two X thresholds actually consumed by `0x9DC770` are materialized as float32:

```text
t1 = float32((B - 0.5) / (S + 0.5))
t2 = float32(1.0 - (A - 0.5) / (S + 0.5))
```

and the driver builds:

```text
X[0] = 0.0f
X[1] = t1
X[2] = t2
X[3] = 1.0f
```

The Y payoff knot array is also float32. A special numeric branch is:

```text
if ((F & 1) == 1 && C == 1)
    Y = {-1.0f, -1.0f, +1.0f, +1.0f};
else
    Y = {float32(-B*C), float32(-C), float32(+C), float32(A*C)};
```

The special branch is consistent with Jacoby-like behavior, but only the numeric condition/effect above is treated as proven here.

## `0x9DC690`: exact live-endpoint interpolation

Input `x = state+0x48` is clamped in-place to `[0,1]` before interpolation.

Helper `0x9DC630` computes one segment using x87 arithmetic and materializes the result to float32 before returning:

```text
interp(i,j) = float32(
    Y[i] + (x-X[i])/(X[j]-X[i]) * (Y[j]-Y[i])
)
```

The driver selects segments solely from numeric `state+0x2c`:

### `state+0x2c == 0`

Full three-segment path:

```text
x <= X1 : interp(X0,Y0 -> X1,Y1)
x <= X2 : interp(X1,Y1 -> X2,Y2)
else     : interp(X2,Y2 -> X3,Y3)
```

### `state+0x2c == +1`

Two-segment path:

```text
x <= X1 : interp(X0,Y0 -> X1,Y1)
else     : interp(X1,Y1 -> X3,Y3)
```

### `state+0x2c == -1`

Two-segment path:

```text
x <= X2 : interp(X0,Y0 -> X2,Y2)
else     : interp(X2,Y2 -> X3,Y3)
```

Any other numeric owner value falls through to zero in this recovered branch.

The clamp to `[0,1]` makes the sentinel third-index used by the two-segment calls unreachable in normal finite input; it is not an extra semantic segment.

## Rounding boundaries proven statically

1. `0x9DA770`: evaluator result is read as float32 and then stored to qword output.
2. `0x9DBA90`: each threshold/payoff written to caller arrays is `FSTP dword` (float32).
3. `0x9DC630`: interpolation result is `FSTP dword`, then reloaded.
4. `0x9DC770`: returned live endpoint is again `FSTP [ebp-0x08]` (float32).
5. `0x9DAD30` result is `FSTP [ebp-0x10]` (float32) before blend.
6. Final live/dead blend is `FSTP [state+0x54]` (float32).

## Still unresolved before production promotion

- dynamic confirmation tying numeric `state+0x2c` values to actor/opponent ownership on a known XG position;
- exact portable semantics of the dead endpoint path below `0x9D5C80 -> 0x6FFEF4`;
- root ND / Double-Take / Double-Pass materialization and action/response selection;
- final parity validation against XG before opening the BG1 production money guard.
