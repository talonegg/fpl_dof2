"""Transform stage — conform bronze into silver. Implemented in E0-S3."""

from __future__ import annotations

from fpl_dof.pipeline import StageContext, StageResult


def run(ctx: StageContext) -> StageResult:
    del ctx
    return StageResult(metrics={"status": "not-implemented", "story": "E0-S3"})
