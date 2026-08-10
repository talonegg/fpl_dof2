"""Transform stage — conform bronze into validated silver.

Like ingest, this module names no source. It asks each enabled adapter for its contribution to the
canonical model, concatenates them, validates against the Pandera schemas, and writes Parquet.

It runs **offline**: transform reads bronze and never fetches. That is what makes the stage
reproducible — the same snapshots always produce the same silver, whatever the API is doing at the
time (DP-11).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.rules.build import build_game_rules
from fpl_dof.rules.models import ApiRules, GameRules
from fpl_dof.silver.store import write_table
from fpl_dof.silver.tables import Table
from fpl_dof.sources import BronzeStore, Fetcher, IngestRequest, OfflineWithoutSnapshotError, build

log = get_logger(__name__)

RULES_FILENAME = "rules.json"

#: Tables where a later source must not silently overwrite an earlier one's row.
KEYS: dict[Table, list[str]] = {
    Table.PLAYER: ["player_id"],
    Table.TEAM: ["team_id"],
    Table.FIXTURE: ["fixture_id"],
    Table.GAMEWEEK: ["gameweek"],
    Table.PLAYER_SEASON_HISTORY: ["player_id", "season_name"],
}


class NoBronzeError(RuntimeError):
    """Transform was asked to run before anything was ingested."""


def run(ctx: StageContext) -> StageResult:
    result = StageResult()
    bronze = BronzeStore(ctx.layout.bronze)

    with Fetcher(config=ctx.config.http, bronze=bronze, run_id=ctx.run_id) as fetcher:
        adapters = build(ctx.config.sources, fetcher)
        request = IngestRequest(run_id=ctx.run_id, offline=True)

        collected: dict[Table, list[pd.DataFrame]] = {table: [] for table in Table}
        api_rules: ApiRules | None = None
        rules_sha: str | None = None

        for adapter in adapters:
            try:
                conformed = adapter.conform(request)
            except OfflineWithoutSnapshotError as exc:
                raise NoBronzeError(
                    f"no bronze snapshot for {exc.source}/{exc.resource}; "
                    "run `fpl-dof ingest` before `fpl-dof transform`"
                ) from exc

            for name, frame in conformed.tables.items():
                if not frame.empty:
                    collected[Table(name)].append(frame)
            for warning in conformed.warnings:
                log.warning("transform.warning", extra={"detail": warning})
            if conformed.rules is not None:
                if api_rules is not None:
                    raise RuntimeError(
                        "more than one source published game rules; which one governs is a "
                        "decision that must be made explicitly, not by iteration order"
                    )
                api_rules = conformed.rules
                rules_sha = conformed.rules_snapshot_sha256

        if fetcher.network_calls:
            raise RuntimeError(
                f"transform made {fetcher.network_calls} network calls; it must read bronze only"
            )

    if api_rules is None:
        raise RuntimeError("no source published the game rules; they must not be assumed")

    rules = build_game_rules(api_rules, ctx.config.rules, source_snapshot_sha256=rules_sha)
    season = rules.season

    for table, frames in collected.items():
        if not frames:
            raise NoBronzeError(f"no source produced the {table.value!r} table")
        merged = pd.concat(frames, ignore_index=True)
        before = len(merged)
        merged = merged.drop_duplicates(subset=KEYS[table], keep="first").reset_index(drop=True)
        if len(merged) != before:
            log.warning(
                "transform.duplicates_dropped",
                extra={"table": table.value, "dropped": before - len(merged)},
            )
        path = write_table(ctx.layout.silver, season, table, merged)
        result.metrics[f"rows.{table.value}"] = len(merged)
        result.outputs.append(Output(path=path, rows=len(merged)))
        log.info("transform.table", extra={"table": table.value, "rows": len(merged)})

    rules_path = _write_rules(ctx, rules, season)
    result.outputs.append(Output(path=rules_path))
    result.metrics["season"] = season
    result.metrics["rules_from_api"] = sum(1 for v in rules.derived.values() if v == "api")
    return result


def rules_path(ctx: StageContext, season: str) -> Path:
    return ctx.layout.silver / f"season={season.replace('/', '-')}" / RULES_FILENAME


def _write_rules(ctx: StageContext, rules: GameRules, season: str) -> Path:
    path = rules_path(ctx, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rules.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_rules(ctx: StageContext, season: str) -> GameRules:
    path = rules_path(ctx, season)
    if not path.exists():
        raise NoBronzeError(f"{path} is missing; run `fpl-dof transform` first")
    return GameRules.model_validate(json.loads(path.read_text(encoding="utf-8")))
