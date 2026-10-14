"""Model benchmark evaluation, registry, and accuracy calculation.

Consolidates the five-model registry, walk-forward evaluation, and all-player xP MAE
accuracy scoring into a deep module.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fpl_dof.publish.contract import CONTRACT_VERSION, Contract

#: Model entry: (harness_key, web_id, label, role, description). Display order.
MODEL_REGISTRY: tuple[tuple[str, str, str, str, str], ...] = (
    ("C3", "champion", "Champion (C3)", "champion", "Engine + minutes_v2, price/position captain"),
    ("C1", "challenger", "Challenger (C1)", "challenger", "Boosted xG + minutes model"),
    ("engine", "engine", "Engine", "comparison", "Original engine, engine captain"),
    ("A", "a", "Model A", "comparison", "Component xPts model"),
    ("A_odds", "a_odds", "A + odds", "comparison", "Model A with the odds team layer"),
)

CHAMPION_KEY = "C3"
CHAMPION_WEB_ID = "champion"

HARNESS_TO_WEB: dict[str, str] = {key: wid for key, wid, *_ in MODEL_REGISTRY}
WEB_TO_HARNESS: dict[str, str] = {wid: key for key, wid, *_ in MODEL_REGISTRY}
REGISTRY_BY_KEY: dict[str, tuple[str, str, str, str]] = {
    key: (wid, label, role, desc) for key, wid, label, role, desc in MODEL_REGISTRY
}
HISTORY_MODELS: tuple[tuple[str, str, str], ...] = tuple(
    (wid, label, role) for _, wid, label, role, _ in MODEL_REGISTRY
)


def build_xp_accuracy_season(
    name: str,
    kind: str,
    path: Path | str,
    *,
    subset: str = "all",
    id_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Compile accuracy metrics for a single season from an xp_scores CSV file."""
    ids = id_map if id_map is not None else HARNESS_TO_WEB
    csv_file = Path(path)
    gws: dict[int, dict[str, float]] = {}
    tot: dict[str, list[float]] = {}

    with csv_file.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("subset") != subset or not r.get("mae"):
                continue
            model_raw = r["model"]
            if model_raw not in ids:
                continue
            m = ids[model_raw]
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
        "missing_models": {m: "no saved predictions" for m in ids.values() if m not in tot},
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
    "CHAMPION_KEY",
    "CHAMPION_WEB_ID",
    "HARNESS_TO_WEB",
    "HISTORY_MODELS",
    "MODEL_REGISTRY",
    "REGISTRY_BY_KEY",
    "WEB_TO_HARNESS",
    "ModelBenchmarkBuilder",
    "build_xp_accuracy",
    "build_xp_accuracy_season",
]
