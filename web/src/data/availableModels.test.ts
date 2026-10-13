import { describe, expect, it } from "vitest";
import { availableModels } from "./DataProvider";
import type { PublishedData } from "./published";
import { modelsFixture } from "../test/fixtures";

function data(models: PublishedData["models"]): PublishedData {
  return { challenger: null, models } as unknown as PublishedData;
}

describe("availableModels", () => {
  it("offers every model that has advice and passed its input check", () => {
    expect(availableModels(data(modelsFixture))).toEqual(["champion", "engine", "a", "a_odds"]);
  });

  it("never offers a model whose inputs failed the freshness check", () => {
    const models = {
      ...modelsFixture,
      models: modelsFixture.models.map((m) =>
        m.id === "a_odds" ? { ...m, available: false, unavailable_reason: "live odds stale" } : m,
      ),
    };
    expect(availableModels(data(models))).not.toContain("a_odds");
  });

  it("keeps the champion when nothing else is available", () => {
    const models = { ...modelsFixture, models: modelsFixture.models.map((m) => ({ ...m, available: false })) };
    expect(availableModels(data(models))).toEqual(["champion"]);
  });
});
