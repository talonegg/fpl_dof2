import { Link, useParams } from "react-router-dom";
import type { History, LeagueEntry, Player } from "../../contract/types";
import { useData } from "../../data/DataProvider";
import { unready, useArtefact } from "../../data/store";
import "./league.css";

/** Raw points a player scored in one gameweek (a double gameweek sums), or null when no fixture is recorded. */
function pointsIn(history: History | null, playerId: number, gameweek: number | null): number | null {
  if (!history || gameweek === null) return null;
  const rows = history.players.find((p) => p.id === playerId)?.gameweeks.filter((g) => g.gw === gameweek) ?? [];
  return rows.length === 0 ? null : rows.reduce((sum, g) => sum + g.pts, 0);
}

function PlayerLine({
  id,
  player,
  points,
  captain,
  showPoints,
}: {
  id: number;
  player: Player | undefined;
  points: number | null;
  captain: "Captain" | "Vice-captain" | null;
  showPoints: boolean;
}) {
  return (
    <li className="league-team-player" data-testid={`league-team-player-${id}`}>
      <span className="league-team-pos">{player?.position ?? "?"}</span>
      {player ? <Link to={`/player/${id}`}>{player.name}</Link> : <span>#{id}</span>}
      {captain && <span className="league-team-badge">{captain}</span>}
      {showPoints && <span className="league-team-points">{points ?? "—"}</span>}
    </li>
  );
}

/**
 * One entry's last gameweek (WEB-09): XI, bench, captain and vice, and each player's points that
 * gameweek, from the league's published squad joined to `history.json`. Points are raw (the
 * captain's multiplier is not applied). Drop B (ORC-14) adds transfers, hits, the chip and
 * differentials as further sections below the squad.
 */
export function LeagueTeam() {
  const { entryId } = useParams<{ entryId: string }>();
  const { players } = useData();
  const league = useArtefact("league").state;
  const history = useArtefact("history").state;

  if (league.status === "loading") return <p data-testid="league-team-loading">Loading the team…</p>;
  const back = <Link to="/league">Back to the league</Link>;
  if (league.status !== "ready") {
    return (
      <section className="league-status" data-testid="league-team-error">
        <h2>Mini-league team</h2>
        <p>{unready(league, "No mini-league is published.")}</p>
        <p>{back}</p>
      </section>
    );
  }

  const data = league.data;
  const entry: LeagueEntry | undefined = data.entries.find((e) => e.entry_id === Number(entryId));
  if (!entry) {
    return (
      <section className="league-status" data-testid="league-team-not-found">
        <h2>Team not found</h2>
        <p>No published entry has id {entryId}.</p>
        <p>{back}</p>
      </section>
    );
  }

  const squad = entry.squad ?? null;
  const gw = data.gameweek;
  const hist = history.status === "ready" ? history.data : null;
  const byId = new Map(players.players.map((p) => [p.id, p]));
  const groups: [string, number[]][] = squad
    ? [
        ["Starting XI", squad.player_ids.filter((id) => squad.starting_ids.includes(id))],
        ["Bench", squad.player_ids.filter((id) => !squad.starting_ids.includes(id))],
      ]
    : [];

  return (
    <section className="league-squad" data-testid="league-team">
      <header className="league-header">
        <h2>{entry.entry_name}</h2>
        <p className="league-sub">
          {entry.player_name} · rank {entry.rank} · {entry.total} points
          {gw !== null && entry.event_total != null && ` · ${entry.event_total} in gameweek ${gw}`}
        </p>
        <p>{back}</p>
      </header>

      {squad === null ? (
        <p className="league-note" data-testid="league-team-unpublished">
          This team&apos;s squad was not published
          {data.league.squad_limit === 0
            ? ": squads were not requested."
            : gw === null
              ? ": no gameweek has been scored yet."
              : `: only the top ${data.league.squad_limit} entries' squads are fetched.`}
        </p>
      ) : (
        <>
          {hist === null && (
            <p className="league-note" data-testid="league-team-no-points">
              Per-player points are not available (the season history is not published), so only the
              team&apos;s gameweek total{entry.event_total != null ? ` of ${entry.event_total}` : ""} is shown.
            </p>
          )}
          {groups.map(([title, ids]) => (
            <section key={title} aria-labelledby={`lt-${title.replace(" ", "-")}`}>
              <h3 id={`lt-${title.replace(" ", "-")}`}>
                {title}
                {gw !== null && <span className="league-sub"> (gameweek {gw}, raw points)</span>}
              </h3>
              <ul className="league-team-list">
                {ids.map((id) => (
                  <PlayerLine
                    key={id}
                    id={id}
                    player={byId.get(id)}
                    points={pointsIn(hist, id, gw)}
                    captain={
                      id === squad?.captain_id ? "Captain" : id === squad?.vice_captain_id ? "Vice-captain" : null
                    }
                    showPoints={hist !== null}
                  />
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </section>
  );
}
