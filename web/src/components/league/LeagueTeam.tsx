import { Link, useParams } from "react-router-dom";
import type { History, LeagueEntry, Player } from "../../contract/types";
import { useData } from "../../data/DataProvider";
import { pointsIn } from "../../data/season";
import { unready, useArtefact } from "../../data/store";
import { compareSquads } from "./league";
import "./league.css";

function Swing({
  title,
  ids,
  byId,
  hist,
  gw,
}: {
  title: string;
  ids: number[];
  byId: Map<number, Player>;
  hist: History | null;
  gw: number | null;
}) {
  return (
    <div>
      <h4>{title}</h4>
      {ids.length === 0 ? (
        <p className="league-note">None.</p>
      ) : (
        <ul className="league-team-list">
          {ids.map((id) => (
            <li key={id} className="league-team-player" data-testid={`diff-${id}`}>
              {byId.get(id) ? <Link to={`/player/${id}`}>{byId.get(id)!.name}</Link> : <span>#{id}</span>}
              {hist !== null && <span className="league-team-points">{pointsIn(hist, id, gw) ?? "—"}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
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
 * captain's multiplier is not applied: `rules.json` publishes none). ORC-14 adds the moves
 * (transfers, hit, chip) and the differentials against the owner's squad below it.
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
  const name = (id: number) => byId.get(id)?.name ?? `#${id}`;
  const ownerSquad = data.entries.find((e) => e.is_owner)?.squad ?? null;
  const diff = squad && ownerSquad && !entry.is_owner ? compareSquads(ownerSquad, squad) : null;
  const sum = (ids: number[]) => ids.reduce((t, id) => t + (pointsIn(hist, id, gw) ?? 0), 0);
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
              {history.status === "loading"
                ? "Loading each player's points…"
                : `Per-player points are not available: ${unready(history, "the season history is not published.")} Only the team's gameweek total${entry.event_total != null ? ` of ${entry.event_total}` : ""} is shown.`}
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

      <section aria-labelledby="lt-moves" data-testid="league-team-moves">
        <h3 id="lt-moves">Moves{entry.moves ? ` (gameweek ${entry.moves.gameweek})` : ""}</h3>
        {entry.moves ? (
          <>
            <p>
              {entry.moves.transfers.length === 0
                ? "No transfers."
                : entry.moves.transfers.map((t) => `${name(t.out_id)} → ${name(t.in_id)}`).join(", ")}
            </p>
            <p>
              Hit: {entry.moves.hit_cost === 0 ? "none" : `−${entry.moves.hit_cost} points`} · Chip:{" "}
              {entry.moves.chip ?? "none"}
            </p>
          </>
        ) : (
          <p className="league-note" data-testid="league-team-no-moves">
            This team&apos;s transfers, hit and chip are not available: they were not fetched, or the fetch failed.
          </p>
        )}
      </section>

      <section aria-labelledby="lt-diff" data-testid="league-team-diff">
        <h3 id="lt-diff">Differentials against your team</h3>
        {entry.is_owner ? (
          <p className="league-note">This is your team.</p>
        ) : diff === null ? (
          <p className="league-note">
            {squad === null ? "This team's squad was not published." : "Your own squad is not in the published league."}
          </p>
        ) : (
          <>
            <Swing title="They hold, you do not" ids={diff.rivalOnlyIds} byId={byId} hist={hist} gw={gw} />
            <Swing title="You hold, they do not" ids={diff.ownerOnlyIds} byId={byId} hist={hist} gw={gw} />
            {hist !== null && (
              <p data-testid="diff-net">
                Net swing to them in gameweek {gw}: {sum(diff.rivalOnlyIds) - sum(diff.ownerOnlyIds)} points (raw points; a
                player with no fixture counts as 0).
              </p>
            )}
          </>
        )}
      </section>
    </section>
  );
}
