/**
 * Trends and forecasts across the compared players (E6-S5, FR-29) — the slot E6-S4 left open.
 *
 * Two halves, and the split matters:
 *
 * **The forecast**, drawn from `players.json`, which the view already has. This is the only place in
 * the app that charts a predicted number, so it is the only place E6-S5's rule can be broken:
 * "uncertainty must be visible on every forecast chart". `IntervalChart` draws the ±2σ band as the
 * mark and the mean as a tick inside it, which makes two overlapping forecasts *look* the way the
 * verdict above already *says* they are. The picture and the prose agree because they are computed
 * from the same two published fields.
 *
 * **The history**, from `history.json`, fetched lazily on this route (DL-37) exactly as
 * `/player/:id` fetches it, through the same hook. Everything here is measured, so nothing here
 * carries a band: an error bar around a counted return would be a fabrication (DL-37).
 *
 * There is no chart of expected points *forward over gameweeks*, deliberately. The contract publishes
 * `xp_next` for one gameweek and `xp_horizon` as an aggregate over the whole horizon, and no
 * per-gameweek forecast path between them. Spreading the horizon across its gameweeks to draw a line
 * would invent a derivation the pipeline never made and present it with a confidence nothing earned
 * (DP-09). When the pipeline publishes a per-gameweek forecast series, this is where it goes.
 */

import type { History, Player } from "../../contract/types";
import { fetchHistory } from "../../data/api";
import { formatXpRange } from "../../format";
import { IntervalChart } from "../charts/IntervalChart";
import type { IntervalDatum } from "../charts/IntervalChart";
import { LineChart } from "../charts/LineChart";
import type { ChartSeries, SeriesVariant } from "../charts/LineChart";
import { useLazyArtefact } from "../player/useLazyArtefact";
import { buildCompareTrends } from "./overlays";
import type { PlayerTrendLines } from "./overlays";

/** One variant per compared player, held constant across every chart in the section. */
function variantFor(index: number): SeriesVariant {
  return (index % 4) as SeriesVariant;
}

/**
 * A player's line for one quantity, or null when there is nothing measured for them.
 *
 * Null rather than an empty series: an empty line still earns a legend entry, and a legend entry for
 * a player with no data reads as a player who scored nothing.
 */
function lineFor(
  line: PlayerTrendLines,
  index: number,
  pick: (line: PlayerTrendLines) => { x: number; y: number }[],
): ChartSeries | null {
  const points = pick(line);
  if (points.length === 0) return null;
  return {
    key: String(line.playerId),
    label: line.name,
    points,
    variant: variantFor(index),
  };
}

function seriesFor(
  lines: readonly PlayerTrendLines[],
  pick: (line: PlayerTrendLines) => { x: number; y: number }[],
): ChartSeries[] {
  return lines
    .map((line, index) => lineFor(line, index, pick))
    .filter((series): series is ChartSeries => series !== null);
}

function ForecastCharts({
  players,
  horizonGameweeks,
}: {
  players: readonly Player[];
  horizonGameweeks?: number;
}) {
  const next: IntervalDatum[] = players.map((player) => ({
    key: String(player.id),
    label: player.name,
    mean: player.xp_next,
    sd: player.xp_next_sd,
    statement: `${player.name}: ${formatXpRange(player.xp_next, player.xp_next_sd)}`,
  }));

  const horizon: IntervalDatum[] = players.map((player) => ({
    key: String(player.id),
    label: player.name,
    mean: player.xp_horizon,
    sd: player.xp_horizon_sd,
    statement: `${player.name}: ${formatXpRange(player.xp_horizon, player.xp_horizon_sd)}`,
  }));

  const weeks =
    horizonGameweeks === undefined ? "the horizon" : `the next ${horizonGameweeks} gameweeks`;

  return (
    <>
      <IntervalChart
        testId="compare-chart-xp-next"
        title="Expected points, next gameweek"
        summary="The bar is the range each forecast makes plausible, two standard deviations either side of the mean; the upright tick is the mean itself. Where two bars overlap heavily the forecast does not separate those players, whatever the order of the means."
        data={next}
      />
      <IntervalChart
        testId="compare-chart-xp-horizon"
        title={`Expected points, over ${weeks}`}
        summary="The same reading over the whole horizon. Uncertainty compounds across gameweeks, so these bars are wider than the single-gameweek ones and a lead here needs to be larger before it means anything."
        data={horizon}
      />
      <p className="compare-note" data-testid="compare-forecast-caveat">
        These two are forecasts, not measurements. Everything below them is measured, and carries no
        band for that reason.
      </p>
    </>
  );
}

function HistoryCharts({ history, players }: { history: History; players: readonly Player[] }) {
  const trends = buildCompareTrends(history, players);
  const gw = (x: number) => `GW${Math.round(x)}`;
  const dateAt = (index: number) => trends.priceDates[Math.round(index)] ?? "";

  return (
    <div data-testid="compare-trend-charts">
      {trends.absentNames.length > 0 && (
        <p className="compare-note" data-testid="compare-trends-absent">
          The published history does not carry {trends.absentNames.join(" or ")}, so{" "}
          {trends.absentNames.length === 1 ? "that player is" : "those players are"} missing from the
          charts below rather than plotted at zero.
        </p>
      )}

      {!trends.anyGameweeks ? (
        <p className="compare-subnote" data-testid="compare-trends-no-gameweeks">
          {trends.gameweeksPlayed === 0
            ? `No gameweek has been scored in ${history.season} yet, so there is nothing to plot for points, minutes or defensive contributions.`
            : `None of these players has featured in the ${trends.gameweeksPlayed} gameweeks scored so far.`}
        </p>
      ) : (
        <>
          {trends.notFeaturedNames.length > 0 && (
            <p className="compare-subnote" data-testid="compare-trends-not-featured">
              {trends.notFeaturedNames.join(" and ")}{" "}
              {trends.notFeaturedNames.length === 1 ? "has" : "have"} not featured in a scored
              gameweek, so {trends.notFeaturedNames.length === 1 ? "that line is" : "those lines are"}{" "}
              absent from the performance charts below.
            </p>
          )}

          <LineChart
            testId="compare-chart-points"
            title="Points, cumulative"
            summary="Total FPL points to date, accumulating by gameweek. Cumulative rather than per gameweek because the question here is who has delivered more and when the order changed, which a set of crossing weekly spikes hides. A double gameweek is summed into its own gameweek."
            series={seriesFor(trends.lines, (line) => line.points)}
            xTickLabel={gw}
          />

          <LineChart
            testId="compare-chart-minutes"
            title="Minutes, cumulative"
            summary="Minutes on the pitch, accumulating. The constraint under every other series here: a player cannot return points they were not on to earn, so a gap that opens here explains most gaps elsewhere."
            series={seriesFor(trends.lines, (line) => line.minutes)}
            xTickLabel={gw}
          />

          {trends.anyDefensive && (
            <LineChart
              testId="compare-chart-defensive"
              title="Defensive contributions, cumulative"
              summary="Defensive actions counted for each player's position, accumulating. Positions are scored against different thresholds, so compare the slopes between players of the same position and read across positions with care. A gameweek with no measurement is skipped, not counted as none."
              series={seriesFor(trends.lines, (line) => line.defensive)}
              xTickLabel={gw}
            />
          )}
        </>
      )}

      {trends.anyPrices ? (
        <LineChart
          testId="compare-chart-price"
          title="Price"
          summary="Price over the observation dates of all the compared players combined, so a change in one lines up with what the others were doing that day. Recorded only when a price changed, and carried forward in between — a flat run is a run of unchanged days, not missing data. A line starts where that player was first observed."
          series={seriesFor(trends.lines, (line) => line.price)}
          xTickLabel={dateAt}
          includeZero={false}
          minSpan={0.4}
          yTickLabel={(y) => `£${y.toFixed(1)}m`}
        />
      ) : (
        <p className="compare-subnote" data-testid="compare-trends-no-prices">
          No price observations have been recorded for these players yet. FPL publishes only the
          current price, so history exists only for the days something recorded it.
        </p>
      )}
    </div>
  );
}

export function CompareTrends({
  players,
  horizonGameweeks,
}: {
  players: readonly Player[];
  horizonGameweeks?: number;
}) {
  const state = useLazyArtefact<History>(
    fetchHistory,
    "Season history is not part of this published data set.",
  );

  return (
    <section className="compare-trends" data-testid="compare-trends">
      <h2>Forecasts and trends</h2>

      {/* Above the fetch on purpose: the forecast comes from data the page already has, so a slow
          or absent history.json must not delay or remove it (DP-15). */}
      <ForecastCharts players={players} horizonGameweeks={horizonGameweeks} />

      {state.status === "loading" && (
        <p className="compare-subnote" data-testid="compare-trends-loading">
          Loading this season's history…
        </p>
      )}
      {state.status === "unavailable" && (
        <p className="compare-subnote" data-testid="compare-trends-unavailable">
          Trends are unavailable: {state.reason}
        </p>
      )}
      {state.status === "ready" && <HistoryCharts history={state.data} players={players} />}
    </section>
  );
}
