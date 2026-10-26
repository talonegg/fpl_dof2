"""Ingest stage — fetch every enabled source into bronze.

This module deliberately contains no source name. It asks the registry what is enabled and calls
the interface. Admitting a new source is a new module in ``sources/`` plus, at most, a config
entry — never a change here (Invariant 1, DP-01).
"""

from __future__ import annotations

import datetime as dt
import json

from fpl_dof.gameweek import SilverTables, open_gameweek
from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.sources import (
    BronzeStore,
    ChangeContext,
    Fetcher,
    IngestRequest,
    before_ingest,
    build,
    changed_kinds,
    gameweeks_from_bronze,
)

log = get_logger(__name__)


def run(ctx: StageContext) -> StageResult:
    bronze = BronzeStore(ctx.layout.bronze)
    result = StageResult()

    with Fetcher(
        config=ctx.config.http,
        bronze=bronze,
        run_id=ctx.run_id,
    ) as fetcher:
        adapters = build(ctx.config.sources, fetcher)
        if not adapters:
            raise RuntimeError("no sources are enabled; ingest has nothing to do")

        if ctx.options.fast_path_only:
            # Still no source name here: a source is skipped because it says nothing it offers is
            # cheap enough for this cadence, not because this module recognises it (Invariant 1).
            adapters = [adapter for adapter in adapters if adapter.has_fast_path()]
            if not adapters:
                raise RuntimeError(
                    "no enabled source declares a fast-path resource; there is nothing the fast "
                    "cadence can fetch"
                )

        request = IngestRequest(
            run_id=ctx.run_id,
            force_refresh=ctx.options.force_refresh,
            rebackfill=ctx.options.rebackfill,
            offline=ctx.options.offline,
            player_limit=ctx.options.player_limit,
            fast_path_only=ctx.options.fast_path_only,
            now=ctx.as_of,
            entry_id=ctx.config.entry.team_id,
            league_id=ctx.config.entry.league_id,
            league_rival_limit=ctx.config.entry.league_rival_limit,
            seasons=ctx.config.sources.backfill_seasons,
            season=ctx.config.rules.season,
        )

        before = before_ingest(bronze, adapters)
        for adapter in adapters:
            try:
                report = adapter.ingest(request)
            except Exception as exc:
                drift = getattr(exc, "diff", None)
                if drift:
                    log.error(
                        "ingest.schema_drift",
                        extra={"source": adapter.name, "diff": drift, "error": str(exc)},
                    )
                # An enriching source that cannot be reached costs its own fields. Only a source
                # that declares itself essential can stop the run (NFR-15, DP-15).
                if adapter.essential:
                    raise
                result.metrics[f"degraded.{adapter.name}"] = type(exc).__name__
                log.warning(
                    "ingest.source_degraded",
                    extra={"source": adapter.name, "detail": f"{type(exc).__name__}: {exc}"},
                )
                continue
            for resource, count in report.resources.items():
                result.metrics[f"{report.source}.{resource}"] = count
            result.metrics[f"{report.source}.network_calls"] = report.network_calls
            result.metrics[f"{report.source}.cache_hits"] = report.cache_hits
            for warning in report.warnings:
                log.warning("ingest.warning", extra={"source": report.source, "detail": warning})
            result.outputs.extend(Output(path=path) for path in report.snapshots)
        # Each malformed capture is already out of bronze; the run went on with the last valid one.
        result.metrics["quarantined"] = len(fetcher.quarantined)

        gameweek, window = _open_window(ctx)
        context = ChangeContext.of(window, ctx.config.schedule)
        kinds = changed_kinds(bronze, adapters, before, context)
    ctx.layout.changes.parent.mkdir(parents=True, exist_ok=True)
    ctx.layout.changes.write_text(
        json.dumps({"as_of": ctx.as_of.isoformat(), "gameweek": gameweek, "kinds": kinds}),
        encoding="utf-8",
    )
    result.metrics["changes"] = ",".join(kinds)
    result.outputs.append(Output(path=ctx.layout.changes))

    result.metrics["sources"] = len(adapters)
    result.metrics["cadence"] = "fast" if ctx.options.fast_path_only else "full"
    return result


def _open_window(
    ctx: StageContext,
) -> tuple[int | None, tuple[dt.datetime, dt.datetime | None] | None]:
    """The Open gameweek in the bronze just fetched, and when its matches can kick off: from its
    deadline to the next one's (ORC-02)."""
    gameweeks = gameweeks_from_bronze(ctx.layout.bronze)
    state = None if gameweeks is None else open_gameweek(SilverTables(gameweeks), (), ctx.as_of)
    if gameweeks is None or state is None:
        return None, None
    later = gameweeks.loc[gameweeks["deadline_time"] > state.deadline, "deadline_time"]
    return state.gameweek, (state.deadline, None if later.empty else later.min().to_pydatetime())
