import { Link } from "react-router-dom";
import type { LiveFigures, Player } from "../../contract/types";
import { bonusText, countedPoints, fieldedAndBench, substitutions } from "../../data/live";
import { formatPoints } from "../../format";
import "./live.css";

/**
 * One team's fifteen in the gameweek in play (LIVE-05, LIVE-06): minutes, points so far (the
 * captain's multiplied, as the pipeline applied the armband), and either each player's bonus
 * (confirmed or pending) or his expected points next gameweek. The projected substitutions are
 * named on the players they move, and again in words under the table.
 *
 * Display only. Every figure was scored upstream by the one realised scorer; nothing here scores,
 * substitutes or applies a multiplier of its own (Invariant 9).
 */
export function LiveSquadTable({
  figures,
  players,
  extra,
  rowTestId,
  linkPlayers = false,
  caption,
}: {
  figures: LiveFigures;
  players: Map<number, Player>;
  /** The last column: bonus for a team's drill-down, next gameweek's xP for Home. */
  extra: "bonus" | "xp";
  rowTestId: (playerId: number) => string;
  linkPlayers?: boolean;
  caption: string;
}) {
  const { fielded, bench } = fieldedAndBench(figures);
  const subs = substitutions(figures);
  const on = new Map(subs.map((s) => [s.on, s.off]));
  const off = new Map(subs.map((s) => [s.off, s.on]));
  const nameOf = (id: number) => players.get(id)?.name ?? `#${id}`;

  const row = (p: LiveFigures["players"][number], onBench: boolean) => {
    const player = players.get(p.player_id);
    const notes = [
      p.is_captain ? "captain" : null,
      p.is_vice_captain ? "vice" : null,
      p.player_id === figures.captain_id && figures.vice_used ? "armband" : null,
      onBench ? "bench" : null,
      on.has(p.player_id) ? `on for ${nameOf(on.get(p.player_id)!)} (projected)` : null,
      off.has(p.player_id) ? `off for ${nameOf(off.get(p.player_id)!)} (projected)` : null,
      !p.complete && p.minutes === 0 ? "yet to play" : null,
    ].filter((note): note is string => note !== null);
    return (
      <tr key={p.player_id} data-testid={rowTestId(p.player_id)} className={onBench ? "live-bench" : undefined}>
        <th scope="row">
          {linkPlayers && player ? <Link to={`/player/${p.player_id}`}>{player.name}</Link> : nameOf(p.player_id)}{" "}
          <span className="live-pts-detail">
            {player ? `${player.team} ${player.position}` : ""}
            {notes.length > 0 && `${player ? " · " : ""}${notes.join(" · ")}`}
          </span>
        </th>
        <td className="live-number">{p.minutes}</td>
        <td className="live-number" data-testid={`${rowTestId(p.player_id)}-pts`}>
          {onBench ? p.points : countedPoints(p)}
          {!onBench && p.multiplier > 1 && (
            <span className="live-pts-detail">
              {p.points} × {p.multiplier}
            </span>
          )}
        </td>
        <td className={extra === "xp" ? "live-number" : undefined}>
          {extra === "xp" ? (player ? formatPoints(player.xp_next) : "—") : bonusText(p)}
        </td>
      </tr>
    );
  };

  return (
    <>
      <div className="live-scroll">
        <table className="live-table">
          <caption className="visually-hidden">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">Player</th>
              <th scope="col" className="live-number">
                Min
              </th>
              <th scope="col" className="live-number">
                Pts
              </th>
              <th scope="col" className={extra === "xp" ? "live-number" : undefined}>
                {extra === "xp" ? "xP next" : "Bonus"}
              </th>
            </tr>
          </thead>
          <tbody>
            {fielded.map((p) => row(p, false))}
            {bench.map((p) => row(p, true))}
          </tbody>
        </table>
      </div>
      <div className="live-subs" data-testid="live-subs">
        <strong>Projected substitutions</strong>
        {subs.length === 0 ? (
          <p>None so far. A starter is only replaced once his gameweek is over without a minute.</p>
        ) : (
          <ul>
            {subs.map((s) => (
              <li key={s.on}>
                {nameOf(s.on)} on for {nameOf(s.off)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
