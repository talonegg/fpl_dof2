# 2025/26 model history — how the checked-in artefact was built

`web/public/static/models_history_2526.json` is a **backtest**, built offline because CI cannot run
the backtest. These two scripts are the exact local steps; they use box paths and local branches
(`forge/autosubs` 3de5329 simulator, forecast caches from the backtest runs) and are not run in CI.

1. `replay_2526.py <model> <cache> <policy>` per model, with `OMP_NUM_THREADS=3` and
   `PYTHONPATH=<forge/autosubs worktree>/pipeline/src`:
   engine `baseline default`, C3 `minutes_v2 cap_b0`, C1 `vec_xg2 cap_b0`, A `comp_A cap_b0`,
   A+odds `comp_ot cap_b0`. It runs `backtest.simulate` (auto-subs + vice, deadline availability,
   hits) on 2025/26 and records captain/vice/transfer ids.
2. `build_artefact.py` assembles the JSON with `fpl_dof.publish.models_history` and validates it
   against `contracts/v1/models_history.schema.json`.

Check: engine, C3 and C1 reproduce RESULTS_autosubs.md (L1, auto-subs, 2025/26) exactly
(47.47 / 47.84 / 50.76 pts/GW); A's no-subs 2025/26 mean (51.29) matches RESULTS_round2.md.
