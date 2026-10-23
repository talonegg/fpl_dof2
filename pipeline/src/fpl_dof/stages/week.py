"""Week stage — every published strategy's advice for the next deadline, in one pass (MOD-04).

Runs after ``forecast``. Loads the squad as it actually stands and the one input snapshot every
strategy is decided on, then runs each published strategy through ``forecast`` → ``decide``: the
transfers, the XI, the captain, and the multi-gameweek plan with its chips unless the strategy's
policy skips it. The champion writes ``week.json`` and ``plan.json``; every other published strategy
writes its own pair, named in :func:`fpl_dof.publish.strategies.artefact_paths`. The alerts, both
deadlines and the reconciliation of last week's advice are shared by all of them.

The success test for E1 is not accuracy, it is **elapsed attention**: "it is Thursday evening" to
"I know what I am doing and why" in under fifteen minutes. So this stage writes one week artefact
per strategy that answers the whole question rather than several that each answer part of it.

The champion's week is written, and recorded in the ledger, the moment its week decision exists:
before its plan is solved and before any challenger runs, so neither can lose or delay this week's
advice. A champion plan that fails, for any reason, is "no plan" with its reason and the week
stands. A challenger that fails costs its own advice and nothing else: it records "no advice" with
the reason, in its artefacts and the ledger (NFR-15). A champion week failure fails the run, as it
always has.

It is skipped, with a reason, when no squad can be established. That is the normal preseason state
(DL-20) and must not fail a run that is otherwise fine — the forecast and the E0 squad are still
worth publishing.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.artefacts import CAPTAIN_LINE_FILENAME, XP_FILENAME, read_rules
from fpl_dof.config.models import Config
from fpl_dof.decision import Decision, DecisionPolicy, decide, solve_plan
from fpl_dof.factory import form_by_player_id, trailing_form
from fpl_dof.factory.registry import (
    Forecast,
    ForecastInputs,
    Strategy,
    champion,
    published_strategies,
    stamp,
)
from fpl_dof.frames import as_float
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.captain import PricePositionLine
from fpl_dof.optimise.plan import DecisionPlan, as_dict
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.publish.strategies import artefact_paths
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.squad.state import (
    SquadState,
    SquadStateError,
    gameweek_price_index,
    load_squad_state,
)
from fpl_dof.week.alerts import Alert, collect_alerts
from fpl_dof.week.deadline import DeadlineView, describe_deadline, next_deadline, to_contract
from fpl_dof.week.ledger import read_advice, record_advice
from fpl_dof.week.reconcile import Reconciliation, reconcile

log = get_logger(__name__)

WEEK_FILENAME = "week.json"
SKIPPED_REASON_KEY = "skipped_reason"

#: A strategy's week and plan payloads; the plan is ``None`` when its policy does not plan.
Advice = tuple[dict[str, Any], dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What every published strategy is decided on, read once, so any two agree on their data."""

    config: Config
    run_id: str
    rules: GameRules
    state: SquadState
    inputs: ForecastInputs
    champion: Forecast
    """The forecast stage's frame and B0 line: the champion's forecast, decided first."""
    fixtures: pd.DataFrame | None
    chips: pd.DataFrame | None
    last_gameweek: int
    deadline: DeadlineView
    alerts: list[Alert]
    reconciliation: Reconciliation | None
    form: dict[int, tuple[float | None, int | None]] | None


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    silver = ctx.layout.silver
    gold = ctx.layout.gold_for(season)
    published = published_strategies()

    gameweeks = read_table(silver, season, Table.GAMEWEEK)
    players = read_table(silver, season, Table.PLAYER)

    deadline = next_deadline(
        gameweeks,
        now=ctx.as_of,
        local_zone=ctx.config.runtime.timezone,
        decide_by_hours=ctx.config.alerts.decide_by_hours_before_deadline,
    )

    picks = read_table_optional(silver, season, Table.ENTRY_PICK)
    player_gameweek = read_table_optional(silver, season, Table.PLAYER_GAMEWEEK)
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
            gameweek_prices=gameweek_price_index(player_gameweek, season),
        )
    except SquadStateError as exc:
        # Degrade rather than break (DP-15). The forecast is still good; there is simply no squad
        # to advise on yet.
        log.warning("week.skipped", extra={"reason": str(exc)})
        skipped = {
            s.id: _no_advice(ctx.run_id, deadline, s, str(exc), ctx.config) for s in published
        }
        return StageResult(
            metrics={"status": "skipped", SKIPPED_REASON_KEY: str(exc)},
            outputs=_write_all(gold, skipped, published),
        )

    champion_frame = pd.read_parquet(gold / XP_FILENAME)
    fixtures = read_table(silver, season, Table.FIXTURE)
    chips = read_table_optional(silver, season, Table.CHIP)
    this_season = player_gameweek
    if this_season is not None and "season" in this_season.columns:
        this_season = this_season[this_season["season"] == season]
    snapshot = Snapshot(
        config=ctx.config,
        run_id=ctx.run_id,
        rules=rules,
        state=state,
        inputs=ForecastInputs(
            players=players,
            teams=read_table(silver, season, Table.TEAM),
            fixtures=fixtures,
            gameweeks=gameweeks,
            history=read_table(silver, season, Table.PLAYER_SEASON_HISTORY),
            as_of=ctx.as_of,
            player_gameweek=player_gameweek,
            metrics=read_table_optional(silver, season, Table.PLAYER_METRIC),
            match_odds=read_table_optional(silver, season, Table.TEAM_MATCH_EXPECTATION),
        ),
        champion=Forecast(
            frame=champion_frame,
            model=str(champion_frame["model"].iloc[0]),
            fallback_reason=None,
            captain_line=_read_captain_line(gold),
        ),
        fixtures=fixtures,
        chips=chips,
        last_gameweek=int(gameweeks["gameweek"].max()),
        deadline=deadline,
        alerts=collect_alerts(
            state=state,
            players=players,
            rules=rules,
            config=ctx.config.alerts,
            current_gameweek=deadline.gameweek,
            chips=chips,
        ),
        reconciliation=_reconcile_previous(ctx, gold, picks, deadline.gameweek),
        form=form_by_player_id(
            trailing_form(this_season, as_of=pd.Timestamp(ctx.as_of)), champion_frame
        ),
    )

    advice, outputs = advise_all(snapshot, published, gold=gold, layout=ctx.layout)
    week_payload, plan_payload = advice[champion().id]

    recommendation = week_payload["recommendation"]
    for line in [
        *describe_deadline(deadline),
        f"Squad provenance: {state.provenance.value}",
        f"Recommendation: {recommendation['rationale']}",
    ]:
        log.info("week.summary", extra={"line": line})

    plan_ok = plan_payload is not None and not plan_payload["skipped"]
    return StageResult(
        metrics={
            "status": "ok",
            "gameweek": deadline.gameweek,
            "provenance": state.provenance.value,
            "transfers": recommendation["transfers"],
            "net_xp": recommendation["net_expected_points"],
            "gain_over_roll": recommendation["gain_over_roll"],
            "free_transfers": state.free_transfers,
            "alerts": len(snapshot.alerts),
            "urgent_alerts": sum(1 for a in snapshot.alerts if a.severity.label == "urgent"),
            "plan_status": "ok" if plan_ok else "skipped",
            "plan_solve_seconds": plan_payload["solve_seconds"] if plan_ok and plan_payload else 0,
            "strategies": len(published),
            "strategies_without_advice": sum(1 for w, _ in advice.values() if w["skipped"]),
        },
        outputs=outputs,
    )


def advise_all(
    snapshot: Snapshot, strategies: Sequence[Strategy], *, gold: Path, layout: DataLayout
) -> tuple[dict[str, Advice], list[Output]]:
    """Every strategy through ``forecast`` → ``decide`` on the one snapshot, each isolated, written.

    The registry's champion goes first, and its week is written and ledgered before anything that
    could fail or take long: its plan, then each challenger. A champion week failure propagates,
    because a run without the live advice has failed; a champion plan failure is "no plan" and the
    week stands; a challenger that raises gets "no advice" with the reason (NFR-15).
    """
    lead = champion()
    policy = lead.decision_policy(snapshot.config, snapshot.champion.captain_line)
    week = _week(snapshot, lead, snapshot.champion, dataclasses.replace(policy, plan=False))
    _write_all(gold, {lead.id: (week, None)}, [lead])
    _record(snapshot, layout, {lead.id: (week, None)}, [lead])

    advice: dict[str, Advice] = {lead.id: (week, _champion_plan(snapshot, lead, policy))}
    outputs = _write_all(gold, advice, [lead])
    challengers = [s for s in strategies if s.id != lead.id]
    for strategy in challengers:
        try:
            advice[strategy.id] = _advise(snapshot, strategy)
        except Exception as exc:
            reason = f"no advice: {type(exc).__name__}: {exc}"
            log.warning("week.no_advice", extra={"strategy": strategy.id, "reason": reason})
            advice[strategy.id] = _no_advice(
                snapshot.run_id, snapshot.deadline, strategy, reason, snapshot.config
            )
    outputs += _write_all(gold, advice, challengers)
    _record(snapshot, layout, advice, [lead, *challengers])
    return advice, outputs


def _record(
    snapshot: Snapshot, layout: DataLayout, advice: dict[str, Advice], strategies: list[Strategy]
) -> None:
    """The champion's advice to the ledger, with every strategy's so far under ``models``."""
    week, _ = advice[strategies[0].id]
    models = ledger_models(advice, strategies)
    record_advice(layout, week | {"models": models}, as_of=snapshot.inputs.as_of)


def _week(
    snapshot: Snapshot, strategy: Strategy, forecast: Forecast, policy: DecisionPolicy
) -> dict[str, Any]:
    decision = decide(
        forecast.frame,
        snapshot.state,
        snapshot.rules,
        policy,
        fixtures=snapshot.fixtures,
        chips=snapshot.chips,
        last_gameweek=snapshot.last_gameweek,
    )
    return _payload(snapshot, forecast.frame, decision) | _stamp(strategy, snapshot.config)


def _champion_plan(
    snapshot: Snapshot, strategy: Strategy, policy: DecisionPolicy
) -> dict[str, Any] | None:
    """The champion's plan, solved after its week is on disk; any failure is "no plan" (DP-15)."""
    if not strategy.policy.plan:
        return None
    try:
        plan, reason = solve_plan(
            snapshot.champion.frame,
            snapshot.state,
            snapshot.rules,
            policy,
            fixtures=snapshot.fixtures,
            chips=snapshot.chips,
            last_gameweek=snapshot.last_gameweek,
        )
    except Exception as exc:
        plan, reason = None, f"no plan: {type(exc).__name__}: {exc}"
        log.warning("week.no_plan", extra={"strategy": strategy.id, "reason": reason})
    return _plan_payload(snapshot, strategy, plan, reason)


def _advise(snapshot: Snapshot, strategy: Strategy) -> Advice:
    forecast = strategy.forecast(snapshot.inputs, snapshot.rules, snapshot.config)
    decision = decide(
        forecast.frame,
        snapshot.state,
        snapshot.rules,
        strategy.decision_policy(snapshot.config, forecast.captain_line),
        fixtures=snapshot.fixtures,
        chips=snapshot.chips,
        last_gameweek=snapshot.last_gameweek,
    )
    week = _payload(snapshot, forecast.frame, decision) | _stamp(strategy, snapshot.config)
    if not strategy.policy.plan:
        return week, None
    return week, _plan_payload(snapshot, strategy, decision.plan, decision.plan_skipped_reason)


def _plan_payload(
    snapshot: Snapshot, strategy: Strategy, plan: DecisionPlan | None, reason: str | None
) -> dict[str, Any]:
    deadline = to_contract(snapshot.deadline)
    if plan is None:
        payload = _skipped(snapshot.run_id, deadline, reason or "no plan")
    else:
        payload = {"run_id": snapshot.run_id, "skipped": False, "deadline": deadline}
        payload |= as_dict(plan)
    return payload | {"strategy": stamp(strategy, snapshot.config)}


def _skipped(run_id: str, deadline: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"run_id": run_id, "skipped": True, SKIPPED_REASON_KEY: reason, "deadline": deadline}


def _no_advice(
    run_id: str, deadline: DeadlineView, strategy: Strategy, reason: str, config: Config
) -> Advice:
    payload = _skipped(run_id, to_contract(deadline), reason)
    plan = payload | {"strategy": stamp(strategy, config)} if strategy.policy.plan else None
    return payload | _stamp(strategy, config), plan


def ledger_models(advice: dict[str, Advice], strategies: Sequence[Strategy]) -> dict[str, Any]:
    """Every published strategy's advice for the ledger's ``models`` key, by registry id.

    A strategy that produced nothing is recorded as ``no_advice`` with its reason, never carried
    forward from an earlier week (05 §6.3).
    """
    models: dict[str, Any] = {}
    for strategy in strategies:
        week, _ = advice[strategy.id]
        entry: dict[str, Any] = {"role": strategy.role, "strategy": week["strategy"]}
        if week["skipped"]:
            entry["no_advice"] = week[SKIPPED_REASON_KEY]
        else:
            entry |= {
                "advised": week["advised"],
                "recommendation": week["recommendation"],
                "transfers": week["recommendation"]["transfers"],  # what the season log reads
            }
        models[strategy.id] = entry
    return models


def _write_all(
    gold: Path, advice: dict[str, Advice], strategies: Sequence[Strategy]
) -> list[Output]:
    gold.mkdir(parents=True, exist_ok=True)
    outputs = []
    for strategy in strategies:
        paths = artefact_paths(strategy)
        for name, payload in zip((paths["week"], paths["plan"]), advice[strategy.id], strict=True):
            if name is None or payload is None:
                continue
            path = gold / name
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            outputs.append(Output(path=path))
    return outputs


def _read_captain_line(gold: Path) -> PricePositionLine | None:
    """The price-and-position line the forecast stage fitted, validated; ``None`` if none was."""
    path = gold / CAPTAIN_LINE_FILENAME
    if not path.exists():
        return None
    return PricePositionLine.model_validate_json(path.read_text(encoding="utf-8"))


def _stamp(strategy: Strategy, config: Config) -> dict[str, Any]:
    """Which strategy produced a week payload: its label for the app, its registry id and digest."""
    return {
        "model": {"id": strategy.id, "label": strategy.label, "role": strategy.role},
        "strategy": stamp(strategy, config),
    }


def _reconcile_previous(
    ctx: StageContext,
    gold: Path,
    picks: pd.DataFrame | None,
    next_gameweek: int,
) -> Reconciliation | None:
    """Diff last gameweek's advice against what was played, if both exist.

    Reads the advice *as it was recorded at the time* — the ledger first (DL-69), and the
    previously written week.json as the fallback a pre-ledger run left behind — which is what
    makes this evidence rather than recollection: not as it is remembered, and not as it would be
    recomputed now with hindsight.
    """
    if picks is None or picks.empty or ctx.config.entry.team_id is None:
        return None
    previous_gameweek = next_gameweek - 1
    if previous_gameweek < 1:
        return None

    advised: object = None
    recorded = read_advice(ctx.layout, previous_gameweek)
    if recorded is not None:
        advised = recorded.get("advised")
    else:
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


def _payload(snapshot: Snapshot, frame: pd.DataFrame, decision: Decision) -> dict[str, object]:
    """One strategy's decision in the week contract's shape. Presentation only: no choices here."""
    recommendation = decision.recommendation
    chosen = recommendation.recommended
    selection = decision.selection
    state, rules, deadline = snapshot.state, snapshot.rules, snapshot.deadline
    lookup = frame.set_index("player_id")
    form = snapshot.form or {}

    def side(player_id: int, name: str, price: float) -> dict[str, object]:
        """One side of a move, with both rankings' numbers on it (DL-70)."""
        xp = 0.0
        if player_id in lookup.index:
            xp = round(as_float(lookup.loc[player_id, "xp_next"]), 3)
        return {
            "player_id": player_id,
            "web_name": name,
            "price": price,
            "xp_next": xp,
            "form_points_per_match": form.get(player_id, (None, None))[0],
        }

    return {
        "run_id": snapshot.run_id,
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
                    "out": side(move.player_out_id, move.player_out_name, move.selling_price),
                    "in": side(move.player_in_id, move.player_in_name, move.buying_price),
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
            "warnings": [*recommendation.warnings, *decision.warnings],
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
        "alerts": [alert.as_dict() for alert in snapshot.alerts],
        "reconciliation": snapshot.reconciliation.as_dict() if snapshot.reconciliation else None,
    }
