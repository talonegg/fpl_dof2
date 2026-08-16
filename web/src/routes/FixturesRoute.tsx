import { FixtureTicker } from "../components/fixtures/FixtureTicker";
import { useFixtures } from "../components/fixtures/useFixtures";
import "../components/fixtures/fixtures.css";

/**
 * `/fixtures` — the fixture ticker (E6-S8, FR-30).
 *
 * The grid is fetched here rather than by the shell because it is not on the first-paint path
 * (DL-37); everything about that, including why an absent artefact is a normal answer, is on
 * `useFixtures`.
 */
export function FixturesRoute() {
  const { state, retry } = useFixtures();

  if (state.status === "loading") {
    return (
      <section className="ticker-status" data-testid="fixtures-loading">
        <p>Loading the fixture grid…</p>
      </section>
    );
  }

  if (state.status === "absent") {
    return (
      <section className="ticker-status" data-testid="fixtures-absent">
        <h2>Fixture ticker</h2>
        <p>
          No fixture grid has been published yet. It is written by the publish stage alongside the
          rest of the contract, so it appears with the next successful run.
        </p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="ticker-status" data-testid="fixtures-error">
        <h2>Fixture ticker</h2>
        <p>The fixture grid could not be loaded: {state.message}</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }

  return <FixtureTicker fixtures={state.fixtures} />;
}
