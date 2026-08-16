import { useData } from "../data/DataProvider";
import { ScoutTable } from "../components/scout/ScoutTable";

/**
 * The scout view (E6-S2, FR-27): the searchable, filterable, sortable table over every player.
 *
 * The route stays a one-liner on purpose. It resolves the published data and hands it over; the
 * table owns filtering, sorting, columns, presets and the comparison selection, none of which the
 * router needs to know about.
 */
export function ScoutRoute() {
  const { players } = useData();
  return <ScoutTable players={players.players} />;
}
