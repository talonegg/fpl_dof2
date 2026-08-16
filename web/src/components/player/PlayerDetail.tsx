/**
 * Player detail (E6-S3, FR-23, FR-29).
 *
 * The page answers, in order: what is this player forecast to return and how sure is the model, why
 * is that number what it is, will they be on the pitch, what is coming up, and what have they
 * actually done. The decomposition leads rather than trails, because "why is this number what it is"
 * is the question the page exists to answer (DP-09) — a breakdown bolted underneath the trends reads
 * as a debugging aid, which is exactly what it is not.
 *
 * Uncertainty is on every forecast on this page and on none of the history, which is the honest
 * split: the forecasts are estimates and the history is a record (Invariant 6, DL-37).
 */

import { Link } from "react-router-dom";
import type { Player } from "../../contract/types";
import { Decomposition } from "../Decomposition";
import { statusLabel, AVAILABLE_STATUS } from "../scout/columns";
import { formatPercent, formatPrice, formatXpRange } from "../../format";
import { FixtureRunPanel } from "./FixtureRunPanel";
import { TrendCharts } from "./TrendCharts";
import "./player.css";

/**
 * Minutes probability, framed as what it means rather than as a bare percentage.
 *
 * A start probability is the single most decision-relevant number on the page — a 9.0-point forecast
 * on a 40% chance of starting is a different proposition from the same forecast on a 95% chance —
 * and "0.42" communicates none of that. It is also a forecast, so it says so.
 */
function MinutesProbability({ player }: { player: Player }) {
  const percent = player.start_probability * 100;
  const inTwenty = Math.round(player.start_probability * 20);

  const framing =
    percent >= 90
      ? "A near-certain starter on current information."
      : percent >= 70
        ? "Expected to start, with a real chance of missing out."
        : percent >= 40
          ? "A genuine rotation risk: as likely to be benched or rested as not."
          : "Unlikely to start. Treat any expected-points figure here as conditional on them playing.";

  return (
    <div className="player-metric" data-testid="minutes-probability">
      <span className="player-metric-label">Chance of starting</span>
      <span className="player-metric-value">{formatPercent(percent)}</span>
      <span className="player-metric-note">
        The model expects {player.name} to start roughly {inTwenty} of every 20 gameweeks like this
        one. {framing} This is a forecast from minutes history and availability, not a team sheet.
      </span>
    </div>
  );
}

function Availability({ player }: { player: Player }) {
  const available = player.status === AVAILABLE_STATUS;
  const news = player.news?.trim();

  return (
    <section className="player-panel" data-testid="availability">
      <h3>Availability</h3>
      <p className={available ? "availability-line" : "availability-line availability-flagged"}>
        <span className="availability-status">{statusLabel(player.status)}</span>
        {news ? ` — ${news}` : available ? " — no news reported by the game." : ""}
      </p>
      {!available && !news && (
        <p className="panel-note">
          The game reports this player as {statusLabel(player.status).toLowerCase()} but has published
          no accompanying news.
        </p>
      )}
      {/*
        TODO(E6-S3): set-piece role is named in the story but is not in the web contract. The
        `set_piece_note` table exists in silver (`pipeline/src/fpl_dof/silver/tables.py`) and is
        populated by the FPL adapter, but nothing publishes it into `contracts/v1/players.schema.json`,
        so the browser has no route to it. Publishing it is pipeline and contract work, which is out
        of scope for a web-only story — this is a note, not an omission, and inventing the field
        client-side would be worse than leaving it absent.
      */}
      <p className="panel-note" data-testid="set-piece-unpublished">
        Set-piece role is not published in the current web contract, so it cannot be shown here.
      </p>
    </section>
  );
}

export function PlayerDetail({ player }: { player: Player }) {
  return (
    <div className="player-page" data-testid="player-detail">
      <header className="player-header">
        <h2>{player.full_name ?? player.name}</h2>
        <p className="player-detail-sub">
          {player.position} · {player.team} · {formatPrice(player.price)} ·{" "}
          {formatPercent(player.selected_by_percent)} selected by
        </p>
        <div className="player-metrics">
          <div className="player-metric" data-testid="xp-next">
            <span className="player-metric-label">Expected points, next gameweek</span>
            <span className="player-metric-value">{player.xp_next.toFixed(2)}</span>
            <span className="player-metric-note">
              {formatXpRange(player.xp_next, player.xp_next_sd)}
            </span>
          </div>
          <div className="player-metric" data-testid="xp-horizon">
            <span className="player-metric-label">Expected points, planning horizon</span>
            <span className="player-metric-value">{player.xp_horizon.toFixed(2)}</span>
            <span className="player-metric-note">
              {formatXpRange(player.xp_horizon, player.xp_horizon_sd)}
            </span>
          </div>
          <MinutesProbability player={player} />
          <div className="player-metric" data-testid="confidence">
            <span className="player-metric-label">Model confidence</span>
            <span className={`confidence-badge confidence-${player.confidence}`}>
              {player.confidence}
            </span>
            <span className="player-metric-note">
              How much evidence sits behind this forecast, not how good the player is.
            </span>
          </div>
        </div>
      </header>

      <section className="player-panel" data-testid="decomposition-panel">
        <h3>Why this number</h3>
        <Decomposition player={player} />
      </section>

      <Availability player={player} />
      <FixtureRunPanel player={player} />
      <TrendCharts player={player} />

      <p className="player-detail-back">
        <Link to="/scout">Back to the scout table</Link>
      </p>
    </div>
  );
}
