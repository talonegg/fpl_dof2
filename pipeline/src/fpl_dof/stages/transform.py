"""Transform stage — conform bronze into validated silver.

Like ingest, this module names no source. It asks each enabled adapter for its contribution to the
canonical model, concatenates them, validates against the Pandera schemas, and writes Parquet.

It runs **offline**: transform reads bronze and never fetches. That is what makes the stage
reproducible — the same snapshots always produce the same silver, whatever the API is doing at the
time (DP-11).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.rules.build import build_game_rules
from fpl_dof.rules.models import ApiRules, GameRules
from fpl_dof.silver.store import append_table, write_table
from fpl_dof.silver.tables import OPTIONAL_TABLES, Table
from fpl_dof.sources import (
    BronzeStore,
    Fetcher,
    IngestRequest,
    OfflineWithoutSnapshotError,
    SourceAdapter,
    build,
    canonicalise,
)

log = get_logger(__name__)

RULES_FILENAME = "rules.json"

#: Tables where a later source must not silently overwrite an earlier one's row.
KEYS: dict[Table, list[str]] = {
    Table.PLAYER: ["player_id"],
    Table.TEAM: ["team_id"],
    Table.FIXTURE: ["fixture_id"],
    Table.GAMEWEEK: ["gameweek"],
    Table.PLAYER_SEASON_HISTORY: ["player_id", "season_name"],
    Table.PLAYER_GAMEWEEK: ["season", "gameweek", "player_code", "fixture_id"],
    Table.CHIP: ["chip_id"],
    Table.SET_PIECE_NOTE: ["team_id", "info_message"],
    Table.PRICE_HISTORY: ["observed_at", "player_id"],
    Table.ENTRY: ["entry_id"],
    Table.ENTRY_PICK: ["entry_id", "gameweek", "slot"],
    Table.ENTRY_TRANSFER: ["entry_id", "gameweek", "player_in_id", "player_out_id"],
    Table.ENTRY_CHIP: ["entry_id", "name", "gameweek"],
    Table.LEAGUE_STANDING: ["league_id", "entry_id"],
    Table.LEAGUE_PICK: ["entry_id", "gameweek", "slot"],
    Table.PLAYER_CROSSWALK: ["season", "source", "source_player_id"],
    Table.PLAYER_ADVANCED: ["season", "source", "source_player_id", "scope", "gameweek"],
    Table.PLAYER_METRIC: ["season", "player_code", "scope", "gameweek"],
    Table.TEAM_MATCH_EXPECTATION: ["season", "source", "captured_at", "home_team", "away_team"],
}

#: Tables that accumulate across runs instead of being rebuilt from the current snapshot.
#: Rebuilding these would destroy the only record of every day that has already passed.
APPENDED: frozenset[Table] = frozenset({Table.PRICE_HISTORY, Table.PLAYER_GAMEWEEK})


class NoBronzeError(RuntimeError):
    """Transform was asked to run before anything was ingested."""


def run(ctx: StageContext) -> StageResult:
    result = StageResult()
    bronze = BronzeStore(ctx.layout.bronze)

    with Fetcher(config=ctx.config.http, bronze=bronze, run_id=ctx.run_id) as fetcher:
        adapters = build(ctx.config.sources, fetcher)
        request = IngestRequest(
            run_id=ctx.run_id,
            offline=True,
            entry_id=ctx.config.entry.team_id,
            seasons=ctx.config.sources.backfill_seasons,
            season=ctx.config.rules.season,
        )

        collected: dict[Table, list[pd.DataFrame]] = {table: [] for table in Table}
        api_rules: ApiRules | None = None
        rules_sha: str | None = None

        for adapter in adapters:
            try:
                conformed = adapter.conform(request)
            except OfflineWithoutSnapshotError as exc:
                if not adapter.essential:
                    # Losing an enriching source costs its fields and nothing else (DP-15).
                    result.metrics[f"degraded.{adapter.name}"] = "no snapshot"
                    log.warning(
                        "transform.source_degraded",
                        extra={"source": adapter.name, "detail": str(exc)},
                    )
                    continue
                raise NoBronzeError(
                    f"no bronze snapshot for {exc.source}/{exc.resource}; "
                    "run `fpl-dof ingest` before `fpl-dof transform`"
                ) from exc
            except Exception as exc:
                # Deliberately broad, and deliberately only for a non-essential source. A scraped
                # page fails in ways nobody enumerated in advance (R-06), and a recommendation
                # missing one enrichment beats no recommendation before a deadline (NFR-15).
                if adapter.essential:
                    raise
                result.metrics[f"degraded.{adapter.name}"] = type(exc).__name__
                log.warning(
                    "transform.source_degraded",
                    extra={"source": adapter.name, "detail": f"{type(exc).__name__}: {exc}"},
                )
                continue

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

    merged_tables = {
        table.value: pd.concat(frames, ignore_index=True)
        for table, frames in collected.items()
        if frames
    }
    # Identity resolution and field precedence, both of which need to see every source at once and
    # neither of which may be visible to this stage as anything but a function call (Invariant 1).
    produced, resolution = canonicalise(merged_tables, season=season, config=ctx.config.sources)
    for name, frame in produced.items():
        collected[Table(name)] = [frame] if not frame.empty else []
    for warning in resolution.warnings:
        log.warning("transform.resolution", extra={"detail": warning})
    for source, counts in resolution.counts.items():
        result.metrics[f"resolved.{source}"] = sum(counts.values()) - counts.get("unmatched", 0)
        result.metrics[f"unmatched.{source}"] = counts.get("unmatched", 0)

    for adapter_name, credit in _attributions(adapters).items():
        result.metrics[f"attribution.{adapter_name}"] = credit

    for table, frames in collected.items():
        if not frames:
            if table in OPTIONAL_TABLES:
                # Normal: no team ID configured, a season not yet started, a club with no notes.
                # Degrading here is what lets the weekly loop run at all in preseason (DP-15).
                log.info("transform.table_absent", extra={"table": table.value})
                continue
            raise NoBronzeError(f"no source produced the {table.value!r} table")
        merged = pd.concat(frames, ignore_index=True)
        before = len(merged)
        merged = merged.drop_duplicates(subset=KEYS[table], keep="first").reset_index(drop=True)
        if len(merged) != before:
            log.warning(
                "transform.duplicates_dropped",
                extra={"table": table.value, "dropped": before - len(merged)},
            )
        writer = append_table if table in APPENDED else write_table
        path = writer(ctx.layout.silver, season, table, merged)
        result.metrics[f"rows.{table.value}"] = len(merged)
        result.outputs.append(Output(path=path, rows=len(merged)))
        log.info("transform.table", extra={"table": table.value, "rows": len(merged)})

    rules_path = _write_rules(ctx, rules, season)
    result.outputs.append(Output(path=rules_path))
    result.metrics["season"] = season
    result.metrics["rules_from_api"] = sum(1 for v in rules.derived.values() if v == "api")
    return result


def _attributions(adapters: Sequence[SourceAdapter]) -> dict[str, str]:
    """The credit each contributing source requires, keyed by source name.

    Carried as data from the source layer into the manifest so the requirement to attribute
    (NFR-10) travels with the data rather than living in a template somebody has to remember to
    update when a source is added.
    """
    return {adapter.name: adapter.attribution for adapter in adapters if adapter.attribution}


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
