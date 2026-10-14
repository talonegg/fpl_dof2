import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { Models, ModelGameweek } from "../../contract/types";
import type { SeasonReplay } from "./season";
import { buildSeason } from "./season";
import { SeasonView } from "./SeasonView";

const replay: SeasonReplay = {
  contract_version: 1,
  season: "2026/27",
  kind: "replay",
  caveat: "Replay, not live.",
  frozen_tag: "frozen-2026-10-13 (79e080c)",
  models: ["champion", "engine"],
  missing_models: { a_odds: "not in the GW1-6 replay run" },
  as_of_gameweek: 2,
  gameweeks: [
    { gameweek: 1, models: { champion: { points: 40, hit_points: 0, captain: "X" }, engine: { points: 30, hit_points: 0, captain: "Y" } } },
    { gameweek: 2, models: { champion: { points: 50, hit_points: 0, captain: "X" }, engine: { points: 60, hit_points: 0, captain: "Y" } } },
  ],
};

const actual = (points: number) => ({ points, points_before_hits: points, hit_points: 0, n_autosubs: 0, vice_used: false, armband_points: 4 });
const gw = (gameweek: number, a: ModelGameweek["actual"]): ModelGameweek =>
  ({ gameweek, deadline: null, decided_at: null, availability: {}, advice: {}, actual: a }) as ModelGameweek;

const models = (gws: ModelGameweek[]): Models =>
  ({ contract_version: 1, season: "2026/27", champion: "champion", frozen: { tag: "frozen-2026-10-13", code_commit: null }, models: [], gameweeks: gws, season_to_date: [] }) as Models;

describe("buildSeason", () => {
  it("is replay only before any prospective GW is scored", () => {
    const s = buildSeason(replay, models([gw(3, null)]));
    expect(s.rows.map((r) => r.phase)).toEqual(["replay", "replay"]);
    expect(s.asOf).toEqual({ replay: 2, prospective: null });
    expect(s.totals.champion).toEqual({ replay: 90, prospective: 0, total: 90 });
  });

  it("appends scored prospective GWs after the replay and keeps a running total", () => {
    const s = buildSeason(replay, models([gw(2, { champion: actual(999) }), gw(3, { champion: actual(70), a_odds: actual(55) })]));
    expect(s.rows.map((r) => [r.gameweek, r.phase])).toEqual([
      [1, "replay"],
      [2, "replay"],
      [3, "prospective"],
    ]);
    expect(s.rows[2].cumulative.champion).toBe(160);
    expect(s.totals.champion).toEqual({ replay: 90, prospective: 70, total: 160 });
    expect(s.models).toContain("a_odds");
  });

  it("ignores models.json from another season", () => {
    const other = { ...models([gw(3, { champion: actual(70) })]), season: "2025/26" };
    expect(buildSeason(replay, other).rows).toHaveLength(2);
  });
});

describe("SeasonView", () => {
  it("labels replay vs prospective rows, and the as-of note", () => {
    render(<SeasonView replay={replay} models={models([gw(3, { champion: actual(70), engine: actual(20) })])} />);
    expect(screen.getByTestId("season-asof").textContent).toBe("As of GW3 · GW1–2 replay · GW3–3 live");
    expect(within(screen.getByTestId("season-gw-1")).getByTestId("phase-replay")).toBeTruthy();
    expect(within(screen.getByTestId("season-gw-3")).getByTestId("phase-prospective")).toBeTruthy();
    expect(screen.getByTestId("season-total-champion").textContent).toBe("160");
    const chart = screen.getByTestId("season-chart");
    expect(chart.querySelectorAll('polyline[data-phase="replay"]').length).toBe(2);
    expect(chart.querySelectorAll('polyline[data-phase="prospective"]').length).toBe(2);
  });

  it("renders nothing with no data", () => {
    const { container } = render(<SeasonView replay={null} models={null} />);
    expect(container.innerHTML).toBe("");
  });
});
