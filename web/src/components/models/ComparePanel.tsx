import { useState } from "react";
import type { ReactNode } from "react";
import type { ModelsHistory } from "../../contract/types";
import { availableModels } from "../../data/DataProvider";
import type { PublishedData } from "../../data/published";
import { isComparison, modelLabel } from "../../data/registry";
import { compareStrategies } from "../../data/strategyCompare";
import type { StrategyAdvice, StrategyDiff } from "../../data/strategyCompare";
import { formatPoints } from "../../format";
import { ModelBadge } from "./ModelBadge";
import "./models.css";

const NO_DIFF: StrategyDiff = {
  transfersDiffer: false,
  captainDiffers: false,
  viceDiffers: false,
  benchDiffers: false,
  chipDiffers: false,
  xiIn: [],
  xiOut: [],
};

/** A cell that differs from the baseline says so in words as well as in its background. */
function Cell({ differs, children, testId }: { differs: boolean; children: ReactNode; testId?: string }) {
  return (
    <td className={differs ? "differs" : undefined} data-testid={testId}>
      {differs && <span className="visually-hidden">Differs from the baseline. </span>}
      {differs && <span aria-hidden="true">≠ </span>}
      {children}
    </td>
  );
}

/**
 * `/models` comparison: pick any strategies and see this gameweek's advice as differences from the
 * baseline (the champion unless it is deselected), the players they disagree on with the xP their
 * week artefacts carry, and how each has performed. Every published strategy is selected by default.
 */
export function ComparePanel({ data, history }: { data: PublishedData; history: ModelsHistory | null }) {
  const { registry, weeks, plans, players, models } = data;
  const published = registry.entries.filter((e) => e.published);
  const [off, setOff] = useState<ReadonlySet<string>>(new Set());
  const selected = published.map((e) => e.id).filter((id) => !off.has(id));
  const toggle = (id: string) =>
    setOff((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const available = new Set(availableModels(data));
  const comparison = compareStrategies(
    selected.includes(registry.champion) ? registry.champion : (selected[0] ?? registry.champion),
    selected,
    weeks,
    plans,
    players,
  );
  const { advice, diffs, baseline } = comparison;
  const name = (id: number | null) =>
    id == null ? "—" : (players.players.find((p) => p.id === id)?.name ?? `#${id}`);
  const names = (ids: number[]) => ids.map(name).join(", ");
  const gameweek = weeks[baseline]?.deadline.gameweek;
  const label = (id: string) => modelLabel(registry, id);

  const row = (key: string, heading: string, cell: (a: StrategyAdvice, d: StrategyDiff, isBase: boolean) => [boolean, ReactNode]) => (
    <tr key={key}>
      <th scope="row">{heading}</th>
      {advice.map((a) => {
        const isBase = a.id === baseline;
        const [differs, content] = cell(a, diffs[a.id] ?? NO_DIFF, isBase);
        return (
          <Cell key={a.id} differs={!isBase && differs} testId={`compare-${key}-${a.id}`}>
            {content}
          </Cell>
        );
      })}
    </tr>
  );

  const backtest = new Map(history?.summary.map((s) => [s.model, s]) ?? []);
  const live = new Map(models?.season_to_date.map((s) => [s.model, s]) ?? []);

  return (
    <section className="models-page-section" id="models-compare" aria-labelledby="models-compare-heading" data-testid="models-compare">
      <h2 id="models-compare-heading">Compare strategies</h2>
      <fieldset className="compare-pick" data-testid="compare-pick">
        <legend>Strategies to compare</legend>
        {published.map((e) => (
          <label key={e.id} className="compare-pick-item">
            <input
              type="checkbox"
              checked={!off.has(e.id)}
              onChange={() => toggle(e.id)}
              data-testid={`compare-pick-${e.id}`}
            />{" "}
            {e.label}
            {!available.has(e.id) && <span className="history-sub"> (no week published)</span>}
          </label>
        ))}
      </fieldset>

      {advice.length < 2 ? (
        <p className="models-note" data-testid="compare-too-few">
          Select at least two strategies that publish a week to compare them.
        </p>
      ) : (
        <>
          <p className="models-note" data-testid="compare-baseline">
            Baseline: <ModelBadge model={baseline} />
            {isComparison(registry, baseline) ? " — the champion is not selected." : " — live advice."} Differences are
            marked ≠. GW{gameweek}.
          </p>

          <h3 id="compare-advice-heading">This gameweek&apos;s advice</h3>
          <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="compare-advice-heading">
            <table className="models-table" data-testid="compare-advice">
              <thead>
                <tr>
                  <th scope="col">
                    <span className="visually-hidden">Advice</span>
                  </th>
                  {advice.map((a) => (
                    <th scope="col" key={a.id} data-testid={`compare-col-${a.id}`}>
                      {label(a.id)}
                      {a.id === baseline && <span className="history-sub"> (baseline)</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {row("transfers", "Transfers", (a, d) => [
                  d.transfersDiffer,
                  <>
                    {a.transfers.length > 0 ? a.transfers.join(", ") : "Roll (no transfer)"}
                    {a.hitPoints !== 0 ? ` (${a.hitPoints} hit)` : ""}
                  </>,
                ])}
                {row("captain", "Captain", (a, d) => [d.captainDiffers, name(a.captain)])}
                {row("vice", "Vice-captain", (a, d) => [d.viceDiffers, name(a.vice)])}
                {row("chip", "Chip", (a, d) => [d.chipDiffers, a.chip ?? "—"])}
                {row("xp", "Net xP", (a) => [false, a.netXp === null ? "—" : formatPoints(a.netXp)])}
                {row("xi", "XI", (a, d, isBase) => [
                  d.xiIn.length > 0,
                  isBase ? (
                    <>
                      {a.formation ? `${a.formation}: ` : ""}
                      {names(a.starting)}
                    </>
                  ) : d.xiIn.length === 0 ? (
                    "Same XI"
                  ) : (
                    <>
                      In: {names(d.xiIn)}. Out: {names(d.xiOut)}.
                    </>
                  ),
                ])}
                {row("bench", "Bench", (a, d) => [d.benchDiffers, names(a.bench) || "—"])}
              </tbody>
            </table>
          </div>
          {comparison.missing.length > 0 && (
            <p className="models-note">Not compared, no week published: {comparison.missing.map(label).join(", ")}.</p>
          )}

          <h3 id="compare-players-heading">Players they disagree on</h3>
          {comparison.disagreements.length === 0 ? (
            <p className="models-note" data-testid="compare-agree">
              The selected strategies agree on the XI and the captain.
            </p>
          ) : (
            <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="compare-players-heading">
              <table className="models-table" data-testid="compare-players">
                <thead>
                  <tr>
                    <th scope="col">Player</th>
                    {advice.map((a) => (
                      <th scope="col" key={a.id}>
                        {label(a.id)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {comparison.disagreements.map((d) => (
                    <tr key={d.player.id} data-testid={`compare-player-${d.player.id}`}>
                      <th scope="row">
                        {d.player.name} <span className="history-sub">{d.player.position}</span>
                      </th>
                      {advice.map((a) => (
                        <td key={a.id} data-testid={`compare-player-${d.player.id}-${a.id}`}>
                          {d.inXI[a.id] ? "In XI" : "Not in XI"}
                          {d.captainOf.includes(a.id) ? " · captain" : ""}
                          {d.xp[a.id] !== undefined ? ` · xP ${formatPoints(d.xp[a.id])}` : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="models-note">
                xP is the next-gameweek forecast a strategy&apos;s recommended transfers carry; “—” means its week names no
                forecast for that player.
              </p>
            </div>
          )}
        </>
      )}

      <h3 id="compare-history-heading">Historical performance</h3>
      <div className="table-scroll" tabIndex={0} role="region" aria-labelledby="compare-history-heading">
        <table className="models-table" data-testid="compare-history">
          <thead>
            <tr>
              <th scope="col">Strategy</th>
              <th scope="col">
                2025/26 backtest pts/GW
              </th>
              <th scope="col">Δ vs champion / GW</th>
              <th scope="col">2026/27 live total</th>
            </tr>
          </thead>
          <tbody>
            {selected.map((id) => {
              const b = backtest.get(id);
              const l = live.get(id);
              return (
                <tr key={id} data-testid={`compare-history-${id}`}>
                  <th scope="row">{label(id)}</th>
                  <td>{b ? b.mean_per_gameweek.toFixed(2) : "—"}</td>
                  <td>{b?.delta_vs_champion ? b.delta_vs_champion.mean.toFixed(2) : b ? "reference" : "—"}</td>
                  <td>{l ? `${Math.round(l.total)} (${l.gameweeks_scored} GW)` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="models-note">
        The backtest is a walk-forward replay of 2025/26, not real play; a handful of live gameweeks cannot separate the
        strategies. The full history is further down this page.
      </p>
    </section>
  );
}
