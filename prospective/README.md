# Prospective record (harness retired)

The frozen prospective harness (engine, C3, C1, A, A+odds at tag `frozen-2026-10-13`) was
**retired on 2026-10-23** ([DL-87](../docs/decisions/DL-87.md), MOD-06). The five strategies now run
in the live pipeline from the registry, and `pipeline.yml` no longer has a `prospective` job.

What is left is the record, not the machinery:

- The harness's decisions, scores and input checks stay on the `ledger` branch as
  `prospective/gw*.tgz`. The `run` job restores the latest one read-only, so `models.json` keeps
  publishing the frozen gameweeks, the ones before its `switch_gameweek` (the last gameweek the harness
  decided, plus one). From the switch, each strategy's history is its live advice scored on the
  owner's real squad ([DL-89](../docs/decisions/DL-89.md)). The two are different quantities; the
  switch marker on the history chart is the only thing separating them.
- `PREREG_C1_vs_C3.md` is the pre-registration of the C1 versus C3 comparison, and `CHANGELOG.md`
  logs the harness-only fixes made while it ran. Both are kept as records and describe files
  (`bundle/`, `harness_patches/`, `refreeze.py`) that were deleted with the harness; recover them
  from git history at the commit before this retirement if ever needed.
