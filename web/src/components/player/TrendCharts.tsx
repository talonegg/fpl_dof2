/**
 * This season's trends for one player: returns, minutes, expected versus actual, price, ownership.
 *
 * Everything here is **measured**, not forecast, so nothing here carries an uncertainty band — a
 * band around a number that was counted would be a fabrication (DL-37). The forecast on this page
 * lives in the header and the decomposition, and that is where the bands are.
 *
 * The empty case is not an error. Before the first gameweek is scored `gameweeks_played` is 0 and
 * every `gameweeks` array is empty, which is a normal preseason state (DL-20) — but the price series
 * is populated from the first day the pipeline observed a price, so the price and ownership charts
 * have something to show when the performance charts do not. The two are therefore gated separately.
 */

import type { History, Player } from "../../contract/types";
import { fetchHistory } from "../../data/api";
import { BarChart } from "../charts/BarChart";
import { LineChart } from "../charts/LineChart";
import type { ChartSeries, SeriesVariant } from "../charts/LineChart";
import { buildTrends, coverageStatement, findPlayerHistory } from "./trends";
import type { TrendSeries } from "./trends";
import { useLazyArtefact } from "./useLazyArtefact";

function toChartSeries(series: TrendSeries, variant: SeriesVariant): ChartSeries {
  return { key: series.key, label: series.label, points: series.points, variant };
}

function Charts({ history, player }: { history: History; player: Player }) {
  const playerHistory = findPlayerHistory(history, player.id);

  if (playerHistory === null) {
    return (
      <p className="panel-note" data-testid="trends-missing">
        No history has been published for {player.name} this season.
      </p>
    );
  }

  const trends = buildTrends(playerHistory, history.gameweeks_played);
  const gw = (x: number) => `GW${Math.round(x)}`;
  const dateAt = (index: number) => trends.priceDates[Math.round(index)] ?? "";

  return (
    <div data-testid="trend-charts">
      {!trends.hasGameweeks && (
        <p className="panel-note" data-testid="trends-no-gameweeks">
          {history.gameweeks_played === 0
            ? `No gameweek has been scored in ${history.season} yet, so there is nothing to plot for returns, minutes or expected goals.`
            : `${player.name} has not featured in any of the ${history.gameweeks_played} gameweeks scored so far.`}
        </p>
      )}

      {trends.hasGameweeks && (
        <>
          <BarChart
            testId="chart-points"
            title="Points by gameweek"
            summary={`${trends.totals.points} points across ${trends.points.length} gameweeks, ${trends.totals.goals} goals and ${trends.totals.assists} assists. A double gameweek is summed into one bar.`}
            data={trends.points.map((bar) => ({
              x: bar.gameweek,
              y: bar.value,
              label: `GW${bar.gameweek}`,
              title: `GW${bar.gameweek}: ${bar.value} points`,
            }))}
          />

          <BarChart
            testId="chart-minutes"
            title="Minutes by gameweek"
            summary={`${trends.totals.minutes} minutes across ${trends.minutes.length} gameweeks. Minutes are the single strongest constraint on what a player can return.`}
            data={trends.minutes.map((bar) => ({
              x: bar.gameweek,
              y: bar.value,
              label: `GW${bar.gameweek}`,
              title: `GW${bar.gameweek}: ${bar.value} minutes`,
            }))}
          />

          <LineChart
            testId="chart-attacking"
            title="Expected versus actual returns, cumulative"
            summary={
              trends.totals.expectedGoals === null
                ? `${trends.totals.goals} goals and ${trends.totals.assists} assists. No expected-goals data has been measured, so there is nothing to compare them against.`
                : `${trends.totals.goals} goals against ${trends.totals.expectedGoals.toFixed(2)} expected, and ${trends.totals.assists} assists against ${(trends.totals.expectedAssists ?? 0).toFixed(2)} expected. A gap between the two is the case for regression, in whichever direction it runs.`
            }
            series={trends.attacking.series.map((series, index) =>
              toChartSeries(series, (index % 3) as SeriesVariant),
            )}
            xTickLabel={gw}
            minSpan={1}
          />
          {coverageStatement(trends.attacking.coverage, "expected-goals") && (
            <p className="panel-note" data-testid="trends-xg-coverage">
              {coverageStatement(trends.attacking.coverage, "expected-goals")}
            </p>
          )}

          {trends.defensive && (
            <LineChart
              testId="chart-defensive"
              title="Defensive contribution, cumulative"
              summary="Defensive actions counted for this player's position, and the points they earned. Points are all-or-nothing at a per-position threshold, so actions and points do not move together."
              series={trends.defensive.series.map((series, index) =>
                toChartSeries(series, (index % 3) as SeriesVariant),
              )}
              xTickLabel={gw}
            />
          )}
        </>
      )}

      {trends.hasPrices ? (
        <>
          <LineChart
            testId="chart-price"
            title="Price"
            summary={`${trends.price.points.length} price observations between ${history.observed_from ?? "the first observation"} and ${history.observed_to ?? "the most recent"}. Recorded only when the price changed, so a flat run is a run of unchanged days rather than missing data.`}
            series={[toChartSeries(trends.price, 0)]}
            xTickLabel={dateAt}
            yTickLabel={(y) => `£${y.toFixed(1)}m`}
            includeZero={false}
            minSpan={0.4}
          />

          <LineChart
            testId="chart-ownership"
            title="Selected by"
            summary="FPL's own published ownership figure, as a percentage of all managers. This is 'selected by', never effective ownership — the two are different quantities and only one of them is observable (DL-24)."
            series={[toChartSeries(trends.ownership, 1)]}
            xTickLabel={dateAt}
            yTickLabel={(y) => `${y.toFixed(1)}%`}
            includeZero={false}
            minSpan={1}
          />
        </>
      ) : (
        <p className="panel-note" data-testid="trends-no-prices">
          No price or ownership observations have been recorded yet. FPL publishes only the current
          price, so history exists only for the days something recorded it.
        </p>
      )}
    </div>
  );
}

export function TrendCharts({ player }: { player: Player }) {
  const state = useLazyArtefact<History>(
    fetchHistory,
    "Season history is not part of this published data set.",
  );

  return (
    <section className="player-panel" data-testid="trend-panel">
      <h3>This season</h3>
      {state.status === "loading" && <p className="panel-note">Loading this season's history…</p>}
      {state.status === "unavailable" && (
        <p className="panel-note" data-testid="trends-unavailable">
          Trends are unavailable: {state.reason}
        </p>
      )}
      {state.status === "ready" && <Charts history={state.data} player={player} />}
    </section>
  );
}
