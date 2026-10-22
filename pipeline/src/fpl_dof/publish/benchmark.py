"""Model benchmark accuracy: all-player xP MAE per strategy, keyed by registry id (MOD-03)."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fpl_dof.factory.registry import resolve_alias, strategies
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract


def build_xp_accuracy_season(
    name: str,
    kind: str,
    path: Path | str,
    *,
    subset: str = "all",
) -> dict[str, Any]:
    """Compile accuracy metrics for a single season from an xp_scores CSV file.

    Rows carry the harness's model keys; each is resolved to its registry id, and a key the
    registry does not know is skipped rather than guessed at.
    """
    csv_file = Path(path)
    gws: dict[int, dict[str, float]] = {}
    tot: dict[str, list[float]] = {}

    with csv_file.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("subset") != subset or not r.get("mae"):
                continue
            m = resolve_alias(r["model"])
            if m is None:
                continue
            n = int(r["n_rows"])
            mae = float(r["mae"])

            gws.setdefault(int(r["gw"]), {})[m] = round(mae, 4)
            t = tot.setdefault(m, [0.0, 0.0])
            t[0] += mae * n
            t[1] += n

    return {
        "season": name,
        "kind": kind,
        "gameweeks": [{"gameweek": g, "phase": kind, "mae": gws[g]} for g in sorted(gws)],
        "pooled_mae": {m: round(s / n, 4) for m, (s, n) in tot.items() if n},
        "missing_models": {
            m: "no saved predictions" for m in (x.id for x in strategies()) if m not in tot
        },
    }


def build_xp_accuracy(
    sources: Sequence[tuple[str, str, Path | str]],
    *,
    contract_version: int = CONTRACT_VERSION,
    metric: str = "all-player MAE of next-GW xP vs actual FPL points (lower is better)",
    subset: str = "all",
) -> dict[str, Any]:
    """Assemble the ``xp_accuracy.json`` document from available score sources."""
    seasons = [
        build_xp_accuracy_season(name, kind, path, subset=subset)
        for name, kind, path in sources
        if Path(path).exists()
    ]
    return {
        "contract_version": contract_version,
        "metric": metric,
        "seasons": seasons,
    }


@dataclass(frozen=True)
class ModelBenchmarkBuilder:
    """Consolidated model benchmark evaluation and verification suite."""

    contract: Contract

    def validate(self, artefact: str, payload: Mapping[str, Any]) -> None:
        """Validate a benchmark payload against its JSON schema."""
        self.contract.validate(artefact, payload)

    def build_and_validate_accuracy(
        self, sources: Sequence[tuple[str, str, Path | str]]
    ) -> dict[str, Any]:
        doc = build_xp_accuracy(sources, contract_version=self.contract.version)
        self.validate("xp_accuracy", doc)
        return doc


__all__ = [
    "ModelBenchmarkBuilder",
    "build_xp_accuracy",
    "build_xp_accuracy_season",
]
