"""Decision stage — the multi-gameweek plan and the chip calendar. E4.

Runs after ``week``, and deliberately as its own stage rather than folded into it. ``week`` answers
"what do I do before this deadline"; this answers "what is the plan, and when do the chips go". They
have different time horizons, different failure modes and — because the scenario enumeration solves
one MILP per chip scenario — very different runtimes, and a slow chip planner must not be able to
delay the thing that has a deadline attached to it.

It is skipped, with a reason, when no squad can be established. That is the normal preseason state
(DL-20) and must not fail a run that is otherwise fine (DP-15).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import utcnow
from fpl_dof.optimise.plan import as_dict, build_plan
from fpl_dof.optimise.squad import InfeasibleError
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.squad.state import SquadStateError, gameweek_price_index, load_squad_state
from fpl_dof.stages.forecast import XP_FILENAME
from fpl_dof.stages.transform import read_rules
from fpl_dof.week.deadline import next_deadline, to_contract

log = get_logger(__name__)

PLAN_FILENAME = "plan.json"


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    silver = ctx.layout.silver
    gold = ctx.layout.gold / f"season={season.replace('/', '-')}"

    gameweeks = read_table(silver, season, Table.GAMEWEEK)
    players = read_table(silver, season, Table.PLAYER)
    fixtures = read_table(silver, season, Table.FIXTURE)
    forecast = pd.read_parquet(gold / XP_FILENAME)
    forecast["start_floor"] = ctx.config.forecast.minimum_start_probability_for_xi

    deadline = next_deadline(
        gameweeks,
        now=utcnow(),
        local_zone=ctx.config.runtime.timezone,
        decide_by_hours=ctx.config.alerts.decide_by_hours_before_deadline,
    )
    last_gameweek = int(gameweeks["gameweek"].max())

    try:
        state = load_squad_state(
            entry_config=ctx.config.entry,
            rules=rules,
            players=players,
            next_gameweek=deadline.gameweek,
            picks=read_table_optional(silver, season, Table.ENTRY_PICK),
            transfers=read_table_optional(silver, season, Table.ENTRY_TRANSFER),
            entry=read_table_optional(silver, season, Table.ENTRY),
            chips=read_table_optional(silver, season, Table.ENTRY_CHIP),
            gameweek_prices=gameweek_price_index(
                read_table_optional(silver, season, Table.PLAYER_GAMEWEEK)
            ),
        )
    except SquadStateError as exc:
        log.warning("decision.skipped", extra={"reason": str(exc)})
        path = _write(
            gold,
            {
                "run_id": ctx.run_id,
                "skipped": True,
                "skipped_reason": str(exc),
                "deadline": to_contract(deadline),
            },
        )
        return StageResult(
            metrics={"status": "skipped", "skipped_reason": str(exc)},
            outputs=[Output(path=path)],
        )

    try:
        plan = build_plan(
            players=forecast,
            state=state,
            rules=rules,
            decision=ctx.config.decision,
            optimiser=ctx.config.optimiser,
            fixtures=fixtures,
            chips=read_table_optional(silver, season, Table.CHIP),
            last_gameweek=last_gameweek,
            # The most-captained player id is published upstream but the silver gameweek table
            # does not carry it yet (D-15). Passed as None rather than guessed: DL-24's callout
            # says what it knows, and "not available" is one of the things it can know.
            most_captained_id=None,
        )
    except InfeasibleError as exc:
        # An infeasible plan is a finding, not a crash: the message says *why*, and the weekly
        # recommendation from the `week` stage is unaffected and still publishable (DP-15).
        log.warning("decision.infeasible", extra={"reason": str(exc)})
        path = _write(
            gold,
            {
                "run_id": ctx.run_id,
                "skipped": True,
                "skipped_reason": str(exc),
                "deadline": to_contract(deadline),
            },
        )
        return StageResult(
            metrics={"status": "infeasible", "skipped_reason": str(exc)},
            outputs=[Output(path=path)],
        )

    payload: dict[str, object] = {
        "run_id": ctx.run_id,
        "skipped": False,
        "deadline": to_contract(deadline),
        **as_dict(plan),
    }
    path = _write(gold, payload)

    log.info("decision.summary", extra={"line": plan.rationale})
    return StageResult(
        metrics={
            "status": "ok",
            "gameweeks": len(plan.gameweeks),
            "solver": plan.solver,
            "solve_seconds": plan.solve_seconds,
            "is_hold": str(plan.is_hold),
            "chips": ",".join(f"{name}@{week}" for week, name in plan.chips_recommended),
            "candidate_pool": plan.pruning.pool_size,
            "alternatives": len(plan.alternatives),
        },
        outputs=[Output(path=path, rows=len(plan.gameweeks))],
    )


def _write(gold: Path, payload: dict[str, object]) -> Path:
    gold.mkdir(parents=True, exist_ok=True)
    path = gold / PLAN_FILENAME
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
