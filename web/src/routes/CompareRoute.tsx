import { useData } from "../data/DataProvider";
import { ComparisonView } from "../components/compare/ComparisonView";

/**
 * The comparison view (E6-S4, FR-28).
 *
 * A one-liner for the same reason `ScoutRoute` is: the route resolves the published data and hands
 * it over. Which players are being compared comes from the `?compare=` parameter, which
 * `ComparisonView` reads through `data/comparison.ts` — the router does not need to know the format
 * and neither does this file.
 */
export function CompareRoute() {
  const { players, meta } = useData();
  return (
    <ComparisonView allPlayers={players.players} horizonGameweeks={meta.horizon_gameweeks} />
  );
}
