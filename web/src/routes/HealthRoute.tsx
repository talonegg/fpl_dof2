import { HealthPanel } from "../components/health/HealthPanel";
import { useHealth } from "../components/health/useHealth";
import "../components/health/health.css";

/**
 * `/health` — the data health page (E7-S6, FR-33, NFR-07, DL-41).
 *
 * `health.json` is fetched here rather than by the shell, like `fixtures.json` and `league.json`
 * (DL-37, DL-40). The difference is *why*: those two are lazy because of what they cost, this one
 * because of when it is wanted — it is the page you open when something looks wrong, and the shell's
 * eager load is the path every other page waits behind.
 *
 * **This route has an obligation the others do not.** It is the one view whose whole purpose is to
 * be useful when the published data is in a bad state, so every failure mode below renders a page
 * that says something rather than an apology: absent, malformed and failed-to-load are three
 * different diagnoses and are reported as three different things (DP-15).
 */
export function HealthRoute() {
  const { state, retry } = useHealth();

  if (state.status === "loading") {
    return (
      <section className="health-status" data-testid="health-loading">
        <p>Loading the data health report…</p>
      </section>
    );
  }

  if (state.status === "absent") {
    return (
      <section className="health-status" data-testid="health-absent">
        <h2>No health report published</h2>
        <p>
          Every run that publishes anything publishes this report too, so its absence means one of
          two things and this page cannot tell them apart:
        </p>
        <ul>
          <li>
            the site was built against an older published data directory, from before the report
            existed; or
          </li>
          <li>the last run could not read its own manifest, and so had nothing to report.</li>
        </ul>
        <p>
          Either way the rest of the app is reading whatever was published last. The report appears
          with the next successful run.
        </p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }

  if (state.status === "malformed") {
    return (
      <section className="health-status" data-testid="health-malformed">
        <h2>The health report could not be read</h2>
        <p>
          A file was served for this report, but it is not the shape this app understands — a
          truncated write, or a different file at the same address. It is being ignored rather than
          rendered, because a partly-read status page is more misleading than none.
        </p>
        <p>
          Treat this as a failure in its own right: whatever wrote it did not finish. The rest of
          the app is unaffected and is reading the artefacts published alongside it.
        </p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="health-status" data-testid="health-error">
        <h2>Data health</h2>
        <p>The health report could not be loaded: {state.message}</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </section>
    );
  }

  return <HealthPanel health={state.health} />;
}
