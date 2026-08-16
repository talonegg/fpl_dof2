import { useMemo, useState } from "react";
import type { League } from "../../contract/types";
import { useData } from "../../data/DataProvider";
import { buildLeagueView, byOverlapDescending, nameList, playerNames } from "./league";
import type { AnchorState, LeagueRow } from "./league";

/**
 * The mini-league view (E6-S10, FR-32): standings, squad overlap, differentials in both directions
 * and captain divergence.
 *
 * The comparison columns are only as good as their anchor, so the anchor is stated on the page
 * rather than assumed. When there is no owner squad to compare against, the table still renders —
 * a league table is worth reading on its own — and the comparison columns are replaced by one
 * sentence saying why they are not there (DP-09, DP-15).
 */
export function LeagueTable({ league }: { league: League }) {
  const { players } = useData();
  const view = useMemo(() => buildLeagueView(league), [league]);
  const names = useMemo(() => playerNames(players), [players]);
  const [order, setOrder] = useState<"rank" | "overlap">("rank");
  const [expanded, setExpanded] = useState<number | null>(null);

  const rows = order === "overlap" ? byOverlapDescending(view.rows) : view.rows;
  const comparing = view.anchor === "anchored";

  return (
    <section className="league" data-testid="league-table">
      <header className="league-header">
        <h2>{league.league.name}</h2>
        <p className="league-sub">
          {league.league.entries_published} entries shown
          {league.gameweek === null
            ? ", before any gameweek has been scored"
            : `, squads as at gameweek ${league.gameweek}`}
          .
        </p>
        <p className="league-note" data-testid="league-anchor">
          {anchorNote(view.anchor, view.comparableCount, league.league.squad_limit)}
        </p>
      </header>

      {comparing && (
        <div className="league-controls">
          <span id="league-order-label">Order</span>
          <div className="league-order" role="group" aria-labelledby="league-order-label">
            <button
              type="button"
              className={order === "rank" ? "active" : ""}
              aria-pressed={order === "rank"}
              onClick={() => setOrder("rank")}
            >
              By rank
            </button>
            <button
              type="button"
              className={order === "overlap" ? "active" : ""}
              aria-pressed={order === "overlap"}
              onClick={() => setOrder("overlap")}
            >
              By squad overlap
            </button>
          </div>
        </div>
      )}

      <div className="league-scroll">
        <table className="league-grid">
          <caption className="visually-hidden">
            {league.league.name} standings, with squad overlap and captain divergence against your
            own team where both squads are published.
          </caption>
          <thead>
            <tr>
              <th scope="col">Rank</th>
              <th scope="col">Team</th>
              <th scope="col">GW</th>
              <th scope="col">Total</th>
              <th scope="col">Behind</th>
              {comparing && <th scope="col">Shared</th>}
              {comparing && <th scope="col">They have</th>}
              {comparing && <th scope="col">You have</th>}
              {comparing && <th scope="col">Captain</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row
                key={row.entry.entry_id}
                row={row}
                comparing={comparing}
                names={names}
                isExpanded={expanded === row.entry.entry_id}
                onToggle={() =>
                  setExpanded(expanded === row.entry.entry_id ? null : row.entry.entry_id)
                }
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Row({
  row,
  comparing,
  names,
  isExpanded,
  onToggle,
}: {
  row: LeagueRow;
  comparing: boolean;
  names: Map<number, string>;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const { entry, comparison } = row;
  const expandable = comparing && comparison !== null;

  return (
    <>
      <tr
        className={row.isOwner ? "league-row owner" : "league-row"}
        data-testid={`league-row-${entry.entry_id}`}
      >
        <td className="league-rank">
          {entry.rank}
          <RankMove change={row.rankChange} />
        </td>
        <td>
          <span className="league-team">{entry.entry_name}</span>
          <span className="league-manager">{entry.player_name}</span>
          {row.isOwner && <span className="league-you">You</span>}
        </td>
        <td className="league-number">{entry.event_total ?? "—"}</td>
        <td className="league-number">{entry.total}</td>
        <td className="league-number">{row.isOwner ? "—" : row.pointsBehindLeader}</td>

        {comparing && !row.isOwner && !comparison && (
          // Not a zero. A rival outside the fetch budget has no squad published, and rendering
          // that as "0 shared" would state a fact nobody measured (DP-09).
          <td className="league-unknown" colSpan={4}>
            Squad not published for this entry
          </td>
        )}
        {comparing && row.isOwner && (
          <td className="league-unknown" colSpan={4}>
            Your squad — the comparison is measured against this row
          </td>
        )}
        {comparing && comparison && !row.isOwner && (
          <>
            <td className="league-number">
              <button
                type="button"
                className="league-expand"
                onClick={onToggle}
                aria-expanded={isExpanded}
              >
                {comparison.overlapIds.length}
                <span className="visually-hidden">
                  {" "}
                  players shared with {entry.entry_name}; show the names
                </span>
              </button>
            </td>
            <td className="league-number risk">{comparison.rivalOnlyIds.length}</td>
            <td className="league-number bet">{comparison.ownerOnlyIds.length}</td>
            <td>
              <CaptainCell
                captain={
                  comparison.captainId === null ? undefined : names.get(comparison.captainId)
                }
                captainId={comparison.captainId}
                diverges={comparison.captainDiverges}
              />
            </td>
          </>
        )}
      </tr>

      {expandable && isExpanded && comparison && (
        <tr className="league-detail" data-testid={`league-detail-${entry.entry_id}`}>
          <td colSpan={9}>
            <dl>
              <div>
                <dt>Shared ({comparison.overlapIds.length})</dt>
                <dd>{joined(nameList(comparison.overlapIds, names))}</dd>
              </div>
              <div>
                <dt className="risk">Only they have ({comparison.rivalOnlyIds.length})</dt>
                <dd>{joined(nameList(comparison.rivalOnlyIds, names))}</dd>
              </div>
              <div>
                <dt className="bet">Only you have ({comparison.ownerOnlyIds.length})</dt>
                <dd>{joined(nameList(comparison.ownerOnlyIds, names))}</dd>
              </div>
            </dl>
          </td>
        </tr>
      )}
    </>
  );
}

function CaptainCell({
  captain,
  captainId,
  diverges,
}: {
  captain: string | undefined;
  captainId: number | null;
  diverges: boolean | null;
}) {
  if (captainId === null) return <span className="league-unknown">Not published</span>;

  const label = captain ?? `#${captainId}`;
  if (diverges === null) {
    return (
      <span className="league-unknown" title="One of the two captains is not published">
        {label} · unknown
      </span>
    );
  }
  // The word carries the meaning; the colour only reinforces it (E6-S9).
  return (
    <span className={diverges ? "league-captain diverges" : "league-captain"}>
      {label}
      <span className="league-captain-tag">{diverges ? "differs" : "same"}</span>
    </span>
  );
}

function RankMove({ change }: { change: number | null }) {
  if (change === null || change === 0) return null;
  const up = change > 0;
  return (
    <span className={up ? "league-move up" : "league-move down"}>
      {up ? "▲" : "▼"}
      {Math.abs(change)}
      <span className="visually-hidden"> places {up ? "gained" : "lost"}</span>
    </span>
  );
}

function joined(names: string[]): string {
  return names.length > 0 ? names.join(", ") : "None";
}

/** One sentence saying whether the comparison columns mean anything, and why when they do not. */
function anchorNote(anchor: AnchorState, comparable: number, squadLimit: number): string {
  switch (anchor) {
    case "anchored":
      return `Overlap and differentials are measured against your own squad, for the ${comparable} rival${
        comparable === 1 ? "" : "s"
      } whose squad was published.`;
    case "no_gameweek":
      return "No gameweek has been scored yet, so no manager has a squad to read — including you. The table is the whole of what exists until the first deadline passes.";
    case "no_owner_row":
      return "Your own team is not in this league's published rows, so there is nothing to measure overlap against. Set your team ID in configuration, and make sure it is a member of this league.";
    case "no_owner_squad":
      return squadLimit === 0
        ? "No squads were fetched — the squad budget is set to zero — so only the table is available."
        : "Your squad was not published for this gameweek, so overlap and differentials cannot be measured against it.";
  }
}
