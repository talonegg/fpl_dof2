"""The published strategy registry (``strategies.json``, MOD-03): generated from the registry files.

Pure: the registry is read through :mod:`fpl_dof.factory.registry`, nothing here restates it.
"""

from __future__ import annotations

from typing import Any

from fpl_dof.config.models import Config
from fpl_dof.factory.registry import Strategy, champion, digest, strategies


def artefact_paths(s: Strategy) -> dict[str, str | None]:
    """The strategy's week and plan files: in gold, and relative to the published data directory.

    The one home of these names (MOD-04). The champion keeps ``week.json`` and ``plan.json``; every
    other published strategy writes ``week_<id>.json`` and, if its policy plans, ``plan_<id>.json``.
    The web reads these paths from ``strategies.json`` and never builds one.
    """
    if not s.published:
        return {"week": None, "plan": None}
    suffix = "" if s.role == "champion" else f"_{s.id}"
    return {"week": f"week{suffix}.json", "plan": f"plan{suffix}.json" if s.policy.plan else None}


def build_strategies(config: Config, *, contract_version: int) -> dict[str, Any]:
    return {
        "contract_version": contract_version,
        "champion": champion().id,
        "strategies": [
            {
                "id": s.id,
                "label": s.label,
                "description": s.description,
                "role": s.role,
                "published": s.published,
                "aliases": list(s.aliases),
                "digest": digest(s, config),
                "plan": s.policy.plan,
                "artefacts": artefact_paths(s),
            }
            for s in strategies()
        ],
    }


__all__ = ["artefact_paths", "build_strategies"]
