import { useMemo, useState } from "react";
import type { Log, LogHindsight, LogOracleDiagnostic, Players } from "../../contract/types";
import "./hindsight.css";

interface HindsightSectionProps {
  log: Log | null;
  players: Players | null;
  status: "loading" | "ready" | "absent" | "error";
}

const MODEL_DISPLAY_NAMES: Record<string, string> = {
  played: "Owner (Played)",
  xp_v1: "Champion (xp_v1)",
  c1: "Challenger (C1)",
  a: "Model A",
  a_odds: "Model A (odds)",
  b0: "Baseline (B0)",
  model_free: "Model-Free (form)",
};

function formatModelName(key: string): string {
  return MODEL_DISPLAY_NAMES[key] || key;
}

export function HindsightSection({ log, players, status }: HindsightSectionProps) {
  const completedGws = useMemo(() => {
    if (!log || !log.gameweeks) return [];
    return log.gameweeks.filter((gw) => gw.score !== null || gw.hindsight !== null);
  }, [log]);

  const [selectedGwNum, setSelectedGwNum] = useState<number | null>(null);

  // Default to the latest completed gameweek if not explicitly selected
  const activeGwNum = selectedGwNum ?? (completedGws.length > 0 ? completedGws[completedGws.length - 1].gameweek : null);
  const activeGw = completedGws.find((gw) => gw.gameweek === activeGwNum);
  const hindsight: LogHindsight | null = activeGw?.hindsight ?? null;

  const playerLookup = useMemo(() => {
    const map = new Map<number, string>();
    if (players && players.players) {
      for (const p of players.players) {
        map.set(p.id, p.name);
      }
    }
    return map;
  }, [players]);

  const playerName = (id: number) => playerLookup.get(id) || `#${id}`;

  if (status === "loading") {
    return (
      <section className="models-page-section" id="models-hindsight" aria-labelledby="models-hindsight-heading">
        <h2 id="models-hindsight-heading">Hindsight</h2>
        <p>Loading season log and hindsight data…</p>
      </section>
    );
  }

  if (status === "absent" || !log || completedGws.length === 0) {
    return (
      <section className="models-page-section" id="models-hindsight" aria-labelledby="models-hindsight-heading">
        <h2 id="models-hindsight-heading">Hindsight</h2>
        <div className="hindsight-empty-state" data-testid="hindsight-empty">
          <p>Hindsight review and oracle analysis will appear here after gameweeks are completed and match points are scored.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="models-page-section" id="models-hindsight" aria-labelledby="models-hindsight-heading">
      <h2 id="models-hindsight-heading">Hindsight</h2>
      <p className="models-note">
        Evaluate how each model&apos;s pre-deadline advice performed against actual match points, and compare decisions against the hindsight-optimal oracle ceiling.
      </p>

      <div className="hindsight-container">
        {/* Prior Week Selector */}
        <div className="hindsight-selector-bar">
          <span className="hindsight-selector-label" id="gw-selector-label">Prior Gameweek:</span>
          <div className="hindsight-pills" role="radiogroup" aria-labelledby="gw-selector-label" data-testid="gw-selector">
            {completedGws.map((gw) => {
              const isActive = gw.gameweek === activeGwNum;
              return (
                <button
                  key={gw.gameweek}
                  type="button"
                  role="radio"
                  aria-checked={isActive}
                  className={`hindsight-pill ${isActive ? "active" : ""}`}
                  onClick={() => setSelectedGwNum(gw.gameweek)}
                  data-testid={`gw-pill-${gw.gameweek}`}
                >
                  GW{gw.gameweek}
                </button>
              );
            })}
          </div>
        </div>

        {/* Hindsight Content for Selected Gameweek */}
        {hindsight ? (
          <div className="hindsight-grid" data-testid="hindsight-content">
            {/* 1. Multi-Model Recommendation Leaderboard */}
            <div className="hindsight-card" data-testid="hindsight-rankings">
              <h3 className="hindsight-card-title">
                Model Recommendation Performance — GW{activeGwNum}
              </h3>
              <div className="table-scroll" tabIndex={0} role="region" aria-label="Model Performance Table">
                <table className="models-table">
                  <thead>
                    <tr>
                      <th scope="col">Rank</th>
                      <th scope="col">Model</th>
                      <th scope="col">Captain</th>
                      <th scope="col">Autosubs</th>
                      <th scope="col">Transfers &amp; Hits</th>
                      <th scope="col">Expected</th>
                      <th scope="col">Net Pts</th>
                      <th scope="col">Prediction Delta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hindsight.rankings.map((r) => (
                      <tr key={r.model_name} data-testid={`rank-row-${r.model_name}`}>
                        <td style={{ fontWeight: r.rank === 1 ? 700 : 400 }}>#{r.rank}</td>
                        <th scope="row" style={{ textAlign: "left" }}>
                          {formatModelName(r.model_name)}
                        </th>
                        <td>
                          {playerName(r.score.captain_id)} ({r.score.armband_points} pts)
                          {r.score.vice_used ? " (VC)" : ""}
                        </td>
                        <td>
                          {r.score.autosubs_in.length > 0
                            ? `+${r.score.autosubs_in.length} in`
                            : "None"}
                        </td>
                        <td>
                          {r.score.hit_points > 0 ? (
                            <span className="models-hit">-{r.score.hit_points} pts</span>
                          ) : (
                            "0 hits"
                          )}
                        </td>
                        <td>{r.score.expected_points.toFixed(1)}</td>
                        <td style={{ fontWeight: 700 }}>{r.score.net_points}</td>
                        <td style={{ color: r.score.prediction_delta >= 0 ? "#10b981" : "#ef4444" }}>
                          {r.score.prediction_delta > 0 ? `+${r.score.prediction_delta}` : r.score.prediction_delta}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 2. Oracle & Diagnostics Grid */}
            <div className="hindsight-grid-oracle">
              {/* Optimal Hindsight Transfers & Team Selection */}
              <div className="hindsight-card" data-testid="hindsight-oracle-card">
                <h3 className="hindsight-card-title">
                  <span>Hindsight Oracle Ceiling</span>
                  <span className="hindsight-ceiling-badge" data-testid="oracle-ceiling-pts">
                    {hindsight.optimal.optimal_overall.net_points} pts
                  </span>
                </h3>
                <p style={{ margin: "0 0 0.5rem 0", fontSize: "0.9rem" }}>
                  The mathematically optimal legal move within pre-deadline budget:
                </p>

                {hindsight.optimal.optimal_overall.moves.length > 0 ? (
                  <ul className="hindsight-moves-list" data-testid="oracle-moves">
                    {hindsight.optimal.optimal_overall.moves.map((m, idx) => (
                      <li key={idx} className="hindsight-move-item">
                        <span>{m.player_out_name} (£{m.selling_price.toFixed(1)}m)</span>
                        <span className="hindsight-move-arrow">→</span>
                        <strong>{m.player_in_name} (£{m.buying_price.toFixed(1)}m)</strong>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p style={{ fontStyle: "italic", margin: "0.5rem 0" }}>
                    Optimal action was rolling the free transfer (0 transfers).
                  </p>
                )}

                <div style={{ fontSize: "0.88rem", display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                  <div>
                    <strong>Captain:</strong> {hindsight.optimal.optimal_overall.captain_name}
                  </div>
                  <div>
                    <strong>Starting XI:</strong>{" "}
                    {hindsight.optimal.optimal_overall.starting.map((id) => playerName(id)).join(", ")}
                  </div>
                  <div style={{ color: "#10b981", fontWeight: 600 }}>
                    Gain over rolling: +{hindsight.optimal.optimal_overall.gain_over_roll.toFixed(1)} pts
                  </div>
                </div>
              </div>

              {/* Pre-Deadline Model Diagnostics ("Oracle Gap") */}
              <div className="hindsight-card" data-testid="hindsight-diagnostics-card">
                <h3 className="hindsight-card-title">
                  Oracle Gap Diagnostics
                </h3>
                <p style={{ margin: "0 0 0.75rem 0", fontSize: "0.9rem" }}>
                  Distinguishing genuine model blindspots from high-variance hauls:
                </p>

                {hindsight.diagnostics.length > 0 ? (
                  <div className="hindsight-diagnostic-list" data-testid="diagnostics-list">
                    {hindsight.diagnostics.map((d: LogOracleDiagnostic, idx) => {
                      const tagClass =
                        d.category === "model_blindspot"
                          ? "tag-blindspot"
                          : d.category === "high_variance_outlier"
                          ? "tag-outlier"
                          : "tag-trap";
                      return (
                        <div key={idx} className={`hindsight-diagnostic-card category-${d.category}`}>
                          <div className="hindsight-diagnostic-header">
                            <span className={`hindsight-tag ${tagClass}`}>
                              {d.category.replace(/_/g, " ")}
                            </span>
                            <strong>{d.player_name}</strong>
                            <span className="history-sub">({d.role})</span>
                            <span className="hindsight-diagnostic-pts">{d.actual_points} pts</span>
                          </div>
                          <p className="hindsight-diagnostic-text">{d.explanation}</p>
                          <div className="hindsight-xp-comparison">
                            <span>Pre-deadline xP:</span>
                            {Object.entries(d.models_xp).map(([model, xp]) => (
                              <span key={model}>
                                <strong>{model}:</strong> {xp.toFixed(1)}
                              </span>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p style={{ fontStyle: "italic" }}>
                    No significant divergences or blindspots identified for this gameweek.
                  </p>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="hindsight-empty-state" data-testid="hindsight-gw-empty">
            <p>
              Hindsight analysis for GW{activeGwNum} is not yet available or advice was not recorded.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
