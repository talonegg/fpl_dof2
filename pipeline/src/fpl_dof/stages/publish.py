"""Publish stage — gold to the versioned web contract.

Writes ``data/web/v1/{meta,rules,players,squad}.json``, each validated against its schema before it
lands, and regenerates the TypeScript types the app compiles against.

The browser reads these files and nothing else. There is no request path from the client to any
code this project operates (Invariant 8, DL-03).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import git_sha, utcnow
from fpl_dof.paths import find_repo_root
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.typescript import write_types
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table
from fpl_dof.silver.tables import Table
from fpl_dof.stages.decision import PLAN_FILENAME
from fpl_dof.stages.forecast import XP_FILENAME
from fpl_dof.stages.optimise import SQUAD_FILENAME
from fpl_dof.stages.transform import read_rules
from fpl_dof.stages.week import WEEK_FILENAME

log = get_logger(__name__)

TYPES_PATH = ("web", "src", "contract", "types.ts")
WEB_PUBLIC_PATH = ("web", "public", "data", f"v{CONTRACT_VERSION}")


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    gold = ctx.layout.gold / f"season={season.replace('/', '-')}"

    forecast = pd.read_parquet(gold / XP_FILENAME)
    squad = json.loads((gold / SQUAD_FILENAME).read_text(encoding="utf-8"))
    teams = read_table(ctx.layout.silver, season, Table.TEAM)
    gameweeks = read_table(ctx.layout.silver, season, Table.GAMEWEEK)

    contract = Contract(root=find_contracts_root())
    destination = ctx.layout.web / f"v{CONTRACT_VERSION}"

    meta = _meta(ctx, forecast, teams, gameweeks, season)
    rules_payload = _rules(rules)
    players = _players(forecast, teams)
    squad_payload = _squad(squad, rules)

    outputs = [
        Output(path=contract.write("meta", meta, destination)),
        Output(path=contract.write("rules", rules_payload, destination)),
        Output(path=contract.write("players", players, destination), rows=len(players["players"])),
        Output(path=contract.write("squad", squad_payload, destination)),
    ]

    # The weekly decision and the multi-gameweek plan, when there are any. Their absence is normal
    # before the season starts (DL-20), so a missing file is not an error — but a *stale* one would
    # be a lie, and is therefore removed rather than left behind.
    for artefact, filename in (("week", WEEK_FILENAME), ("plan", PLAN_FILENAME)):
        source = gold / filename
        target = destination / f"{artefact}.json"
        if source.exists():
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["contract_version"] = CONTRACT_VERSION
            outputs.append(Output(path=contract.write(artefact, payload, destination)))
        elif target.exists():
            target.unlink()

    root = find_repo_root()
    if root is not None:
        types = write_types(contract, root.joinpath(*TYPES_PATH))
        outputs.append(Output(path=types))

        # The app is a static site: it reads these files from its own origin and never calls an
        # API (Invariant 8). Copying them into the app's public directory is what makes
        # `vite dev` and a built bundle serve identical data.
        #
        # **Only when this run's data root is the repository's own.** A run pointed at a temporary
        # directory — every test, and any experiment run with `--data-dir` — must not overwrite
        # what the app is serving. It did, and the result was a browser check quietly verifying an
        # 8-club test fixture while reporting success.
        public = root.joinpath(*WEB_PUBLIC_PATH)
        if _is_repo_data_root(ctx, root) and public.parent.parent.is_dir():
            public.mkdir(parents=True, exist_ok=True)
            for output in list(outputs):
                if output.path.suffix == ".json":
                    shutil.copy2(output.path, public / output.path.name)
            log.info("publish.copied_to_app", extra={"destination": str(public)})

    log.info(
        "publish.done",
        extra={"destination": str(destination), "players": len(players["players"])},
    )
    return StageResult(
        metrics={
            "contract_version": CONTRACT_VERSION,
            "players": len(players["players"]),
            "squad_players": len(squad_payload["players"]),
        },
        outputs=outputs,
    )


def _is_repo_data_root(ctx: StageContext, root: Path) -> bool:
    """Whether this run is writing to the repository's own ``data/`` directory."""
    try:
        return ctx.layout.root.resolve() == (root / "data").resolve()
    except OSError:
        return False


def _meta(
    ctx: StageContext,
    forecast: pd.DataFrame,
    teams: pd.DataFrame,
    gameweeks: pd.DataFrame,
    season: str,
) -> dict[str, Any]:
    next_gameweek = as_int(forecast["next_gameweek"].iloc[0])
    row = gameweeks[gameweeks["gameweek"] == next_gameweek]
    deadline = None
    if not row.empty:
        stamp = pd.Timestamp(row.iloc[0]["deadline_time"])
        deadline = stamp.tz_convert("UTC").to_pydatetime().isoformat().replace("+00:00", "Z")

    from fpl_dof.forecast.diagnostics import regress_xp_on_price

    regression = regress_xp_on_price(forecast)
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": _iso(utcnow()),
        "run_id": ctx.run_id,
        "git_sha": git_sha(find_repo_root()),
        "season": season,
        "next_gameweek": next_gameweek,
        "deadline_utc": deadline,
        "horizon_gameweeks": as_int(forecast["horizon_gameweeks"].iloc[0]),
        "model": {
            "name": "xp_v0",
            "r_squared_on_price": round(regression.r_squared, 4),
            "price_dependence": regression.verdict.value,
        },
        "counts": {"players": len(forecast), "teams": len(teams)},
    }


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _rules(rules: GameRules) -> dict[str, Any]:
    """Publish the rules the pipeline actually used, so the browser obeys the same numbers."""
    payload: dict[str, Any] = json.loads(rules.model_dump_json())
    payload["contract_version"] = CONTRACT_VERSION
    return payload


def _players(forecast: pd.DataFrame, teams: pd.DataFrame) -> dict[str, Any]:
    names = {as_int(row.team_id): str(row.short_name) for row in teams.itertuples()}
    components = [c for c in forecast.columns if c.startswith("component_")]

    players = []
    for record in forecast.to_dict(orient="records"):
        players.append(
            {
                "id": as_int(record["player_id"]),
                "name": str(record["web_name"]),
                "full_name": str(record.get("full_name", record["web_name"])),
                "position": str(record["position"]),
                "team": names.get(as_int(record["team_id"]), str(record["team_id"])),
                "team_id": as_int(record["team_id"]),
                "price": round(as_float(record["price"]), 1),
                "xp_next": round(as_float(record["xp_next"]), 3),
                "xp_next_sd": round(as_float(record["xp_next_sd"]), 3),
                "xp_horizon": round(as_float(record["xp_horizon"]), 3),
                "xp_horizon_sd": round(as_float(record["xp_horizon_sd"]), 3),
                "start_probability": round(as_float(record["start_probability"]), 3),
                "confidence": str(record["confidence"]),
                "selected_by_percent": round(as_float(record["selected_by_percent"]), 1),
                "status": str(record["status"]),
                "news": str(record.get("news") or ""),
                "components": {
                    column.removeprefix("component_"): round(as_float(record[column]), 3)
                    for column in components
                },
            }
        )
    return {"contract_version": CONTRACT_VERSION, "players": players}


def _squad(squad: dict[str, Any], rules: GameRules) -> dict[str, Any]:
    payload = dict(squad)
    payload["contract_version"] = CONTRACT_VERSION
    payload["budget"] = rules.squad.budget
    return payload
