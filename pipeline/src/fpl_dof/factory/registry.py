"""The strategy registry: one committed YAML file per strategy (MOD-03, DL-86, DL-87).

A strategy is a forecaster paired with a decision policy (05 §5.1). Its file under
``config/strategies/`` is the single home of its id, label, role and recipe: the published
``strategies.json``, every artefact's ``strategy`` stamp and every builder that names a model read
it from here. Legacy keys (the frozen harness's ``C3``, the web's old ``champion``) are aliases,
resolved once by :func:`resolve_alias`.

``Strategy.forecast`` is the orchestrator's way to a forecast frame (MOD-02); ``decide`` arrives
with MOD-04.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fpl_dof.config.models import CaptainRule, ForecastConfig
from fpl_dof.forecast import xp_v0, xp_v1
from fpl_dof.forecast.entry import Forecast, publishable
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.optimise.frame import STRATEGY_COLUMN, STRATEGY_DIGEST_COLUMN
from fpl_dof.rules.models import GameRules
from fpl_dof.shadow import c1
from fpl_dof.silver.tables import Table

STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "config" / "strategies"

#: Forecaster models with live code. A published strategy must name one of these.
LIVE_MODELS: frozenset[str] = frozenset({xp_v1.MODEL_NAME, xp_v0.MODEL_NAME, c1.MODEL_NAME})

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
    training_window: str = Field(description="What the forecaster is fitted on")


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

    def forecast(
        self, inputs: ForecastInputs, rules: GameRules, config: ForecastConfig
    ) -> Forecast:
        """This strategy's forecast frame, validated and stamped with its id and digest.

        Only the shipped ``xp_v1`` recipe (with its ``xp_v0`` cold-start fallback) has a live entry
        point; C1's runs inside the week stage until MOD-04, and config overrides and the frozen
        ports arrive with MOD-05. Asking for one of those is an error, never a quiet substitute.
        """
        recipe = self.forecaster
        if recipe.type != "recipe" or recipe.model != xp_v1.MODEL_NAME or recipe.config:
            raise NotImplementedError(
                f"{self.id}: no forecast entry point for {recipe.type} {recipe.model!r}"
                f"{' with config overrides' if recipe.config else ''} yet (MOD-04, MOD-05)"
            )
        result = publishable(inputs, rules, config)
        result.frame[STRATEGY_COLUMN] = self.id
        result.frame[STRATEGY_DIGEST_COLUMN] = digest(self)
        return result


def digest(strategy: Strategy) -> str:
    """sha256 of the entry as canonical JSON: changes whenever anything in its file does."""
    canonical = json.dumps(strategy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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
    champions = [s.id for s in entries if s.role == "champion"]
    if len(champions) != 1:
        raise RegistryError(f"exactly one champion is required, found {champions}")
    ids = {s.id for s in entries}
    counts = Counter(a for s in entries for a in s.aliases)
    for s in entries:
        for alias in s.aliases:
            if alias in ids or counts[alias] > 1:
                raise RegistryError(f"{s.id}: alias {alias!r} is another id or used twice")
        if s.published and s.forecaster.model not in LIVE_MODELS:
            raise RegistryError(
                f"{s.id}: published, but forecaster model {s.forecaster.model!r} has no live code"
            )


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


def stamp(strategy: Strategy) -> dict[str, str]:
    """The ``strategy`` field every per-strategy artefact carries: registry id and digest."""
    return {"id": strategy.id, "digest": digest(strategy)}


__all__ = [
    "LIVE_MODELS",
    "STRATEGIES_DIR",
    "Forecaster",
    "Policy",
    "RegistryError",
    "Strategy",
    "champion",
    "digest",
    "load_registry",
    "load_strategy",
    "published_strategies",
    "resolve_alias",
    "stamp",
    "strategies",
]
