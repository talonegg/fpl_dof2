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
the reason in its artefacts, and in the ledger unless an earlier success for the gameweek stands
as its advice of record (NFR-15, DL-94). A champion week failure fails the run, as it always has.
Every payload carries its snapshot's ``as_of`` and the run's ``trigger`` (ORC-03).

What it does is asked of each gameweek's state (ORC-01), never of the clock alone: the Open
gameweek is advised, a Finished one is evaluated once (ORC-05, :func:`evaluate`), and nothing else
is done here. Once no gameweek is Open, the stage is skipped with a reason.

It is skipped, with a reason, when no squad can be established. That is the normal preseason state
(DL-20) and must not fail a run that is otherwise fine — the forecast and the E0 squad are still
worth publishing.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections.abc import Callable, Mapping, Sequence
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
    MissingInputError,
    Strategy,
    champion,
    published_strategies,
    stamp,
)
from fpl_dof.frames import as_float, as_int
from fpl_dof.gameweek import Due, SilverTables, chips_played, season_states
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.captain import PricePositionLine
from fpl_dof.optimise.plan import DecisionPlan, as_dict
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.publish.strategies import artefact_paths
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.sources import supplying
from fpl_dof.squad.state import (
    SquadState,
    SquadStateError,
    gameweek_price_index,
    load_squad_state,
)
from fpl_dof.week.alerts import Alert, collect_alerts
from fpl_dof.week.deadline import DeadlineView, describe_deadline, next_deadline, to_contract
from fpl_dof.week.evaluation import (
    Evidence,
    build_evaluation,
    evaluated,
    record_evaluation,
    unready,
)
from fpl_dof.week.ledger import read_advice, read_predictions, record_advice, record_predictions
from fpl_dof.week.oracle import option_set
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
    clock: Callable[[], dt.datetime]
    """The real time, from the edge, for the ledger's closed-record check only (ORC-03)."""


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    silver = ctx.layout.silver
    gold = ctx.layout.gold_for(season)
    published = published_strategies()

    gameweeks = read_table(silver, season, Table.GAMEWEEK)
    # The chip in force, from history and from the gameweek in play's own picks: a Free Hit in
    # play is never the squad next gameweek's advice starts from, whatever history says yet (D-33).
    entry_chips = chips_played(
        read_table_optional(silver, season, Table.ENTRY_CHIP),
        read_table_optional(silver, season, Table.ENTRY_LIVE),
        ctx.config.entry.team_id,
    )
    tables = SilverTables(
        gameweeks, read_table_optional(silver, season, Table.FIXTURE), entry_chips
    )
    states = season_states(tables, evaluated(ctx.layout, ctx.config.entry.team_id), ctx.as_of)
    judged = evaluate(ctx, rules, [s.gameweek for s in states if s.due is Due.EVALUATE])
    if not any(s.due is Due.ADVISE for s in states):
        reason = "no gameweek is open: every deadline has passed"
        log.info("week.nothing_due", extra={"reason": reason})
        return StageResult(
            metrics={"status": "skipped", SKIPPED_REASON_KEY: reason}, outputs=judged
        )

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
            chips=entry_chips,
            gameweek_prices=gameweek_price_index(player_gameweek, season),
        )
    except SquadStateError as exc:
        # Degrade rather than break (DP-15). The forecast is still good; there is simply no squad
        # to advise on yet.
        log.warning("week.skipped", extra={"reason": str(exc)})
        skipped = {
            s.id: _no_advice(ctx.run_id, deadline, s, str(exc), ctx.config, ctx.as_of)
            for s in published
        }
        return StageResult(
            metrics={"status": "skipped", SKIPPED_REASON_KEY: str(exc)},
            outputs=[*judged, *_write_all(gold, skipped, published)],
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
        clock=ctx.clock,
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
        outputs=[*judged, *outputs],
    )


def advise_all(
    snapshot: Snapshot, strategies: Sequence[Strategy], *, gold: Path, layout: DataLayout
) -> tuple[dict[str, Advice], list[Output]]:
    """Every strategy through ``forecast`` → ``decide`` on the one snapshot, each isolated, written.

    The registry's champion goes first, and its week is written and ledgered before anything that
    could fail or take long: its plan, then each challenger. A champion week failure propagates,
    because a run without the live advice has failed; a champion plan failure is "no plan" and the
    week stands; a challenger that raises gets "no advice" with the reason (NFR-15), unless the
    ledger holds a success for the gameweek: its file then shows that advice of record, with the
    failure as ``last_failure`` (DL-94).
    """
    lead = champion()
    policy = lead.decision_policy(snapshot.config, snapshot.champion.captain_line)
    week = _week(snapshot, lead, snapshot.champion, dataclasses.replace(policy, plan=False))
    _write_all(gold, {lead.id: (week, None)}, [lead])
    # Predictions follow the advice of record (ORC-08): written only when the ledger took the entry.
    if _record(snapshot, layout, {lead.id: (week, None)}, [lead]) is not None:
        _predict(snapshot, layout, lead.id, snapshot.champion.frame)

    advice: dict[str, Advice] = {lead.id: (week, _champion_plan(snapshot, lead, policy))}
    outputs = _write_all(gold, advice, [lead])
    challengers = [s for s in strategies if s.id != lead.id]
    held = (read_advice(layout, snapshot.deadline.gameweek) or {}).get("models") or {}
    published: dict[str, Advice] = {}
    missing: dict[str, list[str]] = {}
    frames: dict[str, pd.DataFrame] = {}
    for strategy in challengers:
        try:
            advice[strategy.id], frame = _advise(snapshot, strategy)
            arrived = _arrived(held.get(strategy.id), advice[strategy.id][0], snapshot.config)
            if arrived is not None:
                advice[strategy.id][0]["arrived"] = arrived
            frames[strategy.id] = frame
        except Exception as exc:
            reason = f"no advice: {type(exc).__name__}: {exc}"
            log.warning("week.no_advice", extra={"strategy": strategy.id, "reason": reason})
            if isinstance(exc, MissingInputError):
                missing[strategy.id] = list(exc.tables)
            failed = _no_advice(
                snapshot.run_id,
                snapshot.deadline,
                strategy,
                reason,
                snapshot.config,
                snapshot.inputs.as_of,
            )
            advice[strategy.id] = failed
            of_record = _of_record(held.get(strategy.id), failed[0], week)
            if of_record is not None:
                published[strategy.id] = (of_record, failed[1])
    # The ledger gets the failure (it keeps the success beside it); the app gets the record.
    outputs += _write_all(gold, advice | published, challengers)
    if _record(snapshot, layout, advice, [lead, *challengers], missing) is not None:
        for strategy_id, frame in frames.items():
            _predict(snapshot, layout, strategy_id, frame)
    return advice | published, outputs


def _arrived(held: object, week: dict[str, Any], config: Config) -> dict[str, Any] | None:
    """The source a strategy waited for arrived, and it advised with it (ORC-07).

    Derived from the held record, read before this run's write: the strategy had no advice
    because a table it needs was missing, and now advises, whatever started this run (the week
    file's ``trigger`` says what did). Nothing extra is stored; the next run's week file carries
    no arrival.
    """
    if not isinstance(held, Mapping) or "advised" in held or not held.get("missing"):
        return None
    sources = supplying(held["missing"], config.sources)
    return {"sources": sources, "at": week["as_of"]} if sources else None


def _of_record(
    held: object, failed: dict[str, Any], champion_week: dict[str, Any]
) -> dict[str, Any] | None:
    """A failed strategy's week file rebuilt from its held success, the advice of record (DL-94).

    The squad, alerts and reconciliation are the run's, shared by every strategy; the advice,
    its strategy digest and its stamp are the success's. ``None`` when nothing succeeded yet.
    """
    if not isinstance(held, dict) or not {"advised", "recommendation", "strategy"} <= held.keys():
        return None
    shared = {k: champion_week[k] for k in ("squad_state", "alerts", "reconciliation")}
    stamp = {k: held[k] for k in ("as_of", "trigger") if held.get(k)}
    week = {k: v for k, v in failed.items() if k not in (SKIPPED_REASON_KEY, "as_of", "trigger")}
    return (
        week
        | shared
        | stamp
        | {
            "skipped": False,
            "advised": held["advised"],
            "recommendation": held["recommendation"],
            "strategy": held["strategy"],
            "last_failure": {"as_of": failed["as_of"], "reason": failed[SKIPPED_REASON_KEY]},
        }
    )


def _record(
    snapshot: Snapshot,
    layout: DataLayout,
    advice: dict[str, Advice],
    strategies: list[Strategy],
    missing: Mapping[str, list[str]] | None = None,
) -> Path | None:
    """The champion's advice to the ledger, with every strategy's so far under ``models``.

    The ledger keeps each strategy's last success and refuses a write after the deadline (DL-94).
    Returns what :func:`record_advice` returns: ``None`` when it recorded nothing.
    """
    week, _ = advice[strategies[0].id]
    models = ledger_models(advice, strategies, missing)
    return record_advice(
        layout, week | {"models": models}, as_of=snapshot.inputs.as_of, now=snapshot.clock()
    )


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


def _predict(snapshot: Snapshot, layout: DataLayout, strategy_id: str, frame: pd.DataFrame) -> None:
    """The frame a strategy advised from, to the ledger beside its advice (ORC-08)."""
    record_predictions(
        layout,
        snapshot.deadline.gameweek,
        strategy_id,
        frame,
        deadline=snapshot.deadline.deadline_utc,
        now=snapshot.clock(),
    )


def _advise(snapshot: Snapshot, strategy: Strategy) -> tuple[Advice, pd.DataFrame]:
    """A challenger's advice, and the frame it advised from for the predictions ledger."""
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
        return (week, None), forecast.frame
    plan = _plan_payload(snapshot, strategy, decision.plan, decision.plan_skipped_reason)
    return (week, plan), forecast.frame


def _plan_payload(
    snapshot: Snapshot, strategy: Strategy, plan: DecisionPlan | None, reason: str | None
) -> dict[str, Any]:
    deadline = to_contract(snapshot.deadline)
    if plan is None:
        payload = _skipped(snapshot.run_id, deadline, reason or "no plan")
    else:
        payload = {"run_id": snapshot.run_id, "skipped": False, "deadline": deadline}
        payload |= as_dict(plan)
    run = _run_stamp(snapshot.inputs.as_of, snapshot.config)
    return payload | run | {"strategy": stamp(strategy, snapshot.config)}


def _skipped(run_id: str, deadline: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"run_id": run_id, "skipped": True, SKIPPED_REASON_KEY: reason, "deadline": deadline}


def _no_advice(
    run_id: str,
    deadline: DeadlineView,
    strategy: Strategy,
    reason: str,
    config: Config,
    as_of: dt.datetime,
) -> Advice:
    payload = _skipped(run_id, to_contract(deadline), reason) | _run_stamp(as_of, config)
    plan = payload | {"strategy": stamp(strategy, config)} if strategy.policy.plan else None
    return payload | _stamp(strategy, config), plan


def ledger_models(
    advice: dict[str, Advice],
    strategies: Sequence[Strategy],
    missing: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Every published strategy's advice for the ledger's ``models`` key, by registry id.

    A strategy that produced nothing is recorded as ``no_advice`` with its reason, never carried
    forward from an earlier week (05 §6.3), and with the silver tables it lacked as ``missing``
    when that was why (ORC-07).
    """
    models: dict[str, Any] = {}
    for strategy in strategies:
        week, _ = advice[strategy.id]
        entry: dict[str, Any] = {
            "role": strategy.role,
            "strategy": week["strategy"],
            "as_of": week["as_of"],
            "trigger": week["trigger"],
        }
        if week["skipped"]:
            entry["no_advice"] = week[SKIPPED_REASON_KEY]
            if (tables := (missing or {}).get(strategy.id)) is not None:
                entry["missing"] = tables
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


def _run_stamp(as_of: dt.datetime, config: Config) -> dict[str, str]:
    """When the advice's snapshot was taken and what started the run (ORC-03, DL-94)."""
    return {
        "as_of": as_of.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "trigger": config.runtime.trigger,
    }


def evaluate(ctx: StageContext, rules: GameRules, gameweeks: Sequence[int]) -> list[Output]:
    """ORC-05's evaluation of each Finished gameweek, to ``ledger:evaluation/entry-<id>/gwNN.json``.

    A gameweek whose evidence is not yet complete waits for a later run, and one whose evaluation
    fails is logged and left Finished, to be tried again: judging the past never costs this week's
    advice (DP-15).
    """
    if not gameweeks:
        return []
    silver, season, entry_id = ctx.layout.silver, rules.season, ctx.config.entry.team_id

    def owners(table: Table) -> pd.DataFrame | None:
        frame = read_table_optional(silver, season, table)
        if frame is None or entry_id is None:
            return frame
        return frame[frame["entry_id"] == entry_id]

    evidence = Evidence(
        season=season,
        player_gameweek=read_table_optional(silver, season, Table.PLAYER_GAMEWEEK),
        players=read_table_optional(silver, season, Table.PLAYER),
        fixtures=read_table_optional(silver, season, Table.FIXTURE),
        picks=owners(Table.ENTRY_PICK),
        entry_gameweeks=owners(Table.ENTRY_GAMEWEEK),
        chips=owners(Table.ENTRY_CHIP),
        transfers=owners(Table.ENTRY_TRANSFER),
        gameweeks=read_table_optional(silver, season, Table.GAMEWEEK),
        price_history=read_table_optional(silver, season, Table.PRICE_HISTORY),
    )
    written: list[Output] = []
    for gameweek in gameweeks:
        reason = unready(
            gameweek,
            evidence,
            entry_id=entry_id,
            lagging_share=ctx.config.quality.maximum_lagging_player_share,
        )
        if reason is not None:
            log.info("evaluation.waiting", extra={"gameweek": gameweek, "reason": reason})
            continue
        try:
            evaluation = build_evaluation(
                gameweek,
                evidence=evidence,
                advice=read_advice(ctx.layout, gameweek),
                predictions=read_predictions(ctx.layout, gameweek),
                rules=rules,
                entry_id=entry_id,
                as_of=ctx.as_of,
                run_id=ctx.run_id,
            )
        except Exception as exc:
            log.warning("evaluation.failed", extra={"gameweek": gameweek, "error": repr(exc)})
            continue
        written.append(Output(path=record_evaluation(ctx.layout, evaluation)))
    return written


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
    weighed = option_set(
        deadline.gameweek,
        recommendation,
        {as_int(i): str(name) for i, name in lookup["web_name"].items()},
        digits=2,
    )

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

    return _run_stamp(snapshot.inputs.as_of, snapshot.config) | {
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
            # One home for what was weighed: `option_set`, in the hindsight optimum's shape
            # (ORC-11), which the ledger keeps so Last gameweek can set the two side by side.
            # `options` is derived from it, in its rounding, because the recommendation card, the
            # roll comparison and every week file before R1.4.1 read that older shape.
            "options": [
                {
                    "transfers": plan.transfers_count,
                    "hit_points": plan.hit_points,
                    "net_expected_points": plan.net_points,
                    "gain_over_roll": plan.gain_over_roll,
                    "moves": [move.describe() for move in option.moves],
                }
                for plan, option in zip(
                    weighed.all_options,
                    sorted(recommendation.options, key=lambda o: o.transfers),
                    strict=True,
                )
            ],
            "option_set": weighed.as_dict(),
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
