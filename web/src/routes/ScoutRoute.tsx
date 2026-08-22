import { useMemo } from "react";
import { useData } from "../data/DataProvider";
import { useOwnerIdentity } from "../components/settings/identity";
import { ScoutTable } from "../components/scout/ScoutTable";

/**
 * The scout view (E6-S2, FR-27): the searchable, filterable, sortable table over every player.
 *
 * The route stays a one-liner on purpose. It resolves the published data and hands it over; the
 * table owns filtering, sorting, columns, presets and the comparison selection, none of which the
 * router needs to know about.
 *
 * `ownedIds` is the published squad's fifteen (E13-S2): offered as a filter only once a team ID has
 * been entered in Settings, so the table does not presume "your squad" language before the reader
 * has said who they are.
 */
export function ScoutRoute() {
  const { players, squad } = useData();
  const identity = useOwnerIdentity();
  const ownedIds = useMemo(
    () => (identity.teamId === null ? null : new Set(squad.players.map((p) => p.player_id))),
    [identity.teamId, squad],
  );
  return <ScoutTable players={players.players} ownedIds={ownedIds} />;
}
