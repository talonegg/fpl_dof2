/**
 * Locks and bans in storage.
 *
 * Two things are being protected. The first is the mutual exclusion: a player who is both locked and
 * banned makes every re-optimisation infeasible, so that state must be unreachable however it is
 * arrived at — including from a blob an older build wrote. The second is that every storage failure
 * degrades to "no marks" rather than to an exception, because losing a convenience is acceptable and
 * losing the page is not (DP-15).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  loadMarks,
  LOCKS_STORAGE_KEY,
  MAX_MARKED,
  NO_MARKS,
  parseMarks,
  saveMarks,
  toggleBan,
  toggleLock,
} from "./locks";

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("toggling", () => {
  it("locks and unlocks", () => {
    const once = toggleLock(NO_MARKS, 12);
    expect(once.locked).toEqual([12]);
    expect(toggleLock(once, 12).locked).toEqual([]);
  });

  it("bans and lifts", () => {
    const once = toggleBan(NO_MARKS, 12);
    expect(once.banned).toEqual([12]);
    expect(toggleBan(once, 12).banned).toEqual([]);
  });

  it("locking a banned player lifts the ban", () => {
    const banned = toggleBan(NO_MARKS, 12);
    const locked = toggleLock(banned, 12);
    expect(locked.locked).toEqual([12]);
    expect(locked.banned).toEqual([]);
  });

  it("banning a locked player releases the lock", () => {
    const locked = toggleLock(NO_MARKS, 12);
    const banned = toggleBan(locked, 12);
    expect(banned.banned).toEqual([12]);
    expect(banned.locked).toEqual([]);
  });

  it("keeps the two lists independent otherwise", () => {
    const marks = toggleBan(toggleLock(NO_MARKS, 1), 2);
    expect(marks).toEqual({ locked: [1], banned: [2] });
  });
});

describe("parsing what was in storage", () => {
  it("accepts a well-formed pair of lists", () => {
    expect(parseMarks({ locked: [1, 2], banned: [3] })).toEqual({ locked: [1, 2], banned: [3] });
  });

  it("returns nothing for a shape it does not recognise", () => {
    expect(parseMarks(null)).toEqual(NO_MARKS);
    expect(parseMarks("locked")).toEqual(NO_MARKS);
    expect(parseMarks(42)).toEqual(NO_MARKS);
    expect(parseMarks({})).toEqual(NO_MARKS);
  });

  it("drops entries that are not player ids", () => {
    expect(parseMarks({ locked: ["7", null, 7, Number.NaN], banned: [{}] })).toEqual({
      locked: [7],
      banned: [],
    });
  });

  it("de-duplicates", () => {
    expect(parseMarks({ locked: [7, 7, 7], banned: [] }).locked).toEqual([7]);
  });

  it("resolves a stored state claiming a player is both, in favour of the lock", () => {
    expect(parseMarks({ locked: [7], banned: [7, 8] })).toEqual({ locked: [7], banned: [8] });
  });

  it("caps each list, so a runaway write cannot exhaust the origin's quota", () => {
    const many = Array.from({ length: MAX_MARKED + 50 }, (_, i) => i);
    expect(parseMarks({ locked: many, banned: [] }).locked).toHaveLength(MAX_MARKED);
  });
});

describe("storage round trip", () => {
  it("saves and reloads", () => {
    saveMarks({ locked: [1, 2], banned: [3] });
    expect(loadMarks()).toEqual({ locked: [1, 2], banned: [3] });
  });

  it("reads nothing when nothing has been stored", () => {
    expect(loadMarks()).toEqual(NO_MARKS);
  });

  it("survives a stored value that is not JSON", () => {
    window.localStorage.setItem(LOCKS_STORAGE_KEY, "{not json");
    expect(loadMarks()).toEqual(NO_MARKS);
  });

  it("survives storage being unavailable altogether", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("access denied");
    });
    expect(loadMarks()).toEqual(NO_MARKS);
  });

  it("survives a full quota without losing the marks for this session", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => saveMarks({ locked: [1], banned: [] })).not.toThrow();
  });
});
