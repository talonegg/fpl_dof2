import type { Players, Week } from "../../contract/types";
import { diffModels } from "../../data/modelDiff";
import { MODEL_DESCRIPTIONS } from "../../data/model";
import type { ModelChoice } from "../../data/model";
import { formatPoints } from "../../format";
import { ModelBadge } from "./ModelBadge";
import "./models.css";

/** Side-by-side champion vs challenger: transfers, captain/vice and XI, differences highlighted. */
export function ModelDiffView({
  champion,
  challenger,
  players,
}: {
  champion: Week | null;
  challenger: Week | null;
  players: Players;
}) {
  if (!champion || champion.skipped) {
    return (
      <section className="model-diff" data-testid="model-diff-empty">
        <h2>Champion vs challenger</h2>
        <p>No champion recommendation is published this week, so there is nothing to compare.</p>
      </section>
    );
  }
  if (!challenger || challenger.skipped) {
    return (
      <section className="model-diff" data-testid="model-diff-missing">
        <h2>Champion vs challenger</h2>
        <p>
          The challenger was not published this run (it is optional and never blocks the
          champion). Only the champion&apos;s recommendation is available.
        </p>
      </section>
    );
  }
  const diff = diffModels(champion, challenger, players);
  const onlyA = new Set(diff.onlyChampionXI.map((p) => p.id));
  const onlyB = new Set(diff.onlyChallengerXI.map((p) => p.id));
  const name = (id: number | null | undefined) =>
    id == null ? "—" : (players.players.find((p) => p.id === id)?.name ?? `#${id}`);

  const column = (role: ModelChoice, week: Week, only: Set<number>) => {
    const rec = week.recommendation;
    const adv = week.advised;
    return (
      <div className={`model-diff-col model-diff-col-${role}`} data-testid={`model-diff-${role}`}>
        <h3>
          <ModelBadge model={role} /> <span className="model-diff-sub">{MODEL_DESCRIPTIONS[role]}</span>
        </h3>
        <div className={`model-diff-row${diff.transfersDiffer ? " differs" : ""}`}>
          <span className="model-diff-key">Transfers</span>
          <span data-testid={`model-diff-${role}-transfers`}>
            {rec?.moves && rec.moves.length > 0
              ? rec.moves.map((m) => `${m.out.web_name} → ${m.in.web_name}`).join(", ")
              : "Roll (no transfer)"}
            {rec && rec.hit_points !== 0 ? ` (${rec.hit_points} hit)` : ""}
          </span>
        </div>
        <div className={`model-diff-row${diff.captainDiffers ? " differs" : ""}`}>
          <span className="model-diff-key">Captain</span>
          <span data-testid={`model-diff-${role}-captain`}>{name(adv?.captain)}</span>
        </div>
        <div className={`model-diff-row${diff.viceDiffers ? " differs" : ""}`}>
          <span className="model-diff-key">Vice</span>
          <span>{name(adv?.vice_captain)}</span>
        </div>
        <div className="model-diff-row">
          <span className="model-diff-key">Net xP</span>
          <span>{rec ? formatPoints(rec.net_expected_points) : "—"}</span>
        </div>
        <div className="model-diff-row model-diff-xi">
          <span className="model-diff-key">XI {adv?.formation ? `(${adv.formation})` : ""}</span>
          <ul>
            {(adv?.starting ?? []).map((id) => (
              <li
                key={id}
                className={only.has(id) ? "differs" : ""}
                data-testid={only.has(id) ? `model-diff-${role}-only` : undefined}
              >
                {name(id)}
                {id === adv?.captain ? " (C)" : id === adv?.vice_captain ? " (V)" : ""}
              </li>
            ))}
          </ul>
        </div>
        <div className="model-diff-row">
          <span className="model-diff-key">Bench</span>
          <span>{(adv?.bench_order ?? []).map(name).join(", ") || "—"}</span>
        </div>
      </div>
    );
  };

  return (
    <section className="model-diff" data-testid="model-diff">
      <h2>Champion vs challenger</h2>
      <p className="model-diff-summary" data-testid="model-diff-summary">
        {diff.differenceCount === 0
          ? "Both models agree on transfers, captaincy and the XI."
          : [
              diff.transfersDiffer ? "transfers differ" : null,
              diff.captainDiffers ? "captain differs" : null,
              diff.viceDiffers ? "vice differs" : null,
              diff.onlyChampionXI.length > 0
                ? `${diff.onlyChampionXI.length} XI change(s)`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
      </p>
      <div className="model-diff-grid">
        {column("champion", champion, onlyA)}
        {column("challenger", challenger, onlyB)}
      </div>
    </section>
  );
}
