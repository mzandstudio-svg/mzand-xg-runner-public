# R58 — XG money Branch B static recovery

Scope: reference/static only. No BG1 production behavior is changed.

## Call contract

The second money-path call in `0x009DC770` is:

- `0x009DCD68 lea eax,[ebp-0x40]` / push => `0x9DBA90 arg4`
- `0x009DCD6C lea eax,[ebp-0x70]` / push => `arg3`
- `0x009DCD70 lea eax,[ebp-0x80]` / push => `arg2` (the four Y knots)
- `0x009DCD74 push 0` => `arg1`
- `0x009DCD76 push 0` => `arg0`
- `0x009DCD7F call 0x009DBA90`

This differs from the first money-path call at `0x009DC7E6`, which passes `arg1=1`. In `0x9DBA90`, `arg1` is tested at `0x009DBC43`; non-zero jumps to the money early return at `0x009DC605`, while zero materializes additional threshold slots before returning.

## Exact origin of caller `local[-0x34]`

For Branch B, caller `local[-0x34]` is `arg4 + 0x0c` because `arg4` points to caller `[ebp-0x40]`.

The producer is the common extra-output block in `0x9DBA90`:

```
0x009DBEB2  fld  qword ptr [ebp-0xc8]
0x009DBEB8  fadd qword ptr [ebp-0xc0]       ; S = mode2 + mode3
0x009DBEBE  fld  qword ptr [ebp-0xc0]       ; mode3
0x009DBEC4  fadd dword ptr [0x009DC614]      ; +1.0
0x009DBECA  fdivrp st(1)                     ; (mode3 + 1) / S
0x009DBECC  mov  eax,[ebp+0x18]              ; arg4
0x009DBECF  fstp dword ptr [eax+0x0c]        ; float32 materialization
```

Therefore:

`branch_b_limit = float32((mode3 + 1.0) / (mode2 + mode3))`

The existing main money thresholds remain the R53 values:

- `t1 = float32((mode3 - 0.5)/(mode2 + mode3 + 0.5))`
- `q_other = float32((mode2 - 0.5)/(mode2 + mode3 + 0.5))`
- `t2 = float32(1.0 - q_other)`

Immediately after `0x9DBA90` returns, Branch B builds X:

```
X0 = 0
X1 = caller[-0x28] = t1
X2 = caller[-0x20] = t2
if (caller[-0x34] < caller[-0x20])
    X2 = caller[-0x34]
X3 = 1
```

so the exact Branch B X2 is:

`X2 = min(t2, branch_b_limit)`

using XG's already-materialized float32 operands. The four Y knots are produced before the `arg1` split and are therefore the same recovered money Y knots used by R53.

## What this proves / does not prove

Proven statically:

- the formerly-unidentified `local[-0x34]` producer;
- its exact arithmetic and float32 store boundary;
- the exact Branch B `min` adjustment;
- Branch B can be represented without inventing a new endpoint model.

Not yet semantically renamed:

- why XG selects this second path in game-theory terms;
- numeric owner `+1/-1` actor/opponent naming;
- final root ND/DT/DP/action labels.

Production money-cube enablement remains closed.
