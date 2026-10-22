"""The published strategy registry (``strategies.json``, MOD-03): generated from the registry files.

Pure: the registry is read through :mod:`fpl_dof.factory.registry`, nothing here restates it.
"""

from __future__ import annotations

from typing import Any

from fpl_dof.factory.registry import Strategy, champion, digest, strategies


def _artefacts(s: Strategy) -> dict[str, str | None]:
    """Where the app finds the strategy's week and plan, relative to the data directory.

    The web reads these paths and never builds one; MOD-04 gives every strategy its own pair.
    """
    if not s.published:
        return {"week": None, "plan": None}
    if s.role == "champion":
        return {"week": "week.json", "plan": "plan.json" if s.policy.plan else None}
    # shortcut: one challenger file, until MOD-04 gives every strategy its own pair.
    return {"week": "week_challenger.json", "plan": None}


def build_strategies(*, contract_version: int) -> dict[str, Any]:
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
                "digest": digest(s),
                "plan": s.policy.plan,
                "artefacts": _artefacts(s),
            }
            for s in strategies()
        ],
    }


__all__ = ["build_strategies"]
