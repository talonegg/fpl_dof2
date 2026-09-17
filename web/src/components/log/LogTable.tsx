import { useMemo } from "react";
import type { Log, LogGameweek } from "../../contract/types";
import { useData } from "../../data/DataProvider";
import { formatPoints } from "../../format";

/**
 * The season log (DL-69, E8 §3): one row per finished gameweek, newest first.
 *
 * Three columns of fact and one of judgement, kept visibly apart. *Played* and *scored* are the
 * game's own record. *Advised* is the ledger's, written before the deadline, and it is shown as
 * "no advice recorded" where there was none — the first four gameweeks of 2026/27 were decided
 * without the tool, and the table says so instead of leaving a blank that could be read either
 * way (DP-09). *Followed* is the reconciliation, and an unexplained divergence is named as such
 * rather than folded into "overridden": it usually means a submission error (E1-S5).
 */
export function LogTable({ log }: { log: Log }) {
  const { players } = useData();
  const names = useMemo(
    () => new Map(players.players.map((player) => [player.id, player.name])),
    [players],
  );
  const name = (id: number | null) => (id === null ? "—" : (names.get(id) ?? `#${id}`));
  const rows = useMemo(() => [...log.gameweeks].sort((a, b) => b.gameweek - a.gameweek), [log]);

  return (
    <section className="log" aria-labelledby="log-heading" data-testid="log-table">
      <header className="log-header">
        <h2 id="log-heading">Season log</h2>
        <p className="log-sub" data-testid="log-summary">
          {log.summary.gameweeks_played} gameweek{log.summary.gameweeks_played === 1 ? "" : "s"}{" "}
          played · {log.summary.total_points} points · advice recorded for{" "}
          {log.summary.gameweeks_advised}, followed {log.summary.advice_followed}, overridden{" "}
          {log.summary.advice_overridden}
        </p>
        <p className="log-note">
          Played and scored are the game's own record. Advised is what the pipeline published
          before the deadline, kept in its ledger; it is never reconstructed afterwards, so a
          gameweek decided without the tool says so.
        </p>
      </header>

      <div className="log-scroll">
        <table className="log-grid">
          <thead>
            <tr>
              <th scope="col">GW</th>
              <th scope="col">Points</th>
              <th scope="col">Total</th>
              <th scope="col">Overall rank</th>
              <th scope="col">Captain</th>
              <th scope="col">Transfers</th>
              <th scope="col">Chip</th>
              <th scope="col">Advised</th>
              <th scope="col">Followed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <LogRow key={row.gameweek} row={row} name={name} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function LogRow({ row, name }: { row: LogGameweek; name: (id: number | null) => string }) {
  const score = row.score;
  const advised = row.advised;
  const reconciliation = row.reconciliation;
  const unexplained = reconciliation?.divergences.filter((d) => d.status === "unexplained") ?? [];

  return (
    <tr data-testid={`log-row-${row.gameweek}`}>
      <th scope="row">{row.gameweek}</th>
      <td>{score ? score.points : "—"}</td>
      <td>{score ? score.total_points : "—"}</td>
      <td>{score?.overall_rank ? score.overall_rank.toLocaleString() : "—"}</td>
      <td>{name(row.played.captain)}</td>
      <td>
        {score
          ? `${score.transfers}${score.transfers_cost > 0 ? ` (−${score.transfers_cost})` : ""}`
          : "—"}
      </td>
      <td>{row.chip ?? "—"}</td>
      <td data-testid={`log-advised-${row.gameweek}`}>
        {advised ? (
          <>
            captain {name(advised.captain)} · {advised.transfers} transfer
            {advised.transfers === 1 ? "" : "s"} · {formatPoints(advised.expected_points)} xP
          </>
        ) : (
          <span className="log-no-advice">no advice recorded</span>
        )}
      </td>
      <td data-testid={`log-followed-${row.gameweek}`}>
        {!reconciliation ? (
          "—"
        ) : reconciliation.followed ? (
          <span className="log-followed">followed</span>
        ) : unexplained.length > 0 ? (
          <span className="log-unexplained">
            {unexplained.length} unexplained difference{unexplained.length === 1 ? "" : "s"}
          </span>
        ) : (
          <span className="log-overridden">overridden</span>
        )}
      </td>
    </tr>
  );
}
