# MZand v27 implementation bundle

Target public repository: `mzandstudio-svg/mzand-xg-runner-public`
Target branch: `mzand-v6-gnu-rollout-engine`

Files to add:

- `scripts/mzand-afterstate-v27.py` — 72-feature Markov afterstate encoder.
- `scripts/mzand-engine-v27.py` — exhaustive legal move generation, equity+rank scoring, expectiminimax search, self-play rollout.
- `scripts/test-mzand-engine-v27.py` — rules/orientation tests.
- `scripts/train-mzand-gnu-v27.py` — GNU-only afterstate equity regressor + XGB pairwise ranker; tune-only model selection; sealed dev; full-legal/search evaluation; train/tune rollout error queue.
- `.github/workflows/gnu-equity-rank-search-v27.yml` — reconstructs the same two verified true-GNU rollout refinements used by v18 (1296 and 5184 trials), trains v27, gates provenance, validates legal generator coverage, runs a non-evidence self-play rollout smoke, and uploads measured evidence.

Hard provenance rules:

- `CLASSIFIER_USED: False`
- `DEV_USED_FOR_MODEL_SELECTION: False`
- `DEV_ROWS_MINED: 0`
- `PRISTINE_DATA_USED: False`
- `XG_LABELS_USED: False`
- self-play rollout smoke/results remain `trainingEligible: false`

Local validation completed:

- Python syntax compilation: PASS
- trainer import: PASS
- dice probability mass over 21 unordered outcomes: 1.0
- afterstate feature count: 72
- legal move unit tests: PASS (bar priority, blocked pass, higher-die rule, maximum dice use, doubles, orientation involution, terminal single/gammon/backgammon)

No claim is made that v27 improves Top-1 until GitHub Actions runs and measures sealed dev.
