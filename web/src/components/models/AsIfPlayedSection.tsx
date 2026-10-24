import { unready, useArtefact } from "../../data/store";
import { ModelHistoryView } from "../history/ModelHistoryView";
import "./models.css";

/** DL-97's label, shown wherever the in-sample ladder is. */
export const IN_SAMPLE_LABEL = "In-sample: today's models replayed on past gameweeks; not evidence of skill";

const ABSENT =
  "This season has not been replayed yet: the weekly job replays today's models once a gameweek is finished.";

/**
 * The live season as if each model had played it (ORC-13, DL-97), from `as_if_played.json`: today's
 * models, each on its own team from GW1, in the models history's ladder and tables. In-sample,
 * and labelled so. Beside the ladder of each model's advice on your squad; not on the replay's tab.
 */
export function AsIfPlayedSection() {
  const { state } = useArtefact("as_if_played");
  const { state: replay } = useArtefact("models_history");
  if (state.status === "loading") return <p data-testid="as-if-played-loading">Loading the as-if-played season…</p>;
  if (state.status !== "ready") {
    return (
      <section className="models-season" data-testid="as-if-played-absent">
        <h2>This season, as if each model had played</h2>
        <p>{unready(state, ABSENT)}</p>
      </section>
    );
  }
  const other = replay.status === "ready" ? `the ${replay.data.season} replay, on its own tab` : "the backtest's replay";
  return (
    <ModelHistoryView
      history={state.data}
      heading={{
        testId: "as-if-played",
        title: `${state.data.season}, as if each model had played`,
        badge: "In-sample",
        badgeClass: "season-phase-prospective",
        note: (
          <>
            <strong data-testid="in-sample-label">{IN_SAMPLE_LABEL}.</strong> Each model, with the weights it is fitted
            with today, playing its own team from GW1, picked under the budget, with its own transfers, hits and chips:
            not your squad (the ladder above) and not {other}.
          </>
        ),
      }}
    />
  );
}
