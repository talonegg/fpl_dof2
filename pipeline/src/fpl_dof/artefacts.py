"""The names and homes of the artefacts the stages hand to one another.

Gold file names, the rules file and the reader of it live here, not in the stage that happens to
write them, so no stage imports another (MOD-01). Gold directories come from
:meth:`~fpl_dof.paths.DataLayout.gold_for`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from fpl_dof.rules.models import GameRules

if TYPE_CHECKING:
    from fpl_dof.pipeline import StageContext

RULES_FILENAME = "rules.json"
XP_FILENAME = "expected_points.parquet"
CAPTAIN_LINE_FILENAME = "captain_line.json"
SQUAD_FILENAME = "squad.json"
BACKTEST_REPORT_FILENAME = "backtest.json"
QUALITY_REPORT_FILENAME = "quality.json"
BACKTEST_PREDICTIONS_FILENAME = "backtest-predictions.parquet"
#: Under ``DataLayout.ledger``: the standing backtest's records, one ``<run_id>.json`` per run, kept
#: on the ``ledger`` branch in CI (MOD-08).
EXPERIMENTS_DIRNAME = "experiments"
#: Under ``DataLayout.ledger``: the models history the standing backtest simulated, one
#: ``<run_id>.json`` per run (a list, one document per archive season), kept on ``ledger`` (ORC-06).
MODELS_HISTORY_DIRNAME = "models_history"
#: In gold: why this run's models history could not be built. Its presence fails backtest.yml's
#: own step for it, after the experiments record is appended (DP-15); a run that builds one removes it.
MODELS_HISTORY_FAILURE_FILENAME = "models-history-failure.txt"


class NoBronzeError(RuntimeError):
    """Transform was asked to run with nothing to conform, or a stage ran before it."""


def rules_path(ctx: StageContext, season: str) -> Path:
    return ctx.layout.silver / f"season={season.replace('/', '-')}" / RULES_FILENAME


def read_rules(ctx: StageContext, season: str) -> GameRules:
    path = rules_path(ctx, season)
    if not path.exists():
        raise NoBronzeError(f"{path} is missing; run `fpl-dof transform` first")
    return GameRules.model_validate(json.loads(path.read_text(encoding="utf-8")))
