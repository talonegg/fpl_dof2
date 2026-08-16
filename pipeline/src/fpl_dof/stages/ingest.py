"""Ingest stage — fetch every enabled source into bronze.

This module deliberately contains no source name. It asks the registry what is enabled and calls
the interface. Admitting a new source is a new module in ``sources/`` plus, at most, a config
entry — never a change here (Invariant 1, DP-01).
"""

from __future__ import annotations

from fpl_dof.obs.logging import get_logger
from fpl_dof.pipeline import Output, StageContext, StageResult
from fpl_dof.sources import BronzeStore, Fetcher, IngestRequest, build

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
            offline=ctx.options.offline,
            player_limit=ctx.options.player_limit,
            fast_path_only=ctx.options.fast_path_only,
            entry_id=ctx.config.entry.team_id,
            league_id=ctx.config.entry.league_id,
            league_rival_limit=ctx.config.entry.league_rival_limit,
            seasons=ctx.config.sources.backfill_seasons,
            season=ctx.config.rules.season,
        )

        for adapter in adapters:
            try:
                report = adapter.ingest(request)
            except Exception as exc:
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

    result.metrics["sources"] = len(adapters)
    result.metrics["cadence"] = "fast" if ctx.options.fast_path_only else "full"
    return result
