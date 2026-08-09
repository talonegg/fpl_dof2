"""Ingest stage — fetch sources into bronze. Implemented in E0-S2."""

from __future__ import annotations

from fpl_dof.pipeline import StageContext, StageResult


def run(ctx: StageContext) -> StageResult:
    del ctx
    return StageResult(metrics={"status": "not-implemented", "story": "E0-S2"})
