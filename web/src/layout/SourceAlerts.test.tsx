import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { challengerWeek, modelsFixture, strategiesFixture, week } from "../test/fixtures";
import type { Models, Week } from "../contract/types";
import { NAV_ITEMS } from "../routes/nav";

const GW = modelsFixture.gameweeks[modelsFixture.gameweeks.length - 1].gameweek;
const ahead = { ...week.deadline, gameweek: GW, deadline_utc: "2099-01-02T11:00:00Z" };
const passed = { ...ahead, deadline_utc: "2020-01-02T11:00:00Z" };
const SOURCE = "Match odds in the pipeline run";

/** A + odds without advice for the Open gameweek, waiting for its odds. */
function waiting(): Models {
  const gameweeks = modelsFixture.gameweeks.map((g, i, all) =>
    i < all.length - 1
      ? g
      : {
          ...g,
          availability: {
            ...g.availability,
            a_odds: {
              available: false,
              reason: "no advice: MissingOddsError",
              sources: [SOURCE],
              since: "2099-01-01T02:07:00Z",
              next_check: "2099-01-01T16:07:00Z",
            },
          },
        },
  );
  return { ...modelsFixture, gameweeks };
}

function serve(deadline: Week["deadline"], models: Models, c1: Week = challengerWeek) {
  installFetchStub({
    bodies: { strategies: strategiesFixture, models, week: { ...week, deadline }, week_c1: { ...c1, deadline } },
  });
}

describe("source availability alerts (ORC-07)", () => {
  beforeEach(() => resetAppState());
  afterEach(() => vi.unstubAllGlobals());

  it.each(NAV_ITEMS.map((n) => n.path))("shows the offline banner on %s, naming the source and the next check", async (path) => {
    serve(ahead, waiting());
    renderApp(path);
    const banner = await screen.findByTestId("source-offline-a_odds");
    expect(banner.getAttribute("role")).toBe("alert");
    expect(banner.textContent).toContain("A + odds has no advice for GW10");
    expect(banner.textContent).toContain(SOURCE);
    expect(banner.textContent).toContain("Next checked at");
  });

  it("shows the arrival once the strategy advises, and the banner goes", async () => {
    const arrived = { ...challengerWeek, arrived: { sources: [SOURCE], at: "2099-01-01T16:09:00Z" } };
    serve(ahead, modelsFixture, arrived);
    renderApp("/");
    const notice = await screen.findByTestId("source-arrived-c1");
    expect(notice.getAttribute("role")).toBe("status");
    expect(notice.textContent).toContain(`${SOURCE} arrived`);
    expect(notice.textContent).toContain("Challenger (C1) was refreshed with it");
    expect(screen.queryByTestId("source-offline-a_odds")).toBeNull();
  });

  it("shows no banner once the deadline has passed", async () => {
    serve(passed, waiting());
    renderApp("/");
    await screen.findByTestId("header");
    expect(screen.queryByTestId("source-offline-a_odds")).toBeNull();
  });
});
