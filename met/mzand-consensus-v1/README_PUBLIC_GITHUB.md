# MZand MET Public Signed Pack V1

This package is designed for a public GitHub repository.

## What is public

- Six redistributable MET source tables, with their original copyright/permission notices preserved.
- `MZand Consensus 25-point.met`, generated only from those six tables.
- Reproducible generator, benchmark summary, SHA-256 manifests, and provenance metadata.

## What is NOT public

The user-supplied `eXtremeGammon.met` is **not included** in this public pack. It is used only as a private held-out benchmark. It does not participate in generation of the MZand consensus.

## Consensus method

For each score cell, the generator takes the midpoint between the minimum and maximum of the available redistributable reference values (after pairwise zero-sum symmetrization), which minimizes the worst absolute deviation for that cell. Cells beyond 15 points use the references that actually cover 25 points.

Target tolerance requested: <= 3.00 percentage points where reference coverage exists.

Private held-out XG benchmark maximum absolute deviation: **0.8700 percentage points**.
All benchmarked values within 3 percentage points: **YES**.

## Integrity signature

`MZAND_SIGNATURES_SHA256.txt` is a SHA-256 integrity manifest. It is not a GPG/PGP identity signature and does not transfer or replace third-party copyright.

Public repository target: `mzandstudio-svg/mzand-xg-runner-public`
