/**
 * The comparison view (E6-S4, FR-28): two to four players side by side, with a verdict.
 *
 * **The URL is the state.** The selection arrives as `#/compare?compare=1,2,3` and every change on
 * this page — removing a player — is a navigation, not a `useState`. That is what keeps the view
 * bookmarkable and pasteable (DL-36): a comparison someone sends you renders the same comparison,
 * and reloading the page does not empty it. `data/comparison.ts` owns the format; this file never
 * hand-writes it.
 *
 * An id in a URL is not a player, so ids are resolved against the published set and unresolved ones
 * are reported rather than silently dropped (DP-09, DP-15). Below two resolved players there is
 * nothing to compare, and the view says how to get here instead of rendering an empty table.
 */

import { useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { Player } from "../../contract/types";
import { COMPARE_MAX, COMPARE_MIN, compareHref, parseCompareIds } from "../../data/comparison";
import { formatPrice } from "../../format";
import { CompareTrends } from "./CompareTrends";
import { COMPARE_ROWS, GROUP_LABELS, GROUP_ORDER, leadingId } from "./rows";
import { buildVerdict } from "./verdict";
import type { CompareRow } from "./rows";
import "./compare.css";

interface ComparisonViewProps {
  /** Every published player. Resolution happens here, against the ids in the URL. */
  allPlayers: readonly Player[];
  /** From `meta.horizon_gameweeks`, so the verdict can say "the next 6 gameweeks" and mean it. */
  horizonGameweeks?: number;
}

export function ComparisonView({ allPlayers, horizonGameweeks }: ComparisonViewProps) {
  const { search } = useLocation();
  const navigate = useNavigate();

  const ids = useMemo(() => parseCompareIds(search), [search]);

  const { players, missingIds } = useMemo(() => {
    const byId = new Map(allPlayers.map((player) => [player.id, player]));
    const resolved: Player[] = [];
    const missing: number[] = [];
    for (const id of ids) {
      const player = byId.get(id);
      if (player) resolved.push(player);
      else missing.push(id);
    }
    return { players: resolved, missingIds: missing };
  }, [allPlayers, ids]);

  if (players.length < COMPARE_MIN) {
    return <ComparisonEmpty resolved={players} missingIds={missingIds} />;
  }

  return (
    <ComparisonBoard
      players={players}
      missingIds={missingIds}
      horizonGameweeks={horizonGameweeks}
      onRemove={(id) => {
        // A removal is a navigation: the address bar stays the record of what is being compared.
        navigate(compareHref(players.filter((player) => player.id !== id).map((p) => p.id)));
      }}
    />
  );
}

/**
 * Nothing to compare.
 *
 * Reached by typing `/compare` directly, by following a link whose ids have since left the
 * published set, or by bookmarking a comparison from a previous season's data. All three are the
 * reader's situation rather than an error, so this explains the route back rather than apologising.
 */
function ComparisonEmpty({
  resolved,
  missingIds,
}: {
  resolved: readonly Player[];
  missingIds: readonly number[];
}) {
  return (
    <section className="compare compare-empty" data-testid="compare-empty">
      <h1 className="compare-title">Compare players</h1>
      <p className="compare-lede">
        A comparison holds {COMPARE_MIN} to {COMPARE_MAX} players. This link resolves to{" "}
        {resolved.length === 0 ? "none" : resolved.length === 1 ? "only one" : resolved.length}.
      </p>

      {resolved.length === 1 && (
        <p className="compare-note" data-testid="compare-empty-resolved">
          {resolved[0].name} is in the published data — pick at least one more to compare against.
        </p>
      )}

      {missingIds.length > 0 && (
        <p className="compare-note" data-testid="compare-empty-missing">
          {missingIds.length === 1 ? "Player id" : "Player ids"} {missingIds.join(", ")}{" "}
          {missingIds.length === 1 ? "is" : "are"} not in this publication. Ids are reassigned
          between seasons, so a link kept from last season will not resolve.
        </p>
      )}

      <p className="compare-empty-how">
        Tick up to {COMPARE_MAX} players on the scout table, then follow the compare link that
        appears. The selection travels in the address bar, so the page you land on is one you can
        bookmark or send to somebody.
      </p>

      <Link className="compare-cta" to="/scout" data-testid="compare-empty-scout">
        Pick players on the Scout view
      </Link>
    </section>
  );
}

interface ComparisonBoardProps {
  players: readonly Player[];
  missingIds: readonly number[];
  horizonGameweeks?: number;
  onRemove: (id: number) => void;
}

function ComparisonBoard({
  players,
  missingIds,
  horizonGameweeks,
  onRemove,
}: ComparisonBoardProps) {
  const verdict = useMemo(
    () => buildVerdict(players, { horizonGameweeks }),
    [players, horizonGameweeks],
  );

  // One lead per row, computed once rather than once per cell.
  const leaders = useMemo(() => {
    const map = new Map<string, number | null>();
    for (const row of COMPARE_ROWS) map.set(row.key, leadingId(row, players));
    return map;
  }, [players]);

  const canRemove = players.length > COMPARE_MIN;

  return (
    <section className="compare" data-testid="compare">
      <header className="compare-head">
        <h1 className="compare-title">
          {players.map((player) => player.name).join(" against ")}
        </h1>
        <Link className="compare-change" to="/scout" data-testid="compare-change">
          Change selection on the Scout view
        </Link>
      </header>

      {missingIds.length > 0 && (
        <p className="compare-note" role="status" data-testid="compare-missing">
          {missingIds.length === 1 ? "Player id" : "Player ids"} {missingIds.join(", ")} in this link{" "}
          {missingIds.length === 1 ? "is" : "are"} not in the published data, and{" "}
          {missingIds.length === 1 ? "has" : "have"} been left out.
        </p>
      )}

      <VerdictPanel verdict={verdict} />

      <div className="compare-scroll" data-testid="compare-scroll">
        <table className="compare-table" data-testid="compare-table">
          <caption className="compare-hidden">
            Published figures for the {players.length} players being compared. Expected-points
            figures carry their uncertainty; a row is marked as led only where the difference is
            larger than that uncertainty.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="compare-corner">
                <span className="compare-hidden">Attribute</span>
              </th>
              {players.map((player) => (
                <th scope="col" key={player.id} className="compare-player-head">
                  <Link className="compare-player-name" to={`/player/${player.id}`}>
                    {player.name}
                  </Link>
                  <span className="compare-player-meta">
                    {player.position} · {player.team} · {formatPrice(player.price)}
                  </span>
                  <button
                    type="button"
                    className="compare-remove"
                    onClick={() => onRemove(player.id)}
                    disabled={!canRemove}
                    title={
                      canRemove
                        ? `Remove ${player.name} from this comparison`
                        : `A comparison needs at least ${COMPARE_MIN} players`
                    }
                    data-testid={`compare-remove-${player.id}`}
                  >
                    Remove
                  </button>
                </th>
              ))}
            </tr>
          </thead>

          {GROUP_ORDER.map((group) => {
            const rows = COMPARE_ROWS.filter((row) => row.group === group);
            if (rows.length === 0) return null;
            return (
              <tbody key={group}>
                <tr className="compare-group">
                  <th scope="colgroup" colSpan={players.length + 1}>
                    {GROUP_LABELS[group]}
                  </th>
                </tr>
                {rows.map((row) => (
                  <CompareTableRow
                    key={row.key}
                    row={row}
                    players={players}
                    leaderId={leaders.get(row.key) ?? null}
                  />
                ))}
              </tbody>
            );
          })}
        </table>
      </div>

      {/* E6-S5 fills this: overlaid trends from `history.json`, and the forecast bands. */}
      <CompareTrends players={players} horizonGameweeks={horizonGameweeks} />

      {/*
        TODO(E6-S8): the fixture run for each compared player's club over the horizon, reading
        `fetchFixtures()` from `data/api.ts` — `player/fixtureRun.ts` already builds a run for one
        player and is the thing to reuse. Note `model.teams_rated === 0` means the grid is unrated,
        and must be labelled as such rather than rendered as a rating (DP-09).
      */}
      <section className="compare-pending" data-testid="compare-pending">
        <h2>Fixture runs</h2>
        <p>
          Not on this page yet. The fixture run arrives with E6-S8, reading a grid that is already
          published, so this section fills in without the comparison above changing. Nothing here is
          estimated in the meantime.
        </p>
      </section>
    </section>
  );
}

function CompareTableRow({
  row,
  players,
  leaderId,
}: {
  row: CompareRow;
  players: readonly Player[];
  leaderId: number | null;
}) {
  return (
    <tr data-testid={`compare-row-${row.key}`}>
      <th scope="row" className="compare-row-label" title={row.description}>
        {row.label}
      </th>
      {players.map((player) => {
        const leads = leaderId === player.id;
        return (
          <td
            key={player.id}
            className={leads ? "compare-cell compare-cell-lead" : "compare-cell"}
            title={row.cellTitle?.(player)}
          >
            {row.render(player)}
            {leads && (
              <span
                className="compare-lead-mark"
                title="Best of the compared players on this row. On a forecast row this appears only where the gap is larger than the uncertainty."
              >
                best
              </span>
            )}
          </td>
        );
      })}
    </tr>
  );
}

function VerdictPanel({ verdict }: { verdict: ReturnType<typeof buildVerdict> }) {
  return (
    <section className="compare-verdict" data-testid="compare-verdict">
      <h2 className="compare-verdict-headline">{verdict.headline}</h2>
      <dl className="compare-verdict-lines">
        {verdict.lines.map((line) => (
          <div
            key={line.key}
            className={line.decisive ? "compare-verdict-line" : "compare-verdict-line compare-verdict-line-level"}
            data-testid={`compare-verdict-${line.key}`}
            data-decisive={line.decisive ? "true" : "false"}
          >
            <dt>
              {line.heading}
              {!line.decisive && <span className="compare-level-tag">too close to call</span>}
            </dt>
            <dd>{line.statement}</dd>
          </div>
        ))}
      </dl>
      <details className="compare-caveats" data-testid="compare-caveats">
        <summary>How this verdict was reached</summary>
        <ul>
          {verdict.caveats.map((caveat) => (
            <li key={caveat}>{caveat}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
