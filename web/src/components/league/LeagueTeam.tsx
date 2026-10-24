import { Link, useParams } from "react-router-dom";
import type { LeagueEntry, Player } from "../../contract/types";
import { useData } from "../../data/DataProvider";
import { pointsIn } from "../../data/season";
import { unready, useArtefact } from "../../data/store";
import { compareSquads, fieldedPoints } from "./league";
import "./league.css";

function PlayerLine({
  id,
  player,
  points,
  captain,
  showPoints,
  testId,
}: {
  id: number;
  player: Player | undefined;
  points: number | string | null;
  captain: "Captain" | "Vice-captain" | null;
  showPoints: boolean;
  testId?: string;
}) {
  return (
    <li className="league-team-player" data-testid={testId ?? `league-team-player-${id}`}>
      <span className="league-team-pos">{player?.position ?? "?"}</span>
      {player ? <Link to={`/player/${id}`}>{player.name}</Link> : <span>#{id}</span>}
      {captain && <span className="league-team-badge">{captain}</span>}
      {showPoints && <span className="league-team-points">{points ?? "—"}</span>}
    </li>
  );
}

/**
 * One entry's last gameweek (WEB-09): XI, bench, captain and vice, and each player's points that
 * gameweek, from the league's published squad joined to `history.json`; the squad lists raw points.
 * ORC-14 adds the moves (transfers, hit, chip) and the differentials against the owner's squad,
 * scored as each team fielded them: the XI after automatic substitutions, the armband from
 * `rules.json`, and the hits.
 */
export function LeagueTeam() {
  const { entryId } = useParams<{ entryId: string }>();
  const { players, rules } = useData();
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
  const owner = data.entries.find((e) => e.is_owner);
  const ownerSquad = owner?.squad ?? null;
  const diff = squad && ownerSquad && !entry.is_owner ? compareSquads(ownerSquad, squad) : null;
  const pointsOf = (id: number) => pointsIn(hist, id, gw);
  const theirs = squad ? fieldedPoints(squad, entry.moves?.chip ?? null, rules.chips, pointsOf) : new Map<number, number | null>();
  const yours = ownerSquad ? fieldedPoints(ownerSquad, owner?.moves?.chip ?? null, rules.chips, pointsOf) : new Map<number, number | null>();
  const total = (side: Map<number, number | null>) => [...side.values()].reduce((t: number, p) => t + (p ?? 0), 0);
  // Players both hold who scored differently for each: the armband, or one team benched him.
  const scoredApart = diff ? diff.overlapIds.filter((id) => theirs.get(id) !== yours.get(id)) : [];
  const swing = (title: string, ids: number[], points: (id: number) => number | string | null) => (
    <div>
      <h4>{title}</h4>
      {ids.length === 0 ? (
        <p className="league-note">None.</p>
      ) : (
        <ul className="league-team-list">
          {ids.map((id) => (
            <PlayerLine
              key={id}
              id={id}
              player={byId.get(id)}
              points={points(id)}
              captain={null}
              showPoints={hist !== null}
              testId={`diff-${id}`}
            />
          ))}
        </ul>
      )}
    </div>
  );
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
              {entry.moves.chip_label ?? "none"}
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
            {swing("They hold, you do not", diff.rivalOnlyIds, (id) => theirs.get(id) ?? null)}
            {swing("You hold, they do not", diff.ownerOnlyIds, (id) => yours.get(id) ?? null)}
            {swing(
              "Both hold, scored differently",
              scoredApart,
              (id) => `${theirs.get(id) ?? "—"} for them, ${yours.get(id) ?? "—"} for you`,
            )}
            {hist !== null && (
              <p data-testid="diff-net">
                Net swing to them in gameweek {gw}:{" "}
                {total(theirs) - total(yours) - (entry.moves?.hit_cost ?? 0) + (owner?.moves?.hit_cost ?? 0)} points.
                Each team&apos;s XI as fielded after automatic substitutions (the bench scores nothing),{" "}
                {rules.chips
                  ? "the captain's points multiplied as the game does"
                  : "raw points: the captain's multiplier is not published"}
                ; {entry.moves ? `their hit of ${entry.moves.hit_cost} counted` : "their hit is not known, so not counted"},{" "}
                {owner?.moves ? `and yours of ${owner.moves.hit_cost}` : "yours is not known"}. A player with no fixture
                counts as 0.
              </p>
            )}
          </>
        )}
      </section>
    </section>
  );
}
