/**
 * Locks and bans: players the reader insists on, and players they will not have.
 *
 * Kept in `localStorage` for the same reason saved scout presets are (DL-36): there is no account
 * and no server (NFR-11, Invariant 8), so browser storage is the only place a personal preference
 * can live. Read defensively throughout — storage may be absent, disabled by private browsing, full,
 * or holding a shape an older build wrote — and every one of those degrades to "no locks or bans"
 * rather than to an error (DP-15). The reader loses a convenience, never the page.
 *
 * A player is never both. Locking a banned player lifts the ban and vice versa, because the
 * alternative is a stored state that can only produce an infeasible re-optimisation.
 */

import { useCallback, useMemo, useState } from "react";

export const LOCKS_STORAGE_KEY = "fpl-dof.squad-locks";

/**
 * How many ids are kept on each list.
 *
 * DP-06: a named limit, not a literal. It exists so a runaway loop or a pasted blob cannot exhaust
 * the origin's storage quota and take the theme preference down with it. A squad holds fifteen and a
 * pool around seven hundred, so this is far beyond any hand-made list.
 */
export const MAX_MARKED = 200;

export interface SquadMarks {
  locked: number[];
  banned: number[];
}

export const NO_MARKS: SquadMarks = { locked: [], banned: [] };

/** Player ids, coerced from whatever was in storage. Anything that is not a finite id is dropped. */
function idArray(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  const ids = value.filter(
    (item): item is number => typeof item === "number" && Number.isFinite(item),
  );
  return [...new Set(ids)].slice(0, MAX_MARKED);
}

export function parseMarks(value: unknown): SquadMarks {
  if (typeof value !== "object" || value === null) return NO_MARKS;
  const record = value as Record<string, unknown>;
  const locked = idArray(record.locked);
  const lockedSet = new Set(locked);
  // A stored state claiming both wins for the lock — an explicit "must have" is the stronger
  // statement, and one of the two has to give.
  const banned = idArray(record.banned).filter((id) => !lockedSet.has(id));
  return { locked, banned };
}

export function loadMarks(): SquadMarks {
  try {
    const stored = window.localStorage.getItem(LOCKS_STORAGE_KEY);
    if (!stored) return NO_MARKS;
    return parseMarks(JSON.parse(stored) as unknown);
  } catch {
    return NO_MARKS;
  }
}

export function saveMarks(marks: SquadMarks): void {
  try {
    window.localStorage.setItem(
      LOCKS_STORAGE_KEY,
      JSON.stringify({
        locked: marks.locked.slice(0, MAX_MARKED),
        banned: marks.banned.slice(0, MAX_MARKED),
      }),
    );
  } catch {
    // Quota exceeded, or storage disabled. The marks still apply in this session; they just will
    // not be there tomorrow.
  }
}

function toggle(list: readonly number[], id: number): number[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id].slice(-MAX_MARKED);
}

/** Pure state transitions, so the rules about mutual exclusion are testable without React. */
export function toggleLock(marks: SquadMarks, id: number): SquadMarks {
  const locked = toggle(marks.locked, id);
  return { locked, banned: marks.banned.filter((item) => !locked.includes(item)) };
}

export function toggleBan(marks: SquadMarks, id: number): SquadMarks {
  const banned = toggle(marks.banned, id);
  return { banned, locked: marks.locked.filter((item) => !banned.includes(item)) };
}

export interface MarkStore extends SquadMarks {
  isLocked: (id: number) => boolean;
  isBanned: (id: number) => boolean;
  lock: (id: number) => void;
  ban: (id: number) => void;
  clear: () => void;
}

export function useSquadMarks(): MarkStore {
  const [marks, setMarks] = useState<SquadMarks>(loadMarks);

  const apply = useCallback((next: (current: SquadMarks) => SquadMarks) => {
    setMarks((current) => {
      const updated = next(current);
      saveMarks(updated);
      return updated;
    });
  }, []);

  const lock = useCallback((id: number) => apply((current) => toggleLock(current, id)), [apply]);
  const ban = useCallback((id: number) => apply((current) => toggleBan(current, id)), [apply]);
  const clear = useCallback(() => apply(() => NO_MARKS), [apply]);

  const lockedSet = useMemo(() => new Set(marks.locked), [marks.locked]);
  const bannedSet = useMemo(() => new Set(marks.banned), [marks.banned]);

  return {
    locked: marks.locked,
    banned: marks.banned,
    isLocked: (id) => lockedSet.has(id),
    isBanned: (id) => bannedSet.has(id),
    lock,
    ban,
    clear,
  };
}
