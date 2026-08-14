# Zand ↔ XG Cube/Match Parity Harness V1

Purpose: runtime differential testing only. These outputs are **not training labels**.

## Batch

`cases.json` contains 24 controlled contexts over one fixed checker position with dice `00` so the cube decision is the target. The matrix covers:

- money play, centered and owned cubes through 8;
- 5-point score contexts;
- 7-point normal, Crawford, and post-Crawford contexts;
- 11-point normal and Crawford contexts;
- centered cube, owned cube, and recube states.

The checker position is held fixed so score/cube/MET effects can be isolated before adding a multi-position corpus.

## Outputs

The GitHub workflow produces:

- `raw/<case>.txt`: raw XG clipboard export;
- `capture-status.jsonl`: per-case runtime status;
- `capture-summary.json`: batch capture coverage;
- `xg-oracle.jsonl` / `xg-oracle.csv`: parsed probabilities and cube equities;
- `oracle-summary.json`: parser coverage;
- `COMPARE_ZAND_LOCAL.py`: local comparator.

## Scientific rule

XG exported `Cubeful Equities` are normalized equity values. They must **not** be compared directly to a Zand Match Winning Chance field. Zand values must first be emitted/converted into the same semantic space.

The comparator uses four statuses:

- `PARITY_PROVEN`
- `CLOSE_BUT_NOT_PROVEN`
- `MISMATCH`
- `MISSING`

A matching final action alone is not sufficient for parity.

## Local compare

After generating a standardized Zand JSONL with the same `case_id` values and XG-space keys:

```bash
python3 COMPARE_ZAND_LOCAL.py \
  --xg xg-oracle.jsonl \
  --zand zand-standardized.jsonl \
  --out-dir parity-out
```

The V1 public workflow intentionally does not upload or depend on private Zand model/MET assets.
