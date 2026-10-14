# Frozen bundle changelog

The models frozen at `frozen-2026-10-13` (engine, C3, C1, A, A+odds) never change. These entries
record approved **harness-only** fixes. Each one is also written into `manifest.json` under
`refreezes`, and `prospective/refreeze.py` rebuilds the bundle from them deterministically.

## 2026-10-14T13:45:00+11:00 (02:45 UTC): A+odds live team join

- **Approved by:** Katryn, 2026-10-14.
- **What changed:** `harness/prospective/live_frame.py`. The live football-data.co.uk `fixtures.csv` join now resolves team names in this order: the frozen `ALIAS`, then `EXTRA_ALIAS` (Coventry → Coventry City, Hull → Hull City, Ipswich → Ipswich Town), then unique-prefix matching, as `fpl_dof.sources.fdcouk.odds.team_name_map` does. Before this, every fixture involving a promoted side was silently dropped. On the 2026/27 GW6 rows, 7 of 10 fixtures joined before the fix and 10 of 10 after; the 7 that joined before have identical values.
- **Unchanged:** every model, feature, weight and config. The `config_sha256` and `model_files_sha256` of engine, C3, C1, A and A+odds are identical to the original freeze.
- **Hashes:**

| | old | new |
|---|---|---|
| `manifest_body_sha256` | `25952fc2864c95d5102afd132ae7dfb5539a0bf0c02a8ccc5a2525036de7c2e8` | `edc07c0ed2ab60edc41a5872e1502c2b189f07435f22c59585f76232049829fa` |
| `harness/prospective/live_frame.py` | `fac8584647ad8d64f67010cd3b425be09a6c638126cbf3afa38836b42c7631f9` | `cf432ea97b0b21d9b71fd8097d312bc79de88adb36ce440b1c9f3facb52d1a3e` |
| `bundle/manifest.json` (file) | `a9078e0f8baf4b78d6d4fb903b44a94b20f8eda84b53d74d7f2e486078b8f900` | `474971094309e9bf9472a140adfe3dae59bee5fe5ffdc4786b13aafb253c4c65` |
| `bundle/frozen-2026-10-13.tar.gz` | `50b1ba38ffe8fec279bbc18114ca7a5e7c2a30257dd39d2ac091b98c9e7e0745` | `6645b491d13b1c2241f15cc3b1b076c22e01df39ee9982dacd91c57cc328459a` |

- **Side effect:** each model's `source_sha256` changes, because by construction it covers the harness file hashes. Old and new values are listed in the manifest entry.
