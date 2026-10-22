import { describe, expect, it } from "vitest";
import { availableModels, effectiveModel, withModel } from "./DataProvider";
import type { PublishedData } from "./published";
import { buildRegistry } from "./registry";
import { challengerWeek, modelsFixture, players, squad, strategiesFixture, week } from "../test/fixtures";

function data(over: Partial<PublishedData> = {}): PublishedData {
  return {
    registry: buildRegistry(strategiesFixture),
    weeks: { c3: week, c1: challengerWeek },
    plans: {},
    models: modelsFixture,
    players,
    publishedSquad: squad,
    week,
    plan: null,
    ...over,
  } as unknown as PublishedData;
}

describe("availableModels", () => {
  it("offers every published strategy that has a week", () => {
    expect(availableModels(data())).toEqual(["c3", "c1"]);
  });

  it("never offers a strategy whose inputs failed the freshness check", () => {
    const models = {
      ...modelsFixture,
      models: modelsFixture.models.map((m) => (m.id === "c1" ? { ...m, available: false } : m)),
    };
    expect(availableModels(data({ models }))).toEqual(["c3"]);
  });

  it("keeps the champion when nothing else is available", () => {
    expect(availableModels(data({ weeks: {} }))).toEqual(["c3"]);
  });
});

describe("effectiveModel and withModel", () => {
  it("maps legacy values through the aliases, and an unknown or unavailable one to the champion", () => {
    expect(effectiveModel(data(), "challenger")).toBe("c1");
    expect(effectiveModel(data(), "champion")).toBe("c3");
    expect(effectiveModel(data(), "nonsense")).toBe("c3");
    expect(effectiveModel(data(), "")).toBe("c3");
    expect(effectiveModel(data(), "a")).toBe("c3"); // known but unpublished
  });

  it("swaps the week for the chosen strategy's and drops the champion's plan", () => {
    const d = data({ plan: { skipped: false } as never });
    expect(withModel(d, "c1").week).toBe(challengerWeek);
    expect(withModel(d, "c1").plan).toBeNull();
    expect(withModel(d, "c3")).toBe(d);
  });
});
