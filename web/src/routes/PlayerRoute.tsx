import { Link, useParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { PlayerDetail } from "../components/player/PlayerDetail";

/**
 * Player detail (E6-S3, FR-23, FR-29). Composition lives in `components/player/PlayerDetail.tsx`;
 * this route only resolves the id from the URL against the published players.
 *
 * The two lazy artefacts the page needs — `history.json` and `fixtures.json` — are fetched by the
 * panels that use them rather than here, so a missing one costs its own panel and nothing else
 * (DP-15).
 */
export function PlayerRoute() {
  const { id } = useParams<{ id: string }>();
  const { players } = useData();
  const playerId = Number(id);
  const player = players.players.find((p) => p.id === playerId) ?? null;

  if (!player) {
    return (
      <section className="placeholder" data-testid="player-not-found">
        <h2>Player not found</h2>
        <p className="placeholder-summary">
          No published player has id {id}. <Link to="/scout">Back to the scout table</Link>.
        </p>
      </section>
    );
  }

  return <PlayerDetail player={player} />;
}
