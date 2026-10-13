"""Fail-closed input checks: which frozen models' advice for a gameweek may be published.

Every model needs the FPL history (silver ``player_gameweek``, 2023/24 onward), this gameweek's
availability and the owner's squad. C1, A and A+odds also read xG/xA from that history. A+odds also
needs the frozen odds history and live pre-closing odds for the gameweek. If any input a model needs
is missing or stale, the model is **unavailable for that gameweek, with the reason** — its advice
and its points are never shown, rather than shown on partial data. Pure: the caller does the I/O.

Thresholds (each one is a reason string the app shows verbatim):

- decision lead: the decision must be taken before the deadline and at most 36 h before it, so the
  availability it used (fetched in the same run) is at most 36 h old at the deadline;
- FPL history: refreshed in this run, or at most 24 h before the decision; the current season must
  include every finished gameweek; each backfill season must have at least 20,000 rows;
- xG/xA: at least 90 % of the last finished gameweek's appearances (minutes > 0) carry xG;
- odds history: every frozen football-data.co.uk file byte-identical to the frozen copy;
- live odds: fixtures.csv fetched, at least 70 % of the gameweek's fixtures priced and kept, and at
  most 30 % of A+odds' team rows falling back to the model.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fpl_dof.prospective.bundle import BundleReport

MAX_DECISION_LEAD = dt.timedelta(hours=36)
MAX_SILVER_AGE = dt.timedelta(hours=24)
BACKFILL_SEASONS: tuple[str, ...] = ("2023/24", "2024/25", "2025/26")
MIN_BACKFILL_ROWS = 20_000
MIN_XG_COVERAGE = 0.90
MIN_ODDS_COVERAGE = 0.70
MAX_ODDS_FALLBACK = 0.30

BASE_NEEDS = ("bundle", "decision_lead", "squad", "fpl_history")
NEEDS: dict[str, tuple[str, ...]] = {
    "engine": BASE_NEEDS,
    "C3": BASE_NEEDS,
    "C1": (*BASE_NEEDS, "xg"),
    "A": (*BASE_NEEDS, "xg"),
    "A_odds": (*BASE_NEEDS, "xg", "odds_history", "live_odds"),
}


@dataclass(frozen=True)
class SilverStats:
    """What the decision's FPL history looked like. Built by the caller from the silver table."""

    refresh_ok: bool
    refreshed_at: dt.datetime | None
    current_season_max_gw: int
    rows_by_season: Mapping[str, int]
    xg_coverage_last_gw: float | None


def silver_stats(
    frame: Any,
    *,
    season: str,
    last_finished: int,
    refresh_ok: bool,
    refreshed_at: dt.datetime | None,
) -> SilverStats:
    """Summarise a silver ``player_gameweek`` frame (pandas) for the checks below."""
    cur = frame[frame["season"] == season]
    max_gw = int(cur["gameweek"].max()) if len(cur) else 0
    last = cur[(cur["gameweek"] == last_finished) & (cur["minutes"] > 0)]
    coverage = float(last["expected_goals"].notna().mean()) if len(last) else None
    rows = {str(k): int(v) for k, v in frame.groupby("season").size().items()}
    return SilverStats(refresh_ok, refreshed_at, max_gw, rows, coverage)


def _ts(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def check_inputs(
    decision: Mapping[str, Any],
    *,
    bundle: BundleReport,
    silver: SilverStats | None,
    last_finished: int,
    odds_history: Mapping[str, str | None],
) -> dict[str, str | None]:
    """Input name -> problem (None when fresh). Model-independent except ``bundle`` (see below)."""
    out: dict[str, str | None] = {}
    deadline, decided = _ts(decision.get("deadline")), _ts(decision.get("decided_at"))
    if deadline is None or decided is None:
        out["decision_lead"] = "decision has no deadline or decision time"
    elif decided >= deadline:
        out["decision_lead"] = "decided after the deadline"
    elif deadline - decided > MAX_DECISION_LEAD:
        out["decision_lead"] = "decided more than 36 h before the deadline (availability too old)"
    else:
        out["decision_lead"] = None

    squad = decision.get("real_squad_start") or {}
    out["squad"] = None if squad.get("players") else "owner's squad was not available"

    if silver is None:
        out["fpl_history"] = "FPL history (silver) missing"
        out["xg"] = "FPL history (silver) missing"
    else:
        problem = None
        age_ok = (
            silver.refreshed_at is not None
            and decided is not None
            and decided - silver.refreshed_at <= MAX_SILVER_AGE
        )
        if not (silver.refresh_ok or age_ok):
            problem = "FPL history not refreshed within 24 h of the decision"
        elif silver.current_season_max_gw < last_finished:
            problem = (
                f"FPL history ends at GW{silver.current_season_max_gw}, "
                f"GW{last_finished} has finished"
            )
        else:
            for season in BACKFILL_SEASONS:
                if silver.rows_by_season.get(season, 0) < MIN_BACKFILL_ROWS:
                    problem = f"FPL history for {season} missing or incomplete"
                    break
        out["fpl_history"] = problem
        cov = silver.xg_coverage_last_gw
        if last_finished == 0:
            out["xg"] = None  # nothing played yet this season; prior seasons carry xG
        elif cov is None or cov < MIN_XG_COVERAGE:
            out["xg"] = f"xG/xA missing for GW{last_finished} ({0.0 if cov is None else cov:.0%})"
        else:
            out["xg"] = None

    bad = [rel for rel, p in odds_history.items() if p]
    out["odds_history"] = (
        f"odds history {bad[0].rsplit('/', 1)[-1]}: {odds_history[bad[0]]}"
        if bad
        else (None if odds_history else "odds history not fetched")
    )

    odds = decision.get("odds") or {}
    in_gw = int(odds.get("fixtures_in_gw") or 0)
    kept = int(odds.get("kept") or 0)
    info = ((decision.get("models") or {}).get("A_odds") or {}).get("info") or {}
    used, fallback = int(info.get("odds_rows_used") or 0), int(info.get("odds_fallback_rows") or 0)
    if in_gw == 0 or int(odds.get("fixtures_with_odds") or 0) == 0:
        out["live_odds"] = "no live odds for this gameweek"
    elif kept / in_gw < MIN_ODDS_COVERAGE:
        out["live_odds"] = f"live odds for only {kept}/{in_gw} fixtures"
    elif used + fallback == 0 or fallback / (used + fallback) > MAX_ODDS_FALLBACK:
        out["live_odds"] = "A+odds fell back to the model for too many teams"
    else:
        out["live_odds"] = None
    return out


def assess(
    decision: Mapping[str, Any],
    *,
    bundle: BundleReport,
    silver: SilverStats | None,
    last_finished: int,
    odds_history: Mapping[str, str | None],
    models: Sequence[str] = tuple(NEEDS),
) -> dict[str, dict[str, Any]]:
    """Model -> ``{"available": bool, "reason": str | None, "inputs": {...}}``. Fail closed."""
    inputs = check_inputs(
        decision,
        bundle=bundle,
        silver=silver,
        last_finished=last_finished,
        odds_history=odds_history,
    )
    out: dict[str, dict[str, Any]] = {}
    recorded = set((decision.get("models") or {}).keys())
    for name in models:
        needs = NEEDS.get(name)
        reason: str | None
        if needs is None:
            reason = "unknown model"
        elif name not in recorded:
            reason = "no decision recorded for this model"
        elif not bundle.model_ok(name):
            reason = bundle.reason(name)
        else:
            reason = next((inputs[n] for n in needs if n != "bundle" and inputs.get(n)), None)
        checks = {n: inputs.get(n) for n in (needs or ()) if n != "bundle"}
        checks["bundle"] = None if bundle.model_ok(name) else bundle.reason(name)
        out[name] = {"available": reason is None, "reason": reason, "inputs": checks}
    return out
