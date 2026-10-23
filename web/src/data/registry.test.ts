import { describe, expect, it } from "vitest";
import {
  buildRegistry,
  normaliseAccuracy,
  normaliseHistory,
  normaliseModels,
  orderIds,
  resolveModel,
  seriesStyle,
} from "./registry";
import { modelsFixture, novelRegistry, strategiesFixture } from "../test/fixtures";
import type { ModelsHistory, XpAccuracy } from "../contract/types";

const registry = buildRegistry(strategiesFixture);

describe("resolveModel", () => {
  it("maps ids, legacy aliases and the harness keys to the registry id", () => {
    const cases = [["c3", "c3"], ["champion", "c3"], ["C3", "c3"], ["challenger", "c1"], ["C1", "c1"], ["A_odds", "a_odds"], ["engine", "engine"]];
    for (const [value, id] of cases) expect(resolveModel(registry, value)).toBe(id);
  });

  it("returns null for the unknown and the empty", () => {
    expect(resolveModel(registry, "nope")).toBeNull();
    expect(resolveModel(registry, "")).toBeNull();
    expect(resolveModel(registry, null)).toBeNull();
  });
});

describe("seriesStyle", () => {
  it("is assigned by registry position, never by id, and every strategy gets a distinct one", () => {
    const styles = registry.entries.map((e) => seriesStyle(registry, e.id));
    expect(new Set(styles.map((s) => s.colour)).size).toBe(5);
    expect(new Set(styles.map((s) => s.dash)).size).toBe(5);
    expect(styles[0].colour).toBe("var(--series-1)");
    const novel = buildRegistry(novelRegistry(3).registry);
    expect(seriesStyle(novel, "zeta_1")).toEqual(styles[0]);
  });

  it("styles an id the registry has never heard of", () => {
    expect(seriesStyle(registry, "mystery").colour).toMatch(/^var\(--series-[1-5]\)$/);
  });
});

describe("orderIds", () => {
  it("puts registry order first, then the unknown in the order given", () => {
    expect(orderIds(registry, ["zz", "a", "c1", "c3"])).toEqual(["c3", "c1", "a", "zz"]);
  });
});

describe("normalising legacy ids at load", () => {
  it("maps models.json", () => {
    const legacy = JSON.parse(JSON.stringify(modelsFixture).replace(/"c3"/g, '"champion"').replace(/"c1"/g, '"challenger"'));
    const m = normaliseModels(registry, legacy);
    expect(m.champion).toBe("c3");
    expect(m.models.map((x) => x.id)).toEqual(["c3", "c1", "engine", "a", "a_odds"]);
    expect(Object.keys(m.gameweeks[0].advice)).toContain("c1");
    expect(m.season_to_date.map((s) => s.model)).toContain("c3");
  });

  it("maps the history and accuracy files", () => {
    const entry = { points: 1 } as never;
    const history = normaliseHistory(registry, {
      champion: "champion",
      models: [{ id: "challenger" }],
      gameweeks: [{ gameweek: 1, models: { champion: entry, A: entry } }],
      summary: [{ model: "A_odds" }],
    } as unknown as ModelsHistory);
    expect(history.champion).toBe("c3");
    expect(history.models[0].id).toBe("c1");
    expect(Object.keys(history.gameweeks[0].models)).toEqual(["c3", "a"]);
    expect(history.summary[0].model).toBe("a_odds");

    const acc = normaliseAccuracy(registry, {
      seasons: [{ pooled_mae: { champion: 1 }, missing_models: { A: "x" }, gameweeks: [{ mae: { challenger: 1 } }] }],
    } as unknown as XpAccuracy);
    expect(Object.keys(acc.seasons[0].pooled_mae)).toEqual(["c3"]);
    expect(Object.keys(acc.seasons[0].missing_models)).toEqual(["a"]);
    expect(Object.keys(acc.seasons[0].gameweeks[0].mae)).toEqual(["c1"]);
  });

  it("leaves an id the registry has never heard of as it is", () => {
    const body = { seasons: [{ pooled_mae: { zz: 1 }, missing_models: {}, gameweeks: [] }] } as unknown as XpAccuracy;
    expect(Object.keys(normaliseAccuracy(registry, body).seasons[0].pooled_mae)).toEqual(["zz"]);
  });
});
