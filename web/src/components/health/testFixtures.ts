import type { Health } from "../../contract/types";

/**
 * Fixtures for the data health page (E7-S6, DL-41).
 *
 * Scoped to this component rather than added to `src/test/fixtures.ts`, as `player/testFixtures.ts`
 * already is: only this view and the shell's fetch stub read them.
 *
 * **The source labels are invented on purpose.** Nothing in `web/` may know that a particular data
 * source exists (Invariant 1, DP-01), so these are names this project does not have. A component or
 * a test that had quietly learned a real source's name fails here rather than in a season's time.
 *
 * Deliberately not all-green. One source is degraded and one was never seen, one gate failed without
 * blocking, and one run in the series never reached the optimiser — because the states this page
 * must get right are the ones that read as fine when they are wrong.
 */
export const health: Health = {
  contract_version: 1,
  generated_at: "2026-08-16T11:55:00Z",
  run: {
    run_id: "20260816T113000Z-aaaabbbb",
    git_sha: "0123456789abcdef0123456789abcdef01234567",
    git_dirty: false,
    started_at: "2026-08-16T11:30:00Z",
    finished_at: null,
    status: null,
    duration_seconds: null,
    stages: [
      {
        name: "ingest",
        status: "succeeded",
        started_at: "2026-08-16T11:30:00Z",
        finished_at: "2026-08-16T11:33:20Z",
        duration_seconds: 200,
        error: null,
      },
      {
        name: "transform",
        status: "succeeded",
        started_at: "2026-08-16T11:33:20Z",
        finished_at: "2026-08-16T11:34:05Z",
        duration_seconds: 45,
        error: null,
      },
      {
        name: "quality",
        status: "succeeded",
        started_at: "2026-08-16T11:34:05Z",
        finished_at: "2026-08-16T11:34:11Z",
        duration_seconds: 6,
        error: null,
      },
      {
        name: "optimise",
        status: "succeeded",
        started_at: "2026-08-16T11:34:11Z",
        finished_at: "2026-08-16T11:34:13Z",
        duration_seconds: 1.8,
        error: null,
      },
    ],
  },
  sources: [
    {
      source: "alpha-feed",
      status: "ok",
      detail: null,
      degraded_at_stage: null,
      observed_at: "2026-08-16T11:31:00Z",
      age_seconds: 1440,
      resources: { players: 700, fixtures: 380 },
      network_calls: 4,
      cache_hits: 1,
    },
    {
      source: "beta-feed",
      status: "degraded",
      detail: "HTTPError",
      degraded_at_stage: "ingest",
      observed_at: "2026-08-14T02:00:00Z",
      age_seconds: 208500,
      resources: {},
      network_calls: null,
      cache_hits: null,
    },
    {
      source: "gamma-feed",
      status: "unknown",
      detail: "this run recorded no activity for this source",
      degraded_at_stage: null,
      observed_at: null,
      age_seconds: null,
      resources: {},
      network_calls: null,
      cache_hits: null,
    },
  ],
  gates: {
    passed: true,
    counts: { passed: 9, failed: 1, skipped: 2 },
    blocking: [],
    results: [
      {
        gate: "player-volume",
        class: "freshness_and_volume",
        severity: "error",
        outcome: "passed",
        message: "700 players, within the expected band",
        requirement: "NFR-05",
      },
      {
        gate: "price-range",
        class: "range",
        severity: "warn",
        outcome: "failed",
        message: "2 players priced outside the plausible band",
        requirement: "NFR-07",
      },
      {
        gate: "prior-season-rows",
        class: "referential",
        severity: "info",
        outcome: "skipped",
        message: "table 'player_gameweek_prior' is not present",
        requirement: "NFR-06",
      },
    ],
  },
  metrics_history: {
    derived_from: "run-manifests",
    runs: [
      {
        run_id: "run-1",
        finished_at: "2026-08-14T11:40:00Z",
        status: "succeeded",
        duration_seconds: 260,
        solve_seconds: 1.4,
        rows_total: 7180,
        rows: { player: 700, team: 20 },
        r_squared_on_price: 0.51,
        gates_failed: 0,
      },
      {
        // A run that failed in ingest. Every downstream measurement is absent, and must draw as a
        // gap rather than as an instant solve over an empty database.
        run_id: "run-2",
        finished_at: "2026-08-15T11:38:00Z",
        status: "failed",
        duration_seconds: 41,
        solve_seconds: null,
        rows_total: null,
        rows: {},
        r_squared_on_price: null,
        gates_failed: null,
      },
      {
        run_id: "run-3",
        finished_at: "2026-08-16T11:34:20Z",
        status: "succeeded",
        duration_seconds: 262,
        solve_seconds: 1.8,
        rows_total: 7204,
        rows: { player: 702, team: 20 },
        r_squared_on_price: 0.49,
        gates_failed: 1,
      },
    ],
  },
};

/** Every source reporting, every gate passing, and nothing to warn about. */
export const healthyHealth: Health = {
  ...health,
  sources: [health.sources[0]],
  gates: { passed: true, counts: { passed: 12, failed: 0, skipped: 0 }, blocking: [], results: [] },
};

/** A blocked publication: nothing new was published and the site is serving an earlier run. */
export const blockedHealth: Health = {
  ...health,
  gates: {
    passed: false,
    counts: { passed: 8, failed: 1, skipped: 3 },
    blocking: ["player-volume"],
    results: [
      {
        gate: "player-volume",
        class: "freshness_and_volume",
        severity: "error",
        outcome: "failed",
        message: "30 players, far below the expected band of 500-800",
        requirement: "NFR-05",
      },
    ],
  },
};

/** No gate report at all — which must never render as a pass (DP-13). */
export const ungatedHealth: Health = { ...health, gates: null, metrics_history: null };
