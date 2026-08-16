import { useMemo, useState } from "react";
import type { DifficultyScale, FixtureEntry, FixtureGameweek, Fixtures } from "../../contract/types";
import {
  METRICS,
  SORTS,
  bandFor,
  bandRanges,
  buildRuns,
  difficultyOf,
  gameweeksOf,
  horizonOptions,
  sortRuns,
  type Metric,
  type SortKey,
  type TeamRun,
} from "./ticker";
import "./fixtures.css";

/**
 * The fixture ticker (E6-S8, FR-30).
 *
 * Clubs down the side, gameweeks across the top, each cell shaded by how hard the model thinks that
 * fixture is. Three things it does that the official site's ticker does not, each because leaving
 * them out would mislead:
 *
 * **It says what the number means.** The scores here are model-derived, not FPL's static preseason
 * FDR, and they are continuous rather than an integer 1-5. A reader who has seen the official ticker
 * will read a shaded cell as that familiar figure unless told otherwise, so the scale's own
 * published description, the model behind it and the band edges are all on the page rather than in a
 * commit message (DP-09, DP-10). When the model has no ratings yet the panel says so outright rather
 * than presenting a grid of neutral scores as if they were rated (DP-15).
 *
 * **It separates the attacking and defensive halves.** A high-scoring game between two good sides is
 * a good fixture for forwards and a bad one for defenders; a single number cannot say that, and
 * collapsing them is most of what is wrong with one FDR figure. The metric control switches which
 * half is shaded and sorted on.
 *
 * **It never lets a blank hide.** A blank contributes nothing to a run's mean, so a club that plays
 * twice in six can top an "easiest run first" sort while being close to useless. Every row therefore
 * carries its fixture, double and blank counts next to the mean, and a blank cell is marked as a
 * blank rather than left empty — an empty cell is indistinguishable from a rendering bug.
 */
export function FixtureTicker({ fixtures }: { fixtures: Fixtures }) {
  const horizons = horizonOptions(fixtures);
  const fullWindow = horizons[horizons.length - 1];

  const [metric, setMetric] = useState<Metric>("overall");
  const [sort, setSort] = useState<SortKey>("easiest");
  const [horizon, setHorizon] = useState<number>(fullWindow);

  const gameweeks = useMemo(
    () => gameweeksOf(fixtures).slice(0, horizon),
    [fixtures, horizon],
  );
  const rows = useMemo(
    () => sortRuns(buildRuns(fixtures, metric, horizon), sort),
    [fixtures, metric, horizon, sort],
  );

  const metricLabel = METRICS.find((m) => m.key === metric)?.label ?? "Overall";
  const unrated = fixtures.model.teams_rated === 0;

  return (
    <section className="ticker" data-testid="fixture-ticker">
      <header className="ticker-head">
        <h2>Fixture ticker</h2>
        <p className="ticker-window">
          Gameweeks {gameweeks[0]} to {gameweeks[gameweeks.length - 1]}, {rows.length} clubs.
        </p>
      </header>

      {unrated ? (
        <p className="ticker-unrated" data-testid="ticker-unrated">
          The team-strength model has no ratings yet, so every fixture scores close to{" "}
          {fixtures.scale.neutral} and the only thing separating them is home advantage. Read this
          grid as "not yet known", not as "all fixtures are equal".
        </p>
      ) : null}

      <div className="ticker-controls">
        <label className="ticker-control">
          <span>Difficulty for</span>
          <select
            data-testid="ticker-metric"
            value={metric}
            onChange={(event) => setMetric(event.target.value as Metric)}
          >
            {METRICS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="ticker-control">
          <span>Sort by</span>
          <select
            data-testid="ticker-sort"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortKey)}
          >
            {SORTS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="ticker-control">
          <span>Over the next</span>
          <select
            data-testid="ticker-horizon"
            value={horizon}
            onChange={(event) => setHorizon(Number(event.target.value))}
          >
            {horizons.map((option) => (
              <option key={option} value={option}>
                {option} gameweeks
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="ticker-metric-help" data-testid="ticker-metric-help">
        {METRICS.find((m) => m.key === metric)?.help}
      </p>

      <Legend scale={fixtures.scale} />

      {/* The grid scrolls inside its own box: a wide table must never make the page scroll
          sideways, which is the rule the week and plan tables already follow. */}
      <div className="ticker-scroll">
        <table className="ticker-grid">
          <caption className="ticker-caption">
            {metricLabel} difficulty by gameweek. Lower is easier. Two chips in a cell is a double
            gameweek; a cell marked blank is a gameweek this club does not play.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="ticker-club-head">
                Club
              </th>
              {gameweeks.map((gameweek) => (
                <th scope="col" key={gameweek}>
                  GW{gameweek}
                </th>
              ))}
              <th scope="col">Mean</th>
              <th scope="col">Run</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <TickerRow key={row.teamId} row={row} metric={metric} scale={fixtures.scale} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="ticker-provenance" data-testid="ticker-provenance">
        {fixtures.scale.description} Scores come from {fixtures.model.name}, fitted on{" "}
        {fixtures.model.teams_rated} clubs, with a league mean of{" "}
        {fixtures.model.league_mean_goals.toFixed(2)} goals per club per match and a home advantage
        multiplier of {fixtures.model.home_advantage.toFixed(2)}. They are model expectations, not
        FPL's own fixture difficulty ratings, and they change as the season teaches the model
        something.
      </p>
    </section>
  );
}

function TickerRow({
  row,
  metric,
  scale,
}: {
  row: TeamRun;
  metric: Metric;
  scale: DifficultyScale;
}) {
  const meanBand = row.mean === null ? null : bandFor(row.mean, scale);

  return (
    <tr data-testid="ticker-row" data-team={row.team}>
      <th scope="row" className="ticker-club">
        <span className="ticker-club-short">{row.team}</span>
        <span className="ticker-club-name">{row.name}</span>
      </th>

      {row.gameweeks.map((gameweek) => (
        <Cell
          key={gameweek.gameweek}
          team={row.team}
          gameweek={gameweek}
          metric={metric}
          scale={scale}
        />
      ))}

      <td className="ticker-mean" data-testid={`ticker-mean-${row.team}`}>
        {row.mean === null ? (
          <span className="ticker-mean-absent">no fixtures</span>
        ) : (
          <span
            className="ticker-chip"
            data-band={meanBand?.level}
            title={`Mean difficulty ${row.mean.toFixed(2)} — ${meanBand?.label}`}
          >
            <span className="ticker-score">{row.mean.toFixed(2)}</span>
            <span className="ticker-band-label">{meanBand?.label}</span>
          </span>
        )}
      </td>

      <td className="ticker-counts" data-testid={`ticker-counts-${row.team}`}>
        {row.fixtureCount} {row.fixtureCount === 1 ? "fixture" : "fixtures"}
        {row.doubleCount > 0 ? `, ${row.doubleCount} double` : ""}
        {row.doubleCount > 1 ? "s" : ""}
        {row.blankCount > 0 ? `, ${row.blankCount} blank` : ""}
        {row.blankCount > 1 ? "s" : ""}
      </td>
    </tr>
  );
}

function Cell({
  team,
  gameweek,
  metric,
  scale,
}: {
  team: string;
  gameweek: FixtureGameweek;
  metric: Metric;
  scale: DifficultyScale;
}) {
  const testId = `ticker-cell-${team}-GW${gameweek.gameweek}`;

  // Trust the fixtures actually present over the flags: a cell that says "double" and shows one
  // chip is the ambiguity this view exists to remove. The flags are asserted against the fixture
  // count in the tests instead.
  if (gameweek.fixtures.length === 0) {
    return (
      <td className="ticker-cell ticker-cell-blank" data-testid={testId} data-blank="true">
        <span className="ticker-chip" data-band="blank" title={`No fixture in GW${gameweek.gameweek}`}>
          <span className="ticker-score" aria-hidden="true">
            —
          </span>
          <span className="ticker-band-label">Blank</span>
        </span>
      </td>
    );
  }

  const isDouble = gameweek.fixtures.length > 1;

  return (
    <td
      className={`ticker-cell${isDouble ? " ticker-cell-double" : ""}`}
      data-testid={testId}
      data-double={isDouble ? "true" : undefined}
    >
      {isDouble ? (
        <span className="ticker-double-flag" data-testid={`ticker-double-${team}-GW${gameweek.gameweek}`}>
          Double
        </span>
      ) : null}
      {gameweek.fixtures.map((fixture, index) => (
        <Chip
          key={`${fixture.opponent_id}-${index}`}
          fixture={fixture}
          metric={metric}
          scale={scale}
        />
      ))}
    </td>
  );
}

function Chip({
  fixture,
  metric,
  scale,
}: {
  fixture: FixtureEntry;
  metric: Metric;
  scale: DifficultyScale;
}) {
  const score = difficultyOf(fixture, metric);
  const band = bandFor(score, scale);
  const venue = fixture.at_home ? "home" : "away";

  return (
    <span
      className="ticker-chip"
      data-band={band.level}
      data-testid="ticker-fixture"
      // The derivation sits in the tooltip rather than being hidden entirely: the difficulty is a
      // transformation of these two expected-goals figures, and a score you cannot check is a score
      // you have to take on trust (DP-09).
      title={`${fixture.opponent} (${venue}) — ${band.label}, ${score.toFixed(2)}. Model expects ${fixture.expected_goals_for.toFixed(2)} goals for and ${fixture.expected_goals_against.toFixed(2)} against.`}
    >
      <span className="ticker-opponent">
        {fixture.opponent}
        <span className="ticker-venue">{fixture.at_home ? " (H)" : " (A)"}</span>
      </span>
      <span className="ticker-score">{score.toFixed(1)}</span>
    </span>
  );
}

/**
 * What the shading means, in words and numbers.
 *
 * On the page rather than behind a tooltip because the whole grid is unreadable without it — and
 * because colour must never be the only carrier of the meaning (E6-S9). Every band names itself and
 * gives its range, so the grid is still legible in greyscale, to a colour-blind reader, and to a
 * screen reader reading the cell titles.
 */
function Legend({ scale }: { scale: DifficultyScale }) {
  return (
    <ul className="ticker-legend" data-testid="ticker-legend">
      {bandRanges(scale).map((band) => (
        <li key={band.level} className="ticker-legend-item">
          <span className="ticker-chip" data-band={band.level}>
            <span className="ticker-score">
              {band.from.toFixed(1)}–{band.to.toFixed(1)}
            </span>
          </span>
          <span className="ticker-legend-label">{band.label}</span>
        </li>
      ))}
      <li className="ticker-legend-item">
        <span className="ticker-chip" data-band="blank">
          <span className="ticker-score" aria-hidden="true">
            —
          </span>
        </span>
        <span className="ticker-legend-label">Blank — no fixture</span>
      </li>
    </ul>
  );
}
