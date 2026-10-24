"""Publish stage — gold to the versioned web contract.

Writes ``data/web/v1/{meta,rules,players,squad}.json``, each validated against its schema before it
lands. The TypeScript types are `fpl-dof contract types`, checked in CI (WEB-03).

The browser reads these files and nothing else. There is no request path from the client to any
code this project operates (Invariant 8, DL-03).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from fpl_dof.artefacts import (
    AS_IF_PLAYED_DIRNAME,
    MODELS_HISTORY_DIRNAME,
    QUALITY_REPORT_FILENAME,
    SQUAD_FILENAME,
    XP_FILENAME,
    read_rules,
)
from fpl_dof.factory import (
    TeamStrengthModel,
    form_by_player_id,
    regress_xp_on_price,
    team_matches,
    trailing_form,
)
from fpl_dof.factory.registry import published_strategies
from fpl_dof.frames import as_float, as_int
from fpl_dof.gameweek import SilverTables, open_gameweek
from fpl_dof.gold import read_team_match_odds
from fpl_dof.obs.logging import get_logger
from fpl_dof.obs.manifest import RunManifest, git_sha, read_manifest
from fpl_dof.paths import find_repo_root
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.publish.benchmark import build_live_xp_accuracy, with_record
from fpl_dof.publish.contract import CONTRACT_MINOR, CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.publish.fixtures import build_fixtures
from fpl_dof.publish.health import build_health
from fpl_dof.publish.history import build_history
from fpl_dof.publish.league import build_league
from fpl_dof.publish.models_compare import build_models
from fpl_dof.publish.models_history import label_as_played
from fpl_dof.publish.season_log import build_log
from fpl_dof.publish.strategies import artefact_paths, build_strategies
from fpl_dof.rules.models import GameRules
from fpl_dof.silver.store import read_table, read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.sources import BronzeStore, supplying
from fpl_dof.week.cadence import current_gameweek
from fpl_dof.week.evaluation import read_evaluations
from fpl_dof.week.ledger import read_all_advice
from fpl_dof.week.schedule import next_fast_ingest

log = get_logger(__name__)

WEB_PUBLIC_PATH = ("web", "public", "data", f"v{CONTRACT_VERSION}")


def run(ctx: StageContext) -> StageResult:
    rules = read_rules(ctx, ctx.config.rules.season)
    season = rules.season
    gold = ctx.layout.gold_for(season)

    forecast = pd.read_parquet(gold / XP_FILENAME)
    squad = json.loads((gold / SQUAD_FILENAME).read_text(encoding="utf-8"))
    teams = read_table(ctx.layout.silver, season, Table.TEAM)
    gameweeks = read_table(ctx.layout.silver, season, Table.GAMEWEEK)

    contract = Contract(root=find_contracts_root())
    destination = ctx.layout.web / f"v{CONTRACT_VERSION}"

    meta = _meta(ctx, forecast, teams, gameweeks, season)
    rules_payload = _rules(rules)
    players = _players(forecast, teams, form=_form(ctx, season, forecast))
    squad_payload = _squad(squad, rules)
    history = _history(ctx, season, rules)
    fixtures = _fixtures(ctx, season, teams, gameweeks, gold)
    health = _health(ctx, gold)

    outputs = [
        Output(path=contract.write("meta", meta, destination)),
        Output(path=contract.write("rules", rules_payload, destination)),
        Output(path=contract.write("players", players, destination), rows=len(players["players"])),
        Output(path=contract.write("squad", squad_payload, destination)),
        Output(path=contract.write("history", history, destination), rows=len(history["players"])),
        Output(path=contract.write("fixtures", fixtures, destination), rows=len(fixtures["teams"])),
        Output(
            path=contract.write(
                "strategies",
                build_strategies(ctx.config, contract_version=CONTRACT_VERSION),
                destination,
            )
        ),
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

    # The season log (DL-69): absent until a team ID is configured and the game has recorded picks
    # for it, for the same reason `league.json` is — a stale one would describe a different owner.
    evaluations = read_evaluations(ctx.layout, ctx.config.entry.team_id)
    season_log = _season_log(ctx, season, evaluations)
    if season_log is not None:
        outputs.append(
            Output(
                path=contract.write("log", season_log, destination),
                rows=len(season_log["gameweeks"]),
            )
        )
    else:
        removed.append("log.json")

    # xP accuracy: the 2025/26 record, carried forward (WEB-04), and the live season's once a
    # gameweek with recorded predictions has been evaluated (ORC-05).
    live_accuracy = build_live_xp_accuracy(season, evaluations, contract_version=CONTRACT_VERSION)
    accuracy = with_record(live_accuracy, contract_version=CONTRACT_VERSION)
    outputs.append(Output(path=contract.write("xp_accuracy", accuracy, destination)))

    # The models history (ORC-06): the latest season the weekly backtest simulated, from `ledger`.
    # Absent until a backtest has recorded one; like models.json it never fails the publish.
    models_history = _models_history(ctx)
    published_history = False
    if models_history is not None:
        try:
            path = contract.write("models_history", models_history, destination)
            outputs.append(Output(path=path, rows=len(models_history["gameweeks"])))
            published_history = True
        except Exception as exc:
            log.warning("publish.models_history_dropped", extra={"error": repr(exc)})
    if not published_history:
        removed.append("models_history.json")

    # The five-model comparison: absent until the prospective harness has recorded a decision.
    models_payload = _models(ctx, season, gameweeks, evaluations)
    published_models = False
    if models_payload is not None:
        try:
            path = contract.write("models", models_payload, destination)
            outputs.append(Output(path=path, rows=len(models_payload["gameweeks"])))
            published_models = True
        except Exception as exc:  # optional artefact: never fails the champion's publish
            log.warning("publish.models_dropped", extra={"error": repr(exc)})
    if not published_models:
        removed.append("models.json")

    # The live season as if each model had played it (ORC-13), labelled from the live record in
    # models.json. Absent until a backtest has replayed a live gameweek; never fails the publish.
    played = _as_if_played(ctx, models_payload if published_models else None)
    published_played = False
    if played is not None:
        try:
            path = contract.write("as_if_played", played, destination)
            outputs.append(Output(path=path, rows=len(played["gameweeks"])))
            published_played = True
        except Exception as exc:
            log.warning("publish.as_if_played_dropped", extra={"error": repr(exc)})
    if not published_played:
        removed.append("as_if_played.json")

    # Every published strategy's week and plan, when there are any (MOD-04). Their absence is normal
    # before the season starts (DL-20), so a missing file is not an error. Each is validated against
    # the week or plan schema on the way out; a challenger's that fails is dropped rather than
    # failing the publish of everything else, while the champion's fails the run as it always has.
    for strategy in published_strategies():
        for artefact, filename in artefact_paths(strategy).items():
            if filename is None:
                continue
            source = gold / filename
            if not source.exists():
                removed.append(filename)
                continue
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["contract_version"] = CONTRACT_VERSION
            try:
                path = contract.write(artefact, payload, destination, filename=filename)
            except Exception as exc:
                if strategy.role == "champion":
                    raise
                log.warning(
                    "publish.strategy_dropped",
                    extra={"strategy": strategy.id, "artefact": filename, "error": repr(exc)},
                )
                removed.append(filename)
                continue
            outputs.append(Output(path=path))
    # And every week or plan file no published strategy writes now: the pre-MOD-04
    # week_challenger.json, an unpublished or deregistered strategy's pair, a plan switched off.
    removed += stale_strategy_files(destination)

    for name in removed:
        (destination / name).unlink(missing_ok=True)

    root = find_repo_root()
    if root is not None:
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
            for name in [*removed, *stale_strategy_files(public)]:
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


_STRATEGY_FILE = re.compile(r"^(week|plan)(_[a-z0-9_]+)?\.json$")


def stale_strategy_files(directory: Path) -> list[str]:
    """Week and plan files in ``directory`` that no published strategy writes now (MOD-04)."""
    current = {n for s in published_strategies() for n in artefact_paths(s).values() if n}
    return [
        p.name
        for p in directory.glob("*.json")
        if _STRATEGY_FILE.match(p.name) and p.name not in current
    ]


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

    regression = regress_xp_on_price(forecast)
    return {
        "contract_version": CONTRACT_VERSION,
        "contract_minor": CONTRACT_MINOR,
        "generated_at": _iso(ctx.as_of),
        **_run_stamp(ctx),
        "run_id": ctx.run_id,
        "git_sha": git_sha(find_repo_root()),
        "season": season,
        "next_gameweek": next_gameweek,
        "deadline_utc": deadline,
        "horizon_gameweeks": as_int(forecast["horizon_gameweeks"].iloc[0]),
        "model": {
            # Read from the artefact rather than written here. Which model ran is decided at
            # forecast time and can change between runs (DL-46); a literal in the publisher is a
            # claim about the past that nothing keeps true.
            "name": _model_name(forecast),
            "r_squared_on_price": round(regression.r_squared, 4),
            "price_dependence": regression.verdict.value,
        },
        "counts": {"players": len(forecast), "teams": len(teams)},
    }


def _model_name(forecast: pd.DataFrame) -> str:
    """Which model produced this frame, from the frame's own provenance column.

    Every frame the factory writes carries it (MOD-02); one that does not is said to be unrecorded
    rather than credited to a model by guesswork (DP-15).
    """
    if "model" not in forecast.columns or forecast.empty:
        return "unrecorded"
    return str(forecast["model"].iloc[0])


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _run_stamp(ctx: StageContext) -> dict[str, str]:
    """The run's snapshot ``as_of`` and what started it, as every advice carries them (ORC-03)."""
    return {"as_of": _iso(ctx.as_of), "trigger": ctx.config.runtime.trigger}


def _rules(rules: GameRules) -> dict[str, Any]:
    """Publish the rules the pipeline actually used, so the browser obeys the same numbers."""
    # The chip rules only score finished gameweeks, which the browser never does; not published.
    payload: dict[str, Any] = json.loads(rules.model_dump_json(exclude={"chips"}))
    payload["derived"].pop("chips", None)
    payload["contract_version"] = CONTRACT_VERSION
    return payload


def _form(
    ctx: StageContext, season: str, forecast: pd.DataFrame
) -> dict[int, tuple[float | None, int | None]]:
    """The model-free benchmark per player id, from this season's scored matches (DL-70)."""
    player_gameweek = read_table_optional(ctx.layout.silver, season, Table.PLAYER_GAMEWEEK)
    if player_gameweek is not None and "season" in player_gameweek.columns:
        player_gameweek = player_gameweek[player_gameweek["season"] == season]
    form = trailing_form(player_gameweek, as_of=pd.Timestamp(ctx.as_of))
    return form_by_player_id(form, forecast)


def _players(
    forecast: pd.DataFrame,
    teams: pd.DataFrame,
    *,
    form: dict[int, tuple[float | None, int | None]] | None = None,
) -> dict[str, Any]:
    names = {as_int(row.team_id): str(row.short_name) for row in teams.itertuples()}
    components = [c for c in forecast.columns if c.startswith("component_")]
    form = form or {}

    players = []
    for record in forecast.to_dict(orient="records"):
        form_value, form_rank = form.get(as_int(record["player_id"]), (None, None))
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
                "form_points_per_match": form_value,
                "form_rank": form_rank,
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


def _next_odds_check(ctx: StageContext, gameweeks: pd.DataFrame) -> str | None:
    """ORC-07's next check, reused for odds not posted yet: the next fast-ingest firing."""
    if gameweeks.empty:
        return None
    state = open_gameweek(SilverTables(gameweeks), (), ctx.as_of)
    if state is None:
        return None
    check = next_fast_ingest(now=ctx.as_of, state=state, config=ctx.config.schedule)
    return None if check is None else _iso(check)


def _fixtures(
    ctx: StageContext, season: str, teams: pd.DataFrame, gameweeks: pd.DataFrame, gold: Path
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
    history = read_table_optional(silver, season, Table.PLAYER_GAMEWEEK)
    current = (
        history[history["season"] == season]
        if history is not None and not history.empty
        else pd.DataFrame()
    )
    model = TeamStrengthModel(config=ctx.config.forecast.team_strength)
    if not current.empty:
        model = model.fit(team_matches(current))

    first = current_gameweek(gameweeks, ctx.as_of) if not gameweeks.empty else 1
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
        odds=read_team_match_odds(gold, season=season),
        odds_next_check=_next_odds_check(ctx, gameweeks),
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
        quarantined=BronzeStore(ctx.layout.bronze).quarantined(),
        recent=_recent_manifests(ctx, limit=limit),
        generated_at=ctx.as_of,
        history_limit=limit,
        contract_version=CONTRACT_VERSION,
        catalogue=_source_catalogue(ctx),
        # The same limit the snapshot-freshness gate warns at, so the page and the gate agree on
        # what "stale" means rather than holding two opinions (DL-41).
        stale_after_seconds=ctx.config.quality.maximum_snapshot_age_hours * 3600,
    )


def _source_catalogue(ctx: StageContext) -> list[Any]:
    """Every source the Sources section lists (registry plus external), or none on failure.

    The environment is asked only whether a credential is present. A catalogue that cannot be
    built costs the page its labels and its not-set-up rows, never the publish (DP-15).
    """
    from fpl_dof.sources import describe

    try:
        return list(describe(ctx.config.sources, os.environ))
    except Exception as exc:
        log.warning("publish.health_catalogue_unavailable", extra={"error": repr(exc)})
        return []


def _gate_report(gold: Path) -> dict[str, Any] | None:
    """The gate report this run wrote, or ``None``.

    ``None`` is reachable in normal operation: `fpl-dof publish` can be run as a single stage, and
    then no gate report belongs to this run at all. Reading an older one and presenting it as this
    run's would be worse than showing none — a stale pass is indistinguishable from a real one.
    """
    path = gold / QUALITY_REPORT_FILENAME
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
    """
    return BronzeStore(ctx.layout.bronze).observed()


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
        league_gameweeks=read_table_optional(silver, season, Table.LEAGUE_GAMEWEEK),
        league_transfers=read_table_optional(silver, season, Table.LEAGUE_TRANSFER),
        owner_entry_id=ctx.config.entry.team_id,
        gameweek=_latest_finished(gameweeks),
        squad_limit=ctx.config.entry.league_rival_limit,
        contract_version=CONTRACT_VERSION,
    )


def _season_log(
    ctx: StageContext, season: str, evaluations: dict[int, dict[str, Any]]
) -> dict[str, Any] | None:
    """The season log from the evaluations, or ``None`` when there is no owner or no gameweek of
    theirs evaluated yet (DL-69, ORC-05)."""
    entry_id = ctx.config.entry.team_id
    if entry_id is None:
        return None
    return build_log(
        entry_id=entry_id,
        season=season,
        evaluations=evaluations,
        contract_version=CONTRACT_VERSION,
    )


def _models_history(
    ctx: StageContext, dirname: str = MODELS_HISTORY_DIRNAME
) -> dict[str, Any] | None:
    """The newest backtest record's latest season under ``ledger/models_history/`` (ORC-06), or
    under ``dirname``.

    Run ids sort by time, so the last readable file is the newest run; an unreadable one is logged
    and the one before it is used.
    """
    for path in sorted((ctx.layout.ledger / dirname).glob("*.json"), reverse=True):
        try:
            documents = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            log.warning("publish.models_history_unreadable", extra={"path": str(path)})
            continue
        if isinstance(documents, list) and documents and isinstance(documents[-1], dict):
            return {**documents[-1], "contract_version": CONTRACT_VERSION}
    return None


def _as_if_played(ctx: StageContext, models: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The newest live-season replay under ``ledger/as_if_played/``, labelled replayed or live
    from ``models`` (ORC-13)."""
    document = _models_history(ctx, AS_IF_PLAYED_DIRNAME)
    return None if document is None else label_as_played(document, models)


def _models(
    ctx: StageContext,
    season: str,
    gameweeks: pd.DataFrame | None = None,
    evaluations: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """models.json: the retired harness's record up to the switch, the live ledger from it.

    The frozen record is optional (no ``source_dir`` means the live ledger alone). A malformed
    input is logged and skipped: the comparison is optional and must never fail the publish of
    the champion's artefacts.
    """
    cfg = ctx.config.publish.models
    try:
        decisions: list[dict[str, Any]] = []
        scores: list[dict[str, Any]] = []
        statuses: dict[int, Any] = {}
        if cfg.source_dir:
            root = Path(cfg.source_dir)
            decisions = [
                json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((root / "decisions").glob("GW*.json"))
            ]
            scores_path = root / "scores.csv"
            if scores_path.exists():
                scores = [
                    {str(k): v for k, v in r.items()}
                    for r in pd.read_csv(scores_path).to_dict("records")
                ]
            for p in sorted((root / "status").glob("GW*.json")):
                statuses[int(p.stem[2:])] = json.loads(p.read_text(encoding="utf-8"))
        players = read_table_optional(ctx.layout.silver, season, Table.PLAYER)
        ledger = read_all_advice(ctx.layout)
        # ORC-07: an awaited source is next checked at the next fast-ingest firing that fetches.
        state = None if gameweeks is None else open_gameweek(SilverTables(gameweeks), (), ctx.as_of)
        check = None
        if state is not None:
            check = next_fast_ingest(now=ctx.as_of, state=state, config=ctx.config.schedule)
        payload = build_models(
            season=season,
            decisions=decisions,
            scores=scores,
            frozen_tag=cfg.frozen_tag,
            contract_version=CONTRACT_VERSION,
            statuses=statuses,
            ledger=ledger,
            evaluations=evaluations,
            names={}
            if players is None
            else {as_int(r.player_id): str(r.web_name) for r in players.itertuples()},
            sources={t.value: supplying([t.value], ctx.config.sources) for t in Table},
            open_gameweek=None if state is None else state.gameweek,
            next_check=None if check is None else _iso(check),
        )
    except Exception as exc:
        log.warning("publish.models_dropped", extra={"error": repr(exc)})
        return None
    return None if payload is None else payload | _run_stamp(ctx)


def _latest_finished(gameweeks: pd.DataFrame) -> int | None:
    """The gameweek every published squad is read from. None before any has been scored (DL-20)."""
    if gameweeks.empty:
        return None
    finished = gameweeks[gameweeks["finished"]]
    return as_int(finished["gameweek"].max()) if not finished.empty else None


def _squad(squad: dict[str, Any], rules: GameRules) -> dict[str, Any]:
    payload = dict(squad)
    payload["contract_version"] = CONTRACT_VERSION
    payload["budget"] = rules.squad.budget
    return payload
