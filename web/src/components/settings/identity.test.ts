/**
 * The owner identity in storage (E13-S2).
 *
 * The behaviour worth protecting is the same shape as `squad/locks.ts`'s: every storage failure or
 * malformed stored value degrades to "nothing entered" rather than to an exception, and only a
 * positive integer counts as an id — anything else, including zero and negative ids `EntryConfig`
 * itself rejects, is dropped rather than trusted.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  IDENTITY_STORAGE_KEY,
  loadIdentity,
  NO_IDENTITY,
  parseIdentity,
  saveIdentity,
} from "./identity";

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("parsing what was in storage", () => {
  it("accepts a well-formed pair of ids", () => {
    expect(parseIdentity({ teamId: 1234567, leagueId: 987654 })).toEqual({
      teamId: 1234567,
      leagueId: 987654,
    });
  });

  it("returns nothing for a shape it does not recognise", () => {
    expect(parseIdentity(null)).toEqual(NO_IDENTITY);
    expect(parseIdentity("1234567")).toEqual(NO_IDENTITY);
    expect(parseIdentity(42)).toEqual(NO_IDENTITY);
    expect(parseIdentity({})).toEqual(NO_IDENTITY);
  });

  it("drops a non-positive or non-integer id, same as EntryConfig", () => {
    expect(parseIdentity({ teamId: 0, leagueId: -5 })).toEqual(NO_IDENTITY);
    expect(parseIdentity({ teamId: 1.5, leagueId: Number.NaN })).toEqual(NO_IDENTITY);
    expect(parseIdentity({ teamId: "1234567", leagueId: null })).toEqual(NO_IDENTITY);
  });

  it("allows one id to be set without the other", () => {
    expect(parseIdentity({ teamId: 1234567 })).toEqual({ teamId: 1234567, leagueId: null });
  });
});

describe("storage round trip", () => {
  it("saves and reloads", () => {
    saveIdentity({ teamId: 1234567, leagueId: 987654 });
    expect(loadIdentity()).toEqual({ teamId: 1234567, leagueId: 987654 });
  });

  it("reads nothing when nothing has been stored", () => {
    expect(loadIdentity()).toEqual(NO_IDENTITY);
  });

  it("survives a stored value that is not JSON", () => {
    window.localStorage.setItem(IDENTITY_STORAGE_KEY, "{not json");
    expect(loadIdentity()).toEqual(NO_IDENTITY);
  });

  it("survives storage being unavailable altogether", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("access denied");
    });
    expect(loadIdentity()).toEqual(NO_IDENTITY);
  });

  it("survives a full quota without throwing", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => saveIdentity({ teamId: 1234567, leagueId: null })).not.toThrow();
  });
});
