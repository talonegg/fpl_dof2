"""The standing backtest and the experiments store (MOD-08, DL-86).

:func:`grade` runs every registered strategy through the walk-forward harness on the same folds,
the champion first, each through ``Strategy.predictor`` and inside its own training window.
:func:`experiment_records` stamps one record per strategy (its digest, the data window, its metrics
and its paired deltas against the champion); the backtest stage writes them and CI appends them to
the ``ledger`` branch under ``experiments/``. :func:`latest_verdict` is how the model card finds the
verdict for the champion's current digest, and only that digest.

The baselines (B0, the mean, trailing form and the shadow monolith) stay the harness's own: they are
fitted from the fold's training rows, not forecast frames, so they are not registry strategies.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from fpl_dof.config import config_digest
from fpl_dof.config.models import Config
from fpl_dof.factory.registry import Strategy, effective_forecast_config, stamp, unrunnable
from fpl_dof.forecast.backtest import BacktestResult, Entrant, walk_forward
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.rules.models import GameRules

EXPERIMENTS_DIR = Path(__file__).resolve().parents[1] / "config" / "experiments"


class Experiment(BaseModel):
    """A declared experiment (05 section 5.3): the claim, what would falsify it, and how it ends.

    ``decision`` stays ``open`` until the owner records the outcome in a DL entry.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    hypothesis: str
    falsifier: str
    baseline: str
    variant: str
    metrics: tuple[Literal["mae", "spearman", "top_n_precision"], ...]
    decision_rule: str
    length: str
    graded_by: Literal["backtest", "shadow", "both"]
    decision: Literal["open", "promoted", "rejected", "extended", "shipped"]
    results: str = ""


def load_declared(
    registered: Iterable[Strategy], directory: Path = EXPERIMENTS_DIR
) -> tuple[Experiment, ...]:
    """Every declared experiment, validated; its baseline and variant must be registered."""
    known = {s.id for s in registered}
    out = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            exp = Experiment.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if exp.id != path.stem or not {exp.baseline, exp.variant} <= known:
            raise ValueError(
                f"{path.name}: id must match the file and both strategies be registered"
            )
        out.append(exp)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Graded:
    """One standing-backtest run: the harness's result and the strategies it could not grade."""

    result: BacktestResult
    skipped: Mapping[str, str] = field(default_factory=dict)
    """Strategy id -> why it was not graded (retired, no live code yet, or missing inputs)."""


def entrants(
    strategies: Sequence[Strategy],
    rules: GameRules,
    config: Config,
    inputs: ForecastInputs | None = None,
) -> tuple[list[Entrant], dict[str, str]]:
    """Every strategy the harness can grade, champion first, and why each other one is not.

    ``inputs`` are the silver tables a predictor reads beyond the history (A_odds' match odds); a
    strategy whose predictor cannot be built from them is skipped with the reason, never fatal.
    """
    ordered = sorted(strategies, key=lambda s: s.role != "champion")
    graded: list[Entrant] = []
    skipped: dict[str, str] = {}
    for strategy in ordered:
        problem = "retired" if strategy.role == "retired" else unrunnable(strategy)
        if problem is not None:
            skipped[strategy.id] = problem
            continue
        try:
            predictor = strategy.predictor(rules, config, inputs=inputs)
        except ValueError as exc:
            skipped[strategy.id] = str(exc)
            continue
        graded.append(
            Entrant(
                strategy.id,
                predictor,
                strategy.forecaster.training_window,
                effective_forecast_config(config.forecast, strategy.forecaster.config).features,
            )
        )
    if not graded or ordered[0].role != "champion" or graded[0].id != ordered[0].id:
        raise ValueError("the standing backtest needs a runnable champion to pair against")
    return graded, skipped


def grade(
    history: pd.DataFrame,
    strategies: Sequence[Strategy],
    rules: GameRules,
    config: Config,
    *,
    metrics: pd.DataFrame | None = None,
    inputs: ForecastInputs | None = None,
) -> Graded:
    """Walk every gradeable strategy forward over ``backtest.training_seasons``, one process
    per strategy (``backtest.strategy_workers``); one whose fit raises is not graded (D-32)."""
    graded, skipped = entrants(strategies, rules, config, inputs)
    result = walk_forward(
        history,
        graded,
        forecast_config=config.forecast,
        backtest_config=config.backtest,
        seasons=config.backtest.training_seasons or None,
        metrics=metrics,
        workers=config.backtest.strategy_workers,
    )
    return Graded(result=result, skipped={**skipped, **result.not_graded})


def run_config_digest(config: Config) -> str:
    """The digest of the run's validated configuration, without ``runtime`` (machine paths)."""
    return config_digest(config.model_dump(mode="json", exclude={"runtime"}))


def experiment_records(
    graded: Graded,
    strategies: Sequence[Strategy],
    config: Config,
    *,
    run_id: str,
    recorded_at: dt.datetime,
) -> list[dict[str, Any]]:
    """One stamped record per registered strategy, champion first.

    The champion's record also carries DL-21's verdict and the baselines it is read against, which
    is what the model card prints. A strategy the run could not grade gets a record saying why.
    """
    result = graded.result
    report = result.as_dict()
    common = {
        "run_id": run_id,
        "recorded_at": recorded_at.isoformat(),
        "config_digest": run_config_digest(config),
        "data_window": result.data_window(),
    }
    by_id = {s.id: s for s in strategies}
    records: list[dict[str, Any]] = []
    for sid, measured in result.strategies.items():
        strategy = by_id[sid]
        record: dict[str, Any] = {
            "strategy": stamp(strategy, config),
            "role": strategy.role,
            "training_window": strategy.forecaster.training_window,
            **common,
            "metrics": measured.as_dict(),
            "paired_vs_champion": (
                None
                if sid == result.champion
                else {m: d.as_dict() for m, d in result.paired[sid].items()}
            ),
        }
        if sid == result.champion:
            record.update(
                {
                    key: report[key]
                    for key in (
                        "verdict",
                        "beats_b0",
                        "beats_model_free",
                        "b0",
                        "model_free",
                        "mean_baseline",
                        "monolith",
                        "explainability_gap",
                        "minutes_calibration",
                        "warnings",
                    )
                }
            )
        records.append(record)
    for sid, reason in graded.skipped.items():
        strategy = by_id[sid]
        records.append(
            {
                "strategy": stamp(strategy, config),
                "role": strategy.role,
                "training_window": strategy.forecaster.training_window,
                **common,
                "not_graded": reason,
            }
        )
    return records


def latest_verdict(
    records: Iterable[Mapping[str, Any]], strategy_id: str, digest: str
) -> Mapping[str, Any] | None:
    """The most recent graded record for exactly this strategy and digest, or ``None``.

    A verdict for any other digest describes a different entry, config or code, so it is never
    returned in its place.
    """
    matching = [
        r
        for r in records
        if r.get("strategy", {}).get("id") == strategy_id
        and r.get("strategy", {}).get("digest") == digest
        and "verdict" in r
    ]
    return max(matching, key=lambda r: (r["recorded_at"], r["run_id"]), default=None)


__all__ = [
    "Experiment",
    "Graded",
    "entrants",
    "experiment_records",
    "grade",
    "latest_verdict",
    "load_declared",
    "run_config_digest",
]
