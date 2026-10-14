# Frozen prospective bundle

`bundle/frozen-2026-10-13.tar.gz` is a deterministic content bundle of the five frozen models
(engine, C3, C1, A, A+odds) at local tag `frozen-2026-10-13`. The tag itself is not pushed: the
bundle carries the content, and `fpl_dof.prospective.bundle.verify_bundle` checks every file and
model config against `bundle/manifest.json` (the harness's own manifest, byte-identical) in place of
verify.py's git-HEAD check.

- `frozen/`: `git archive` of the tag (pipeline/src, pipeline/pyproject.toml, backtest, config) plus
  the derived `backtest/fdcouk/odds_team_fixtures.parquet` and `backtest/fplcache/index.csv`.
- `harness/`: decide.py, score.py, verify.py, freeze.py, manifest.json, prospective/*.py.

Raw football-data.co.uk CSVs (E0 2023/24–2025/26) are **not** redistributed: CI downloads them and
accepts them only if their sha256 matches the manifest. Changing anything in the bundle is a new
freeze, not an edit.

Approved harness-only fixes are applied with `prospective/refreeze.py`. The patched files live in `prospective/harness_patches/`, and each fix is logged in `CHANGELOG.md` and in the `refreezes` entries of `manifest.json`. The script refuses to run if any model's config or model files would change.
