/**
 * The player's upcoming fixtures, rated by the model rather than by FPL's static FDR.
 *
 * Degrades in four ways, all of them visible (DP-15): the grid may still be loading, it may be
 * absent from the published data, it may not carry this player's club, and the difficulty model may
 * have no team ratings at all. The last is the one that would otherwise be invisible — an unrated
 * model produces a grid that looks exactly like a rated one, separated only by home advantage, and
 * presenting that as a considered rating is worse than showing nothing (DP-09).
 */

import type { Player } from "../../contract/types";
import { fetchFixtures } from "../../data/api";
import { formatLocalDateTime } from "../../format";
import { BAND_LABELS, buildFixtureRun, difficultyBasisLabel, runStatement } from "./fixtureRun";
import type { RunFixture } from "./fixtureRun";
import { useLazyArtefact } from "./useLazyArtefact";
import type { Fixtures } from "../../contract/types";

function FixtureCell({ fixture }: { fixture: RunFixture }) {
  const venue = fixture.atHome ? "home" : "away";
  const title = [
    `GW${fixture.gameweek}: ${fixture.atHome ? "vs" : "away to"} ${fixture.opponent}`,
    `${BAND_LABELS[fixture.band]} (${fixture.difficulty.toFixed(2)})`,
    fixture.kickoffUtc ? formatLocalDateTime(fixture.kickoffUtc) : "kick-off time not confirmed",
  ].join(" — ");

  return (
    <li className={`fixture-cell fixture-band-${fixture.band}`} title={title}>
      <span className="fixture-gw">GW{fixture.gameweek}</span>
      <span className="fixture-opponent">
        {fixture.opponent}
        {/* Venue as a letter as well as a case convention: "ARS" versus "ars" is not a distinction
            a reader should have to notice. */}
        <span className="fixture-venue" aria-hidden="true">
          {fixture.atHome ? "H" : "A"}
        </span>
        <span className="visually-hidden">{venue}</span>
      </span>
      <span className="fixture-difficulty">{fixture.difficulty.toFixed(1)}</span>
    </li>
  );
}

function Run({ fixtures, player }: { fixtures: Fixtures; player: Player }) {
  const run = buildFixtureRun(fixtures, player);

  if (run === null) {
    return (
      <p className="panel-note" data-testid="fixture-run-missing">
        The published fixture grid does not cover {player.team}, so there is no fixture run to show.
      </p>
    );
  }

  return (
    <div data-testid="fixture-run">
      {run.unrated && (
        <p className="panel-warning" data-testid="fixture-run-unrated">
          The difficulty model has not rated any club yet this season, so these fixtures differ only
          by home advantage. Read them as placeholders, not as ratings.
        </p>
      )}
      <ol className="fixture-run-list">
        {run.gameweeks.map((gameweek) =>
          gameweek.isBlank ? (
            <li key={gameweek.gameweek} className="fixture-cell fixture-blank">
              <span className="fixture-gw">GW{gameweek.gameweek}</span>
              <span className="fixture-opponent">Blank</span>
              <span className="fixture-difficulty">—</span>
            </li>
          ) : (
            gameweek.fixtures.map((fixture) => (
              <FixtureCell
                key={`${gameweek.gameweek}-${fixture.indexInGameweek}`}
                fixture={fixture}
              />
            ))
          ),
        )}
      </ol>
      <p className="panel-note">{runStatement(run, player.position)}</p>
      <p className="panel-note">
        Lower is easier. Rated on {difficultyBasisLabel(player.position)}, because that is the half of
        the fixture a {player.position} is paid for. {run.scale.description}
      </p>
    </div>
  );
}

export function FixtureRunPanel({ player }: { player: Player }) {
  const state = useLazyArtefact<Fixtures>(
    fetchFixtures,
    "The fixture grid is not part of this published data set.",
  );

  return (
    <section className="player-panel" data-testid="fixture-run-panel">
      <h3>Upcoming fixtures</h3>
      {state.status === "loading" && <p className="panel-note">Loading the fixture grid…</p>}
      {state.status === "unavailable" && (
        <p className="panel-note" data-testid="fixture-run-unavailable">
          Fixture difficulty is unavailable: {state.reason}
        </p>
      )}
      {state.status === "ready" && <Run fixtures={state.data} player={player} />}
    </section>
  );
}
