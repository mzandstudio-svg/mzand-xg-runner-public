# GitHub Publication Layout

Recommended public layout:

```text
met/mzand-consensus-v1/
  README_PUBLIC_GITHUB.md
  TABLES_COPYRIGHT_AND_PUBLICATION.md
  TABLE_PROVENANCE_AND_COPYRIGHT.json
  BENCHMARK_EVIDENCE_PUBLIC.json
  MZAND_MET_BENCHMARK_SUMMARY.csv
  MZAND_SIGNATURES_SHA256.txt
  generate_mzand_consensus.py
  tables/
    MZand Consensus 25-point.met
    GnuBG 11 point.met
    Jacobs & Trice.met
    Kazaross XG2.met
    Rockwell-Kazaross.met
    Snowie.met
    Woolsey.met
```

Do not add the private `eXtremeGammon.met` to the public tree. The public benchmark evidence records only aggregate held-out comparison results; the XG values are not used to generate the MZand consensus.

No GitHub push is performed by this package itself. Publishing is a separate repository write operation.
