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
from fpl_dof.obs.manifest import RunManifest, git_sha, read_manifest, utcnow
from fpl_dof.paths import find_repo_root
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.fixtures import build_fixtures
from fpl_dof.publish.health import build_health
from fpl_dof.publish.history import build_history
from fpl_dof.publish.league import build_league
from fpl_dof.publish.typescript import write_types
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table, read_table_optional
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
    history = _history(ctx, season, rules)
    fixtures = _fixtures(ctx, season, teams, gameweeks)
    health = _health(ctx, gold)

    outputs = [
        Output(path=contract.write("meta", meta, destination)),
        Output(path=contract.write("rules", rules_payload, destination)),
        Output(path=contract.write("players", players, destination), rows=len(players["players"])),
        Output(path=contract.write("squad", squad_payload, destination)),
        Output(path=contract.write("history", history, destination), rows=len(history["players"])),
        Output(path=contract.write("fixtures", fixtures, destination), rows=len(fixtures["teams"])),
    ]

    # The mini-league, when one is configured (E6-S10). Configuring a league is the whole trigger:
    # with none set there is no artefact, and a stale one from a previous configuration is removed
    # rather than left to describe a league nobody is comparing against any more.
    # Artefacts whose absence is a normal published state, and which must therefore be *removed*
    # when absent rather than left behind: a stale file is not merely old, it is a false statement
    # about the present. Their names are collected so the copy into the app's public directory can
    # delete them there too — that directory is what the browser actually reads, so a stale file
    # surviving there is the only copy that would be believed.
    removed: list[str] = []

    # The data health artefact (E7-S6, DL-41). `None` only when this run's own manifest could not
    # be read, which makes every field of it unknowable — and an unreadable manifest is exactly the
    # moment a *stale* health page would be most misleading, since it would describe an earlier run
    # as though it were this one.
    if health is not None:
        outputs.append(Output(path=contract.write("health", health, destination)))
    else:
        removed.append("health.json")

    league = _league(ctx, season, gameweeks)
    if league is not None:
        outputs.append(Output(path=contract.write("league", league, destination)))
    else:
        removed.append("league.json")

    # The weekly decision and the multi-gameweek plan, when there are any. Their absence is normal
    # before the season starts (DL-20), so a missing file is not an error.
    for artefact, filename in (("week", WEEK_FILENAME), ("plan", PLAN_FILENAME)):
        source = gold / filename
        if source.exists():
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["contract_version"] = CONTRACT_VERSION
            outputs.append(Output(path=contract.write(artefact, payload, destination)))
        else:
            removed.append(f"{artefact}.json")

    for name in removed:
        (destination / name).unlink(missing_ok=True)

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
            for name in removed:
                (public / name).unlink(missing_ok=True)
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
            "history_players": len(history["players"]),
            "history_gameweeks_played": history["gameweeks_played"],
            "fixture_teams": len(fixtures["teams"]),
            "fixture_teams_rated": fixtures["model"]["teams_rated"],
            "league_entries": len(league["entries"]) if league else 0,
            "league_squads": league["league"]["squads_published"] if league else 0,
            "health_sources": len(health["sources"]) if health else 0,
            "health_sources_degraded": (
                sum(1 for s in health["sources"] if s["status"] == "degraded") if health else 0
            ),
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


def _history(ctx: StageContext, season: str, rules: GameRules) -> dict[str, Any]:
    """Per-player trend series for the current season (E6-S3, E6-S5, DL-37).

    Both source tables are optional: ``player_gameweek`` has no rows for a season nobody has played
    yet, and ``price_history`` has none until something has observed a price. Neither absence is a
    failure, and the artefact is published empty rather than omitted so a view has a shape to
    render "no gameweeks played yet" from (DP-15).
    """
    silver = ctx.layout.silver
    return build_history(
        player_gameweek=read_table_optional(silver, season, Table.PLAYER_GAMEWEEK),
        price_history=read_table_optional(silver, season, Table.PRICE_HISTORY),
        players=read_table(silver, season, Table.PLAYER),
        season=season,
        rules=rules,
        config=ctx.config.publish.history,
        contract_version=CONTRACT_VERSION,
    )


def _fixtures(
    ctx: StageContext, season: str, teams: pd.DataFrame, gameweeks: pd.DataFrame
) -> dict[str, Any]:
    """The model-derived fixture difficulty grid (E6-S8, DL-37).

    M2 is fitted on **this season's** results only. The silver table holds the backfilled prior
    seasons too, and it would be tempting to fit on them for a grid that says something useful in
    August — but FPL reassigns club ids between seasons and nothing here maps them, so a
    multi-season fit would rate this season's clubs on last season's ids. That is precisely the
    silent, plausible-looking wrongness DP-13 says to spend the effort avoiding. Preseason the
    model therefore has no ratings, every fixture scores neutral, and ``teams_rated`` says so.
    """
    silver = ctx.layout.silver
    from fpl_dof.forecast.models import TeamStrengthModel
    from fpl_dof.forecast.xp_v1 import team_matches

    history = read_table_optional(silver, season, Table.PLAYER_GAMEWEEK)
    current = (
        history[history["season"] == season]
        if history is not None and not history.empty
        else pd.DataFrame()
    )
    model = TeamStrengthModel()
    if not current.empty:
        model = model.fit(team_matches(current))

    first = 1
    if _has_next(gameweeks):
        first = as_int(gameweeks[gameweeks["is_next"]]["gameweek"].iloc[0])
    last_gameweek = as_int(gameweeks["gameweek"].max()) if not gameweeks.empty else first
    # The same window `plan.json` covers, so the ticker and the plan cannot disagree about how far
    # ahead "ahead" is — clipped at the end of the season rather than running off it.
    span = ctx.config.decision.horizon.gameweeks
    return build_fixtures(
        fixtures=read_table(silver, season, Table.FIXTURE),
        teams=teams,
        model=model,
        from_gameweek=first,
        to_gameweek=min(first + span - 1, last_gameweek),
        config=ctx.config.publish.fixtures,
        contract_version=CONTRACT_VERSION,
    )


def _health(ctx: StageContext, gold: Path) -> dict[str, Any] | None:
    """The data health artefact (E7-S6, FR-33, NFR-07, DL-41).

    This function is the effectful half (DP-03): it reads this run's manifest, the gate report, the
    bronze snapshot times and the recent manifests, and hands them to a pure builder. Every read is
    individually optional, and each absence has a distinct published meaning rather than a shared
    default — a missing gate report publishes as null, not as a pass.

    **The manifest read is against the file, not against an in-memory writer**, because the writer
    flushes after every stage and the file is therefore the same record anyone reading the run
    afterwards would see. This run's own `publish` stage is necessarily absent from it, and the
    run's `status` is null, which is the honest description of a run that has not finished.
    """
    manifest_path = ctx.layout.runs / ctx.run_id / "manifest.json"
    try:
        manifest = read_manifest(manifest_path)
    except OSError, ValueError:
        log.warning("publish.health_manifest_unreadable", extra={"path": str(manifest_path)})
        return None

    limit = ctx.config.publish.health.history_runs
    return build_health(
        manifest=manifest,
        gate_report=_gate_report(gold),
        observed=_source_observations(ctx),
        recent=_recent_manifests(ctx, limit=limit),
        generated_at=utcnow(),
        history_limit=limit,
        contract_version=CONTRACT_VERSION,
    )


def _gate_report(gold: Path) -> dict[str, Any] | None:
    """The gate report this run wrote, or ``None``.

    ``None`` is reachable in normal operation: `fpl-dof publish` can be run as a single stage, and
    then no gate report belongs to this run at all. Reading an older one and presenting it as this
    run's would be worse than showing none — a stale pass is indistinguishable from a real one.
    """
    from fpl_dof.stages.quality import REPORT_FILENAME

    path = gold / REPORT_FILENAME
    if not path.exists():
        return None
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        log.warning("publish.health_gate_report_unreadable", extra={"path": str(path)})
        return None
    return loaded


def _source_observations(ctx: StageContext) -> dict[str, dt.datetime]:
    """When each source's freshest snapshot was captured, keyed by the source's own label.

    The labels are the bronze store's top-level directory names, which the store writes from
    whatever the adapter called itself. This module never names one and never branches on one
    (Invariant 1) — it reads what is there and passes the strings through.

    The newest file is found by modification time, which is cheap over a tree that holds a snapshot
    per player per day; the capture time is then read from **that one sidecar**, because mtime is a
    property of the file and `fetched_at` is a property of the fetch, and they part company the
    moment a snapshot is copied between machines.
    """
    from fpl_dof.sources import BronzeStore

    bronze = BronzeStore(ctx.layout.bronze)
    if not bronze.root.is_dir():
        return {}

    observations: dict[str, dt.datetime] = {}
    for directory in sorted(p for p in bronze.root.iterdir() if p.is_dir()):
        sidecars = list(directory.rglob("*.meta.json"))
        if not sidecars:
            continue
        newest = max(sidecars, key=lambda p: p.stat().st_mtime)
        moment = _fetched_at(newest)
        if moment is not None:
            observations[directory.name] = moment
    return observations


def _fetched_at(sidecar: Path) -> dt.datetime | None:
    """``fetched_at`` from a snapshot sidecar, falling back to the file's own mtime."""
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        stamp = payload.get("fetched_at")
        if isinstance(stamp, str):
            return pd.Timestamp(stamp).tz_convert("UTC").to_pydatetime()
    except OSError, ValueError:
        pass
    try:
        return dt.datetime.fromtimestamp(sidecar.stat().st_mtime, tz=dt.UTC)
    except OSError:
        return None


def _recent_manifests(ctx: StageContext, *, limit: int) -> list[RunManifest]:
    """The most recent run manifests, this one included, for the rolling series.

    Read newest-first and stopped at the limit, so a `runs/` directory holding a season of runs
    costs the same as one holding thirty. Unreadable manifests are skipped rather than fatal: a run
    that died mid-write leaves a truncated file, and one bad file must not cost the whole series.
    """
    if limit <= 0 or not ctx.layout.runs.is_dir():
        return []

    manifests: list[RunManifest] = []
    for path in sorted(ctx.layout.runs.glob("*/manifest.json"), reverse=True):
        if len(manifests) >= limit:
            break
        try:
            manifests.append(read_manifest(path))
        except OSError, ValueError:
            continue
    return manifests


def _league(ctx: StageContext, season: str, gameweeks: pd.DataFrame) -> dict[str, Any] | None:
    """The configured mini-league, or ``None`` when there is no league to publish (E6-S10, FR-32).

    Three ways to get ``None``, and they are not the same thing: no league configured, a configured
    league the source could not read, and a league whose standings came back empty. Only the first
    is routine — the other two have already been recorded as ingest warnings by the time this runs,
    so the artefact's absence is never the only trace of them (DP-15).
    """
    league_id = ctx.config.entry.league_id
    if league_id is None:
        return None

    silver = ctx.layout.silver
    standings = read_table_optional(silver, season, Table.LEAGUE_STANDING)
    if standings is None or standings.empty:
        log.warning("publish.league_absent", extra={"league_id": league_id})
        return None

    return build_league(
        standings=standings,
        league_picks=read_table_optional(silver, season, Table.LEAGUE_PICK),
        entry_picks=read_table_optional(silver, season, Table.ENTRY_PICK),
        owner_entry_id=ctx.config.entry.team_id,
        gameweek=_latest_finished(gameweeks),
        squad_limit=ctx.config.entry.league_rival_limit,
        contract_version=CONTRACT_VERSION,
    )


def _latest_finished(gameweeks: pd.DataFrame) -> int | None:
    """The gameweek every published squad is read from. None before any has been scored (DL-20)."""
    if gameweeks.empty:
        return None
    finished = gameweeks[gameweeks["finished"]]
    return as_int(finished["gameweek"].max()) if not finished.empty else None


def _has_next(gameweeks: pd.DataFrame) -> bool:
    return not gameweeks.empty and bool(gameweeks["is_next"].any())


def _squad(squad: dict[str, Any], rules: GameRules) -> dict[str, Any]:
    payload = dict(squad)
    payload["contract_version"] = CONTRACT_VERSION
    payload["budget"] = rules.squad.budget
    return payload
