/**
 * The reader's own FPL team ID and mini-league ID, entered once in Settings (E13-S2, DL-44).
 *
 * Kept in `localStorage` only — never transmitted, never committed (Invariant 8, Invariant 10). This
 * is a **client-side lens** over already-published artefacts, distinct from `EntryConfig.team_id` /
 * `league_id`, which the pipeline reads server-side (via `FPL_DOF_TEAM_ID` / `FPL_DOF_LEAGUE_ID`,
 * E13-S1) to decide what gets built in the first place. The two normally coincide for the site's own
 * owner, but need not: anyone reading the published site — a rival in the mini-league, say — can
 * type their own ID here to see themselves highlighted, without changing what the pipeline built.
 *
 * Read defensively throughout, for the same reason `squad/locks.ts` is: storage may be absent,
 * disabled by private browsing, full, or holding a shape an older build wrote, and every one of
 * those degrades to "no identity entered" rather than to an error (DP-15).
 */

import { useCallback, useState } from "react";

export const IDENTITY_STORAGE_KEY = "fpl-dof.identity";

export interface OwnerIdentity {
  teamId: number | null;
  leagueId: number | null;
}

export const NO_IDENTITY: OwnerIdentity = { teamId: null, leagueId: null };

/** Mirrors `EntryConfig.team_id` / `league_id`: a positive integer, or unset. */
function positiveIntOrNull(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || !Number.isInteger(value)) {
    return null;
  }
  return value > 0 ? value : null;
}

export function parseIdentity(value: unknown): OwnerIdentity {
  if (typeof value !== "object" || value === null) return NO_IDENTITY;
  const record = value as Record<string, unknown>;
  return {
    teamId: positiveIntOrNull(record.teamId),
    leagueId: positiveIntOrNull(record.leagueId),
  };
}

export function loadIdentity(): OwnerIdentity {
  try {
    const stored = window.localStorage.getItem(IDENTITY_STORAGE_KEY);
    if (!stored) return NO_IDENTITY;
    return parseIdentity(JSON.parse(stored) as unknown);
  } catch {
    return NO_IDENTITY;
  }
}

export function saveIdentity(identity: OwnerIdentity): void {
  try {
    window.localStorage.setItem(IDENTITY_STORAGE_KEY, JSON.stringify(identity));
  } catch {
    // Quota exceeded, or storage disabled. The identity still applies this session; it just will
    // not be there tomorrow.
  }
}

export interface IdentityStore extends OwnerIdentity {
  setTeamId: (value: number | null) => void;
  setLeagueId: (value: number | null) => void;
  clear: () => void;
}

export function useOwnerIdentity(): IdentityStore {
  const [identity, setIdentity] = useState<OwnerIdentity>(loadIdentity);

  const apply = useCallback((next: (current: OwnerIdentity) => OwnerIdentity) => {
    setIdentity((current) => {
      const updated = next(current);
      saveIdentity(updated);
      return updated;
    });
  }, []);

  const setTeamId = useCallback(
    (value: number | null) => apply((current) => ({ ...current, teamId: value })),
    [apply],
  );
  const setLeagueId = useCallback(
    (value: number | null) => apply((current) => ({ ...current, leagueId: value })),
    [apply],
  );
  const clear = useCallback(() => apply(() => NO_IDENTITY), [apply]);

  return { ...identity, setTeamId, setLeagueId, clear };
}
