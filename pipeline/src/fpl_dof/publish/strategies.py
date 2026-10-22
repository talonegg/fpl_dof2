"""The published strategy registry (``strategies.json``, MOD-03): generated from the registry files.

Pure: the registry is read through :mod:`fpl_dof.factory.registry`, nothing here restates it.
"""

from __future__ import annotations

from typing import Any

from fpl_dof.factory.registry import champion, digest, strategies


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
            }
            for s in strategies()
        ],
    }


__all__ = ["build_strategies"]
