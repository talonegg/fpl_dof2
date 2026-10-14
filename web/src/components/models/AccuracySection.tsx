import { MODEL_CHOICES, MODEL_LABELS } from "../../data/model";
import type { ModelChoice } from "../../data/model";
import { COLOURS, DASHES } from "./modelStyle";
import type { XpAccuracy, XpAccuracySeason } from "./accuracy";

const KIND_NOTE: Record<XpAccuracySeason["kind"], string> = {
  backtest: "Backtest (walk-forward, configs tuned on these seasons: in-sample)",
  replay: "Replay (frozen models run after the gameweeks were played)",
  prospective: "Live (xP recorded before each deadline)",
};

function MaeChart({ s }: { s: XpAccuracySeason }) {
  const ids = MODEL_CHOICES.filter((m) => m in s.pooled_mae);
  const gws = s.gameweeks;
  if (gws.length === 0 || ids.length === 0) return null;
  const vals = gws.flatMap((g) => ids.map((m) => g.mae[m]).filter((v): v is number => v !== undefined));
  const lo = Math.floor(Math.min(...vals) * 10) / 10;
  const hi = Math.ceil(Math.max(...vals) * 10) / 10;
  const W = 640;
  const H = 200;
  const L = 40;
  const R = 10;
  const T = 10;
  const B = 24;
  const x = (i: number) => L + ((W - L - R) * i) / Math.max(1, gws.length - 1);
  const y = (v: number) => H - B - ((H - T - B) * (v - lo)) / Math.max(0.01, hi - lo);
  const step = gws.length > 12 ? 5 : 1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`xP MAE per gameweek, ${s.season}`} className="accuracy-chart">
      {[lo, (lo + hi) / 2, hi].map((t) => (
        <g key={t}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="currentColor" opacity="0.12" />
          <text x={L - 4} y={y(t) + 4} textAnchor="end" fontSize="10" fill="currentColor">
            {t.toFixed(2)}
          </text>
        </g>
      ))}
      {gws.map((g, i) =>
        g.gameweek === 1 || g.gameweek % step === 0 ? (
          <text key={g.gameweek} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="currentColor">
            {g.gameweek}
          </text>
        ) : null,
      )}
      {ids.map((m) => (
        <polyline
          key={m}
          data-model={m}
          points={gws
            .map((g, i) => (g.mae[m] !== undefined ? `${x(i)},${y(g.mae[m])}` : null))
            .filter(Boolean)
            .join(" ")}
          fill="none"
          stroke={COLOURS[m]}
          strokeWidth={2}
          strokeDasharray={DASHES[m]}
        />
      ))}
    </svg>
  );
}

/** (c) Forecast accuracy: all-player xP MAE per GW for each season played. */
export function AccuracySection({ accuracy, status }: { accuracy: XpAccuracy | null; status: "loading" | "ready" }) {
  return (
    <section className="models-page-section" id="models-accuracy" data-testid="models-accuracy" aria-labelledby="models-accuracy-heading">
      <h2 id="models-accuracy-heading">Forecast accuracy (xP vs actual)</h2>
      {status === "loading" ? (
        <p>Loading accuracy scores…</p>
      ) : !accuracy || accuracy.seasons.length === 0 ? (
        <p className="models-note" data-testid="accuracy-absent">
          No xP accuracy scores are available yet.
        </p>
      ) : (
        <>
          <p className="models-note">
            {accuracy.metric}. Population: every player all models priced, including those who did not play.
          </p>
          {accuracy.seasons.map((s) => {
            const ids = MODEL_CHOICES.filter((m) => m in s.pooled_mae);
            return (
              <div key={`${s.season}-${s.kind}`} className="accuracy-season" data-testid={`accuracy-${s.season}`}>
                <h3>
                  {s.season} <span className={`season-phase season-phase-${s.kind === "prospective" ? "prospective" : "replay"}`}>{s.kind === "prospective" ? "Live" : s.kind === "replay" ? "Replay" : "Backtest"}</span>
                </h3>
                <p className="models-note">{KIND_NOTE[s.kind]}. GW{s.gameweeks[0]?.gameweek}–{s.gameweeks[s.gameweeks.length - 1]?.gameweek}.</p>
                <MaeChart s={s} />
                <ul className="models-legend accuracy-legend">
                  {ids.map((m: ModelChoice) => (
                    <li key={m} className="models-legend-item">
                      <svg width="24" height="8" aria-hidden="true">
                        <line x1="0" y1="4" x2="24" y2="4" stroke={COLOURS[m]} strokeWidth="3" strokeDasharray={DASHES[m]} />
                      </svg>
                      {MODEL_LABELS[m]} <strong data-testid={`accuracy-${s.season}-${m}`}>{s.pooled_mae[m].toFixed(3)}</strong>
                    </li>
                  ))}
                  {Object.entries(s.missing_models).map(([m, why]) => (
                    <li key={m} className="models-legend-item is-missing">
                      {MODEL_LABELS[m as ModelChoice] ?? m}: {why}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
          <p className="models-note">Live 2026/27 (GW7 onward) accuracy appears here once CI publishes its xP scores.</p>
        </>
      )}
    </section>
  );
}
