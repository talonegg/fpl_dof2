"""Optimise stage — solve for the best legal squad from scratch, and write it to gold.

Preseason, this squad *is* the decision. In-season it is not: the owner has a squad, the decision
is the transfer plan from ``week`` and the multi-gameweek plan from ``decision``, and the wildcard
and free-hit scenarios in that plan already solve "pick fifteen from scratch" where it matters
(DL-15). So the solve runs only while the next deadline is gameweek 1 unless configured otherwise,
and is otherwise skipped with a reason rather than allowed to abort the run before the stages that
carry the in-season decision (DL-67, DP-15).
"""

from __future__ import annotations

import json

import pandas as pd

from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.squad import SolveReport, optimise_squad
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.rules.legality import Squad
from fpl_dof.silver.store import read_table
from fpl_dof.silver.tables import Table
from fpl_dof.stages.forecast import XP_FILENAME
from fpl_dof.stages.transform import read_rules

log = get_logger(__name__)

SQUAD_FILENAME = "squad.json"
SKIPPED_STATUS = "skipped"


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    gold = ctx.layout.gold / f"season={season.replace('/', '-')}"

    forecast = pd.read_parquet(gold / XP_FILENAME)
    forecast["start_floor"] = ctx.config.forecast.minimum_start_probability_for_xi
    teams = read_table(ctx.layout.silver, season, Table.TEAM)

    path = gold / SQUAD_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)

    reason = skip_reason(forecast, ctx.config.optimiser.squad_solve)
    if reason is not None:
        log.info("optimise.skipped", extra={"reason": reason})
        payload = skipped_payload(ctx.run_id, reason)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return StageResult(
            metrics={"status": SKIPPED_STATUS, "skipped_reason": reason},
            outputs=[Output(path=path, rows=0)],
        )

    squad, report = optimise_squad(forecast, rules, ctx.config.optimiser)

    payload = _squad_payload(squad, report, forecast, teams, ctx)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return StageResult(
        metrics={
            "status": report.status.value,
            "objective": round(report.objective, 3),
            "solve_seconds": round(report.solve_seconds, 3),
            "total_price": report.total_price,
            "formation": "-".join(str(report.formation.get(p, 0)) for p in ("DEF", "MID", "FWD")),
        },
        outputs=[Output(path=path, rows=len(squad.players))],
    )


def skip_reason(forecast: pd.DataFrame, squad_solve: str) -> str | None:
    """Why the from-scratch solve is not running, or ``None`` when it should (DL-67).

    Pure, so the rule is testable without a solver: the forecast carries the gameweek it was built
    for, and that is the only fact the decision needs.
    """
    if squad_solve == "always":
        return None
    next_gameweek = as_int(forecast["next_gameweek"].iloc[0]) if not forecast.empty else 1
    if next_gameweek <= 1:
        return None
    return (
        f"the season is under way (next deadline is gameweek {next_gameweek}); the from-scratch "
        "squad solve runs preseason only. This week's decision is the transfer recommendation "
        "in week.json, and the wildcard scenario in plan.json covers a full rebuild (DL-67). "
        "Set optimiser.squad_solve to 'always' to solve it anyway."
    )


def skipped_payload(run_id: str, reason: str) -> dict[str, object]:
    """The artefact's shape when nothing was solved: every field present, nothing invented."""
    return {
        "run_id": run_id,
        "status": SKIPPED_STATUS,
        "skipped": True,
        "skipped_reason": reason,
        "objective": 0.0,
        "solve_seconds": 0.0,
        "formation": {},
        "total_price": 0.0,
        "captain_id": None,
        "vice_captain_id": None,
        "bench_order": [],
        "players": [],
    }


def _squad_payload(
    squad: Squad,
    report: SolveReport,
    forecast: pd.DataFrame,
    teams: pd.DataFrame,
    ctx: StageContext,
) -> dict[str, object]:
    team_names = {as_int(row.team_id): str(row.short_name) for row in teams.itertuples()}
    lookup = forecast.set_index("player_id")
    starting = set(squad.starting)

    members = []
    for player in squad.players:
        row = lookup.loc[player.player_id]
        members.append(
            {
                "player_id": player.player_id,
                "web_name": str(row["web_name"]),
                "position": player.position.value,
                "team_id": player.team_id,
                "team": team_names.get(player.team_id, str(player.team_id)),
                "price": player.price,
                "xp_next": round(as_float(row["xp_next"]), 3),
                "xp_horizon": round(as_float(row["xp_horizon"]), 3),
                "xp_next_sd": round(as_float(row["xp_next_sd"]), 3),
                "xp_horizon_sd": round(as_float(row["xp_horizon_sd"]), 3),
                "start_probability": round(as_float(row["start_probability"]), 3),
                "confidence": str(row["confidence"]),
                "starting": player.player_id in starting,
                "is_captain": player.player_id == squad.captain,
                "is_vice_captain": player.player_id == squad.vice_captain,
                "components": {
                    column.removeprefix("component_"): round(as_float(row[column]), 3)
                    for column in forecast.columns
                    if column.startswith("component_")
                },
            }
        )

    return {
        "run_id": ctx.run_id,
        "status": report.status.value,
        "skipped": False,
        "objective": round(report.objective, 3),
        "solve_seconds": round(report.solve_seconds, 3),
        "formation": report.formation,
        "total_price": report.total_price,
        "captain_id": report.captain_id,
        "vice_captain_id": report.vice_captain_id,
        "bench_order": list(squad.bench_order),
        "players": members,
    }
