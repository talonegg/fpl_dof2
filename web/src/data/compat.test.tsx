import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { screen, waitFor } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";
import { meta } from "../test/fixtures";
import { CONTRACT_MINOR, CONTRACT_VERSION } from "../contract/types";
import { DATA_DIR, PUBLISHED_CACHE, warmPublishedCache } from "./offline";

const HARDCODED = /data\/v\d|published-v\d/;

describe("contract versioning (WEB-02)", () => {
  beforeEach(() => {
    resetAppState();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("refuses data with another major, visibly, and says what to do", async () => {
    installFetchStub({ bodies: { meta: { ...meta, contract_version: CONTRACT_VERSION + 1 } } });
    renderApp("/");
    const refusal = await waitFor(() => screen.getByTestId("app-refused"));
    expect(refusal.getAttribute("role")).toBe("alert");
    expect(refusal.textContent).toMatch(/Reload/);
    expect(screen.queryByTestId("header")).toBeNull();
  });

  it("warns, and still renders, when the data's minor is older than the app needs", async () => {
    installFetchStub({ bodies: { meta: { ...meta, contract_minor: CONTRACT_MINOR - 1 } } });
    renderApp("/");
    const warning = await waitFor(() => screen.getByTestId("app-minor-warning"));
    expect(warning.getAttribute("role")).toBe("status");
    expect(screen.getByTestId("header")).toBeTruthy();
  });

  it("shows no warning for current data", async () => {
    installFetchStub();
    renderApp("/");
    await waitFor(() => screen.getByTestId("header"));
    expect(screen.queryByTestId("app-minor-warning")).toBeNull();
  });

  it("derives the data path and cache name from the one constant", () => {
    expect(DATA_DIR).toBe(`data/v${CONTRACT_VERSION}`);
    expect(PUBLISHED_CACHE).toBe(`fpl-dof-published-v${CONTRACT_VERSION}`);
  });

  it("purges other majors' published caches but leaves unrelated ones", async () => {
    const deleted: string[] = [];
    const cache = { match: async () => true } as unknown as Cache;
    const storage = {
      keys: async () => ["fpl-dof-published-v0", PUBLISHED_CACHE, "workbox-precache"],
      delete: async (k: string) => deleted.push(k) > 0,
      open: async () => cache,
    } as unknown as CacheStorage;
    await warmPublishedCache({ dataBase: `/${DATA_DIR}`, cacheStorage: storage, names: ["meta"] });
    expect(deleted).toEqual(["fpl-dof-published-v0"]);
  });

  it("restates the version nowhere outside the generated file and the contracts", () => {
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.tsx?$/.test(name) && !/\.test\.|fixtures|types\.ts$/.test(name)) {
          if (HARDCODED.test(readFileSync(path, "utf8"))) offenders.push(path);
        }
      }
    };
    const root = process.cwd();
    walk(join(root, "src"));
    const config = join(root, "vite.config.ts");
    if (HARDCODED.test(readFileSync(config, "utf8"))) offenders.push(config);
    expect(offenders).toEqual([]);
  });
});
