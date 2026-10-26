"""The strategy registry: one committed YAML file per strategy (MOD-03, DL-86, DL-87).

A strategy is a forecaster paired with a decision policy (05 §5.1). Its file under
``config/strategies/`` is the single home of its id, label, role and recipe: the published
``strategies.json``, every artefact's ``strategy`` stamp and every builder that names a model read
it from here. Legacy keys (the frozen harness's ``C3``, the web's old ``champion``) are aliases,
resolved once by :func:`resolve_alias`.

``Strategy.forecast`` is the orchestrator's way to a forecast frame (MOD-02), and
``Strategy.decision_policy`` resolves its policy for the one decision engine,
:func:`fpl_dof.decision.decide` (MOD-04).
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from fpl_dof.config.models import CaptainRule, Config, ForecastConfig
from fpl_dof.decision import DecisionPolicy
from fpl_dof.forecast import xp_v1
from fpl_dof.forecast.backtest import StrategyPredictor, TrainingWindow
from fpl_dof.forecast.entry import Forecast, publishable
from fpl_dof.forecast.inputs import ForecastInputs, MissingInputError
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.captain import PricePositionLine
from fpl_dof.optimise.frame import STRATEGY_COLUMN, STRATEGY_DIGEST_COLUMN
from fpl_dof.rules.models import GameRules
from fpl_dof.shadow import a, a_odds, c1
from fpl_dof.silver.tables import LIVE_TABLES, Table

log = get_logger(__name__)

STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "config" / "strategies"

#: The challenger recipes beside ``xp_v1``, by model name: each module's ``forecast`` is looked up
#: when it runs, so a test can replace it.
_CHALLENGERS: dict[str, ModuleType] = {
    c1.MODEL_NAME: c1,
    a.MODEL_NAME: a,
    a_odds.MODEL_NAME: a_odds,
}
#: Forecaster models :meth:`Strategy.forecast` runs as a refitted recipe (``xp_v0`` is ``xp_v1``'s
#: cold-start fallback, not a strategy's model). A published strategy must name one of these.
LIVE_MODELS: frozenset[str] = frozenset({xp_v1.MODEL_NAME, *_CHALLENGERS})

Role = Literal["champion", "challenger", "experiment", "retired"]
_ROLE_ORDER: tuple[Role, ...] = ("champion", "challenger", "experiment", "retired")


class RegistryError(ValueError):
    """The registry files are invalid. Nothing downstream may run on a registry that fails."""


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Forecaster(_Entry):
    type: Literal["recipe", "frozen"] = Field(
        description="recipe: refitted every run; frozen: fitted parameters published by the factory"
    )
    model: str = Field(description="The forecaster's model name, as its code names itself")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Overrides on the shipped forecast config"
    )
    training_window: TrainingWindow = Field(
        description=(
            "Which seasons of player-gameweek history the forecaster is fitted on. "
            "`current_season` keeps the champion's training set fixed when the archive is "
            "enabled; `all_seasons` takes every season silver holds."
        )
    )

    @field_validator("config")
    @classmethod
    def _config_overrides_the_shipped_forecast_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        effective_forecast_config(ForecastConfig(), value)  # unknown keys or bad values raise here
        return value


class Policy(_Entry):
    captain_rule: CaptainRule = Field(
        description=(
            "How captain and vice are picked inside the chosen XI. `price_position`: the highest "
            "B0 (per-position price line) score, then the second highest for vice; B0 is fitted "
            "by the forecaster on its training window and reaches the rule as its own input, "
            "never as a forecast column (DL-76, MOD-02). `model`: the solver's own "
            "xp-maximising captain. DL-76: the champion returns to `model` once the model card "
            "shows the model's top-20 precision above B0's."
        )
    )
    plan: bool = Field(description="Whether the multi-gameweek plan and chips are solved")


class Strategy(_Entry):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="Stable; never reused or a role")
    label: str
    description: str
    role: Role
    published: bool = Field(description="Runs every refresh and appears in the app")
    aliases: tuple[str, ...] = Field(default=(), description="Legacy ids that mean this strategy")
    forecaster: Forecaster
    policy: Policy
    requires: tuple[Table, ...] = Field(description="Silver tables the strategy reads")

    @field_validator("requires")
    @classmethod
    def _never_the_live_tables(cls, value: tuple[Table, ...]) -> tuple[Table, ...]:
        """The live gameweek's provisional rows are never a forecast's input (LIVE-01,
        Invariant 5)."""
        live = sorted(table.value for table in value if table in LIVE_TABLES)
        if live:
            raise ValueError(f"a strategy may not read the live gameweek's tables: {live}")
        return value

    def forecast(
        self,
        inputs: ForecastInputs,
        rules: GameRules,
        config: Config,
        *,
        fitted: Any = None,
    ) -> Forecast:
        """This strategy's forecast frame, validated and stamped with its id and digest.

        Live entry points: the ``xp_v1`` recipe (with its ``xp_v0`` cold-start fallback) and the
        challengers in ``shadow/`` (C1, A, A_odds), each on the shipped forecast config with this
        entry's overrides, each with its own variance and captain line. A ``frozen`` forecaster
        has no live code; asking for one is an error, never a quiet substitute (and the registry
        refuses to publish one, :func:`unrunnable`).
        A required silver table that is absent or empty is a :class:`MissingInputError` naming it,
        so the stage records "no advice", and which table it waits for, rather than a forecast on
        missing data. ``fitted``, an earlier :attr:`Forecast.fitted` of this strategy, predicts with
        those weights instead of a new fit: the in-sample replay's way in (ORC-13, DL-97).
        """
        recipe = self.forecaster
        if (problem := unrunnable(self)) is not None:
            raise NotImplementedError(f"{self.id}: {problem}")
        missing = [t.value for t in self.requires if _is_empty(inputs, t)]
        if missing:
            raise MissingInputError(
                f"{self.id}: required silver table(s) absent or empty: {missing}", tuple(missing)
            )
        if recipe.training_window == "current_season" and inputs.player_gameweek is not None:
            history = inputs.player_gameweek
            inputs = dataclasses.replace(
                inputs, player_gameweek=history[history["season"] == rules.season]
            )
        forecast_config = effective_forecast_config(config.forecast, recipe.config)
        if (module := _CHALLENGERS.get(recipe.model)) is not None:
            run: Callable[..., Forecast] = module.forecast
            # Passed only when given, so a test's stand-in ``forecast`` keeps its three arguments.
            extra = {"fitted": fitted} if fitted is not None else {}
            result = run(inputs, rules, forecast_config, **extra)
        else:
            result = publishable(inputs, rules, forecast_config, fitted=fitted)
        result.frame[STRATEGY_COLUMN] = self.id
        result.frame[STRATEGY_DIGEST_COLUMN] = digest(self, config)
        return result

    def predictor(
        self, rules: GameRules, config: Config, *, inputs: ForecastInputs | None = None
    ) -> StrategyPredictor:
        """This strategy's forecaster behind the walk-forward harness's fit-and-predict interface,
        on the shipped forecast config with this entry's overrides (MOD-05, for MOD-08).

        Its training window is the caller's to apply: the harness hands it the history to fit on.
        A_odds also reads the match odds in ``inputs``, and without them is an error naming them.
        """
        if (problem := unrunnable(self)) is not None:
            raise NotImplementedError(f"{self.id}: {problem}")
        forecast_config = effective_forecast_config(config.forecast, self.forecaster.config)
        if self.forecaster.model == c1.MODEL_NAME:
            return c1.C1Predictor(forecast_config, rules)
        if self.forecaster.model == a.MODEL_NAME:
            return a.APredictor(forecast_config, rules)
        if self.forecaster.model == a_odds.MODEL_NAME:
            if inputs is None or _is_empty(inputs, Table.TEAM_MATCH_EXPECTATION):
                raise ValueError(f"{self.id}: needs the {Table.TEAM_MATCH_EXPECTATION.value} odds")
            return a_odds.AOddsPredictor(
                forecast_config, rules, a_odds.team_odds(inputs, rules.season)
            )
        return xp_v1.ComponentPredictor(forecast_config, rules)

    def decision_policy(
        self, config: Config, captain_line: PricePositionLine | None
    ) -> DecisionPolicy:
        """The policy :func:`fpl_dof.decision.decide` runs this strategy with, on this config.

        ``captain_line`` is the forecaster's B0. A ``price_position`` rule with no line to apply
        (nothing played yet to fit B0 on) falls back to the solver's captain, and says so.
        """
        line = None
        if self.policy.captain_rule == "price_position":
            line = captain_line
            if line is None:
                log.warning(
                    "strategy.captain_rule_fallback",
                    extra={"strategy": self.id, "reason": "no history to fit B0"},
                )
        return DecisionPolicy(
            plan=self.policy.plan,
            captain_line=line,
            transfers=config.transfers,
            optimiser=config.optimiser,
            decision=config.decision,
            start_probability_floor=config.forecast.minimum_start_probability_for_xi,
        )


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    return {
        k: _deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
        for k, v in {**base, **over}.items()
    }


def effective_forecast_config(base: ForecastConfig, overrides: dict[str, Any]) -> ForecastConfig:
    """``base`` with ``overrides`` deep-merged and re-validated: an unknown key is an error."""
    if not overrides:
        return base
    merged = ForecastConfig.model_validate(_deep_merge(base.model_dump(), overrides))
    merged._horizon = base._horizon
    return merged


#: The silver tables the forecast inputs carry; a ``requires`` entry outside it cannot be checked
#: here.
_INPUT_OF_TABLE = {
    Table.PLAYER_GAMEWEEK: "player_gameweek",
    Table.FIXTURE: "fixtures",
    Table.PLAYER: "players",
    Table.TEAM: "teams",
    Table.GAMEWEEK: "gameweeks",
    Table.PLAYER_SEASON_HISTORY: "history",
    Table.PLAYER_METRIC: "metrics",
    Table.TEAM_MATCH_EXPECTATION: "match_odds",
}


def _is_empty(inputs: ForecastInputs, table: Table) -> bool:
    name = _INPUT_OF_TABLE.get(table)
    frame: pd.DataFrame | None = getattr(inputs, name) if name else None
    return name is not None and (frame is None or frame.empty)


def unrunnable(strategy: Strategy) -> str | None:
    """Why :meth:`Strategy.forecast` cannot run this entry yet, or ``None`` if it can (MOD-05)."""
    recipe = strategy.forecaster
    if recipe.type != "recipe":
        return (
            f"{recipe.type} forecaster {recipe.model!r} cannot run: no frozen-artefact loader yet"
        )
    if recipe.model not in LIVE_MODELS:
        return f"forecaster model {recipe.model!r} has no live code"
    return None


#: The packages whose source decides a strategy's advice: its models, its decision code, the squad
#: it is decided on and the config models whose defaults it runs with (05 §4).
_CODE_PACKAGES = ("forecast", "shadow", "factory", "optimise", "decision", "squad", "config")
#: The run's config sections a strategy reads: ``forecast`` and ``decision_policy`` between them.
_CONFIG_SECTIONS = frozenset({"forecast", "transfers", "optimiser", "decision"})
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def code_hash(root: Path = _PACKAGE_ROOT) -> str:
    """sha256 over the model and decision source files, by sorted relative path, line endings
    normalised so Windows and Linux checkouts agree."""
    files = sorted(p for pkg in _CODE_PACKAGES for p in (root / pkg).rglob("*.py"))
    h = hashlib.sha256()
    for path in files:
        h.update(path.relative_to(root).as_posix().encode() + b"\0")
        h.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


@functools.cache
def _shipped_code_hash() -> str:
    return code_hash()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(strategy: Strategy, config: Config, code: str | None = None) -> str:
    """sha256 of (entry, code, effective config): the registry entry and the config sections it
    reads, as canonical JSON, plus the source that decides its advice. Changes whenever any of the
    three does (NFR-06, DP-11). ``code`` is for tests."""
    entry = _canonical(strategy.model_dump(mode="json"))
    effective = _canonical(config.model_dump(mode="json", include=set(_CONFIG_SECTIONS)))
    parts = (entry, effective, code or _shipped_code_hash())
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def load_registry(directory: Path = STRATEGIES_DIR) -> tuple[Strategy, ...]:
    """Read and validate every ``*.yaml`` in ``directory``; champion first, then by role and id."""
    entries: list[Strategy] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            entry = Strategy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as exc:
            raise RegistryError(f"{path.name}: {exc}") from exc
        if entry.id != path.stem:
            raise RegistryError(f"{path.name}: id {entry.id!r} does not match its file name")
        entries.append(entry)
    _validate(entries)
    return tuple(sorted(entries, key=lambda s: (_ROLE_ORDER.index(s.role), not s.published, s.id)))


def _validate(entries: list[Strategy]) -> None:
    champions = [s for s in entries if s.role == "champion"]
    if len(champions) != 1:
        raise RegistryError(f"exactly one champion is required, found {[s.id for s in champions]}")
    if not champions[0].published:
        raise RegistryError(f"{champions[0].id}: the champion is the live advice; publish it")
    ids = {s.id for s in entries}
    counts = Counter(a for s in entries for a in s.aliases)
    for s in entries:
        for alias in s.aliases:
            if alias in ids or counts[alias] > 1:
                raise RegistryError(f"{s.id}: alias {alias!r} is another id or used twice")
        if s.published and (problem := unrunnable(s)) is not None:
            raise RegistryError(f"{s.id}: published, but {problem}")


@functools.cache
def strategies() -> tuple[Strategy, ...]:
    """Every registered strategy, champion first."""
    return load_registry()


def published_strategies() -> tuple[Strategy, ...]:
    return tuple(s for s in strategies() if s.published)


def champion() -> Strategy:
    return next(s for s in strategies() if s.role == "champion")


def load_strategy(strategy_id: str) -> Strategy:
    for s in strategies():
        if s.id == strategy_id:
            return s
    raise KeyError(f"no strategy {strategy_id!r} in the registry")


def resolve_alias(name: str) -> str | None:
    """The registry id that ``name`` (an id or a legacy alias) means, or ``None`` if unknown."""
    for s in strategies():
        if name == s.id or name in s.aliases:
            return s.id
    return None


def stamp(strategy: Strategy, config: Config) -> dict[str, str]:
    """The ``strategy`` field every per-strategy artefact carries: registry id and digest."""
    return {"id": strategy.id, "digest": digest(strategy, config)}


__all__ = [
    "LIVE_MODELS",
    "STRATEGIES_DIR",
    "Forecast",
    "ForecastInputs",
    "Forecaster",
    "MissingInputError",
    "Policy",
    "RegistryError",
    "Strategy",
    "champion",
    "digest",
    "effective_forecast_config",
    "load_registry",
    "load_strategy",
    "published_strategies",
    "resolve_alias",
    "stamp",
    "strategies",
    "unrunnable",
]
