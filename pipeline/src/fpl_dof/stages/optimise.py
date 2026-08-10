"""Optimise stage — solve for the best legal squad and write it to gold."""

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


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    gold = ctx.layout.gold / f"season={season.replace('/', '-')}"

    forecast = pd.read_parquet(gold / XP_FILENAME)
    forecast["start_floor"] = ctx.config.forecast.minimum_start_probability_for_xi
    teams = read_table(ctx.layout.silver, season, Table.TEAM)

    squad, report = optimise_squad(forecast, rules, ctx.config.optimiser)

    payload = _squad_payload(squad, report, forecast, teams, ctx)
    path = gold / SQUAD_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
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
        "objective": round(report.objective, 3),
        "solve_seconds": round(report.solve_seconds, 3),
        "formation": report.formation,
        "total_price": report.total_price,
        "captain_id": report.captain_id,
        "vice_captain_id": report.vice_captain_id,
        "bench_order": list(squad.bench_order),
        "players": members,
    }
