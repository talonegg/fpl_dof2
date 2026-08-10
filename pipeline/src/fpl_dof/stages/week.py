"""Week stage — the weekly recommendation, in one pass.

Runs after ``forecast``. Loads the squad as it actually stands, ranks doing nothing against every
affordable transfer, picks the resulting XI, collects the alerts, works out both deadlines, and
reconciles the last gameweek's advice against what was played.

The success test for E1 is not accuracy, it is **elapsed attention**: "it is Thursday evening" to
"I know what I am doing and why" in under fifteen minutes. So this stage writes one artefact that
answers the whole question rather than several that each answer part of it.

It is skipped, with a reason, when no squad can be established. That is the normal preseason state
(DL-20) and must not fail a run that is otherwise fine — the forecast and the E0 squad are still
worth publishing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fpl_dof.frames import as_float
from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.optimise.transfer import TransferRecommendation, recommend_transfers
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.squad.selection import Candidate, select_team
from fpl_dof.squad.state import (
    SquadState,
    SquadStateError,
    gameweek_price_index,
    load_squad_state,
)
from fpl_dof.stages.forecast import XP_FILENAME
from fpl_dof.stages.transform import read_rules
from fpl_dof.week.alerts import Alert, collect_alerts
from fpl_dof.week.deadline import DeadlineView, describe_deadline, next_deadline, to_contract
from fpl_dof.week.reconcile import Reconciliation, reconcile

log = get_logger(__name__)

WEEK_FILENAME = "week.json"
SKIPPED_REASON_KEY = "skipped_reason"


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    silver = ctx.layout.silver
    gold = ctx.layout.gold / f"season={season.replace('/', '-')}"

    gameweeks = read_table(silver, season, Table.GAMEWEEK)
    players = read_table(silver, season, Table.PLAYER)
    forecast = pd.read_parquet(gold / XP_FILENAME)
    forecast["start_floor"] = ctx.config.forecast.minimum_start_probability_for_xi

    deadline = next_deadline(
        gameweeks,
        now=utcnow(),
        local_zone=ctx.config.runtime.timezone,
        decide_by_hours=ctx.config.alerts.decide_by_hours_before_deadline,
    )

    picks = read_table_optional(silver, season, Table.ENTRY_PICK)
    try:
        state = load_squad_state(
            entry_config=ctx.config.entry,
            rules=rules,
            players=players,
            next_gameweek=deadline.gameweek,
            picks=picks,
            transfers=read_table_optional(silver, season, Table.ENTRY_TRANSFER),
            entry=read_table_optional(silver, season, Table.ENTRY),
            chips=read_table_optional(silver, season, Table.ENTRY_CHIP),
            gameweek_prices=gameweek_price_index(
                read_table_optional(silver, season, Table.PLAYER_GAMEWEEK)
            ),
        )
    except SquadStateError as exc:
        # Degrade rather than break (DP-15). The forecast is still good; there is simply no squad
        # to advise on yet.
        log.warning("week.skipped", extra={"reason": str(exc)})
        path = _write(
            gold,
            {
                "run_id": ctx.run_id,
                "skipped": True,
                SKIPPED_REASON_KEY: str(exc),
                "deadline": to_contract(deadline),
            },
        )
        return StageResult(
            metrics={"status": "skipped", SKIPPED_REASON_KEY: str(exc)},
            outputs=[Output(path=path)],
        )

    recommendation = recommend_transfers(
        forecast, state, rules, ctx.config.transfers, ctx.config.optimiser
    )
    alerts = collect_alerts(
        state=state,
        players=players,
        rules=rules,
        config=ctx.config.alerts,
        current_gameweek=deadline.gameweek,
        chips=read_table_optional(silver, season, Table.CHIP),
    )
    reconciliation = _reconcile_previous(ctx, gold, picks, deadline.gameweek)

    payload = _payload(
        ctx=ctx,
        rules=rules,
        state=state,
        forecast=forecast,
        recommendation=recommendation,
        alerts=alerts,
        deadline=deadline,
        reconciliation=reconciliation,
    )
    path = _write(gold, payload)

    for line in [
        *describe_deadline(deadline),
        f"Squad provenance: {state.provenance.value}",
        f"Recommendation: {recommendation.rationale}",
    ]:
        log.info("week.summary", extra={"line": line})

    return StageResult(
        metrics={
            "status": "ok",
            "gameweek": deadline.gameweek,
            "provenance": state.provenance.value,
            "transfers": recommendation.recommended.transfers,
            "net_xp": recommendation.recommended.net_expected_points,
            "gain_over_roll": recommendation.recommended.gain_over(recommendation.roll),
            "free_transfers": state.free_transfers,
            "alerts": len(alerts),
            "urgent_alerts": sum(1 for a in alerts if a.severity.label == "urgent"),
        },
        outputs=[Output(path=path, rows=len(state.players))],
    )


def _write(gold: Path, payload: dict[str, object]) -> Path:
    gold.mkdir(parents=True, exist_ok=True)
    path = gold / WEEK_FILENAME
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _reconcile_previous(
    ctx: StageContext,
    gold: Path,
    picks: pd.DataFrame | None,
    next_gameweek: int,
) -> Reconciliation | None:
    """Diff last gameweek's advice against what was played, if both exist.

    Reads the *previously written* week.json, which is what makes this evidence rather than
    recollection: the advice is compared as it was recorded at the time, not as it is remembered
    or as it would be recomputed now with hindsight.
    """
    if picks is None or picks.empty or ctx.config.entry.team_id is None:
        return None
    previous_gameweek = next_gameweek - 1
    if previous_gameweek < 1:
        return None

    path = gold / WEEK_FILENAME
    if not path.exists():
        return None
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("week.previous_unreadable", extra={"path": str(path)})
        return None

    advised = previous.get("advised")
    if not isinstance(advised, dict) or advised.get("gameweek") != previous_gameweek:
        return None

    try:
        return reconcile(
            gameweek=previous_gameweek,
            entry_id=ctx.config.entry.team_id,
            advised=advised,
            picks=picks,
        )
    except ValueError as exc:
        log.info("week.reconcile_skipped", extra={"reason": str(exc)})
        return None


def _payload(
    *,
    ctx: StageContext,
    rules: GameRules,
    state: SquadState,
    forecast: pd.DataFrame,
    recommendation: TransferRecommendation,
    alerts: list[Alert],
    deadline: DeadlineView,
    reconciliation: Reconciliation | None,
) -> dict[str, object]:
    chosen = recommendation.recommended
    lookup = forecast.set_index("player_id")

    candidates = {
        player_id: Candidate(
            player_id=player_id,
            position=Position(str(lookup.loc[player_id, "position"])),
            expected_points=as_float(lookup.loc[player_id, "xp_next"]),
            start_probability=as_float(lookup.loc[player_id, "start_probability"]),
            web_name=str(lookup.loc[player_id, "web_name"]),
        )
        for player_id in chosen.squad_after
    }
    selection = select_team(
        candidates,
        rules,
        captain_multiplier=ctx.config.optimiser.captain_multiplier,
        start_probability_floor=(
            ctx.config.forecast.minimum_start_probability_for_xi
            if ctx.config.optimiser.enforce_start_probability_floor
            else 0.0
        ),
        locked_player_ids=frozenset(ctx.config.optimiser.locked_player_ids),
    )

    return {
        "run_id": ctx.run_id,
        "skipped": False,
        "deadline": to_contract(deadline),
        "squad_state": {
            "provenance": state.provenance.value,
            "entry_id": state.entry_id,
            "as_of_gameweek": state.as_of_gameweek,
            "bank": state.bank,
            "sell_value": state.sell_value(rules),
            "budget": state.budget(rules),
            "free_transfers": state.free_transfers,
            "chips_used": list(state.chips_used),
            "warnings": list(state.warnings),
        },
        "recommendation": {
            "rationale": recommendation.rationale,
            "is_roll": recommendation.is_roll(),
            "transfers": chosen.transfers,
            "hit_points": chosen.hit_points,
            "net_expected_points": chosen.net_expected_points,
            "gain_over_roll": chosen.gain_over(recommendation.roll),
            "bank_after": chosen.bank_after,
            "moves": [
                {
                    "out": {
                        "player_id": move.player_out_id,
                        "web_name": move.player_out_name,
                        "price": move.selling_price,
                    },
                    "in": {
                        "player_id": move.player_in_id,
                        "web_name": move.player_in_name,
                        "price": move.buying_price,
                    },
                }
                for move in chosen.moves
            ],
            "options": [
                {
                    "transfers": option.transfers,
                    "hit_points": option.hit_points,
                    "net_expected_points": option.net_expected_points,
                    "gain_over_roll": option.gain_over(recommendation.roll),
                    "moves": [move.describe() for move in option.moves],
                }
                for option in sorted(recommendation.options, key=lambda o: o.transfers)
            ],
            "warnings": list(recommendation.warnings),
        },
        "advised": {
            "gameweek": deadline.gameweek,
            "squad": list(chosen.squad_after),
            "starting": list(selection.starting),
            "bench_order": list(selection.bench_order),
            "reserve_goalkeeper": selection.reserve_goalkeeper,
            "captain": selection.captain,
            "vice_captain": selection.vice_captain,
            "formation": selection.formation,
            "expected_points": selection.expected_points,
        },
        "alerts": [alert.as_dict() for alert in alerts],
        "reconciliation": reconciliation.as_dict() if reconciliation else None,
    }
