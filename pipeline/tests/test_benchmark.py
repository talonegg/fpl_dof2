"""Tests for unified model evaluation, registry, and benchmark accuracy."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from fpl_dof.publish.benchmark import (
    CHAMPION_KEY,
    CHAMPION_WEB_ID,
    HARNESS_TO_WEB,
    HISTORY_MODELS,
    MODEL_REGISTRY,
    REGISTRY_BY_KEY,
    WEB_TO_HARNESS,
    ModelBenchmarkBuilder,
    build_xp_accuracy,
    build_xp_accuracy_season,
)
from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root


def test_model_registry_consistency() -> None:
    assert len(MODEL_REGISTRY) == 5
    assert CHAMPION_KEY == "C3"
    assert CHAMPION_WEB_ID == "champion"
    assert HARNESS_TO_WEB[CHAMPION_KEY] == CHAMPION_WEB_ID
    assert WEB_TO_HARNESS[CHAMPION_WEB_ID] == CHAMPION_KEY
    assert len(HISTORY_MODELS) == len(MODEL_REGISTRY)
    assert len(REGISTRY_BY_KEY) == len(MODEL_REGISTRY)


def test_build_xp_accuracy_season_and_validation(tmp_path: Path) -> None:
    csv_file = tmp_path / "xp_scores.csv"
    rows: list[dict[str, Any]] = [
        {"gw": 1, "model": "C3", "subset": "all", "n_rows": 500, "mae": 1.20},
        {"gw": 1, "model": "C1", "subset": "all", "n_rows": 500, "mae": 1.10},
        {"gw": 1, "model": "engine", "subset": "all", "n_rows": 500, "mae": 1.25},
        {"gw": 1, "model": "A", "subset": "all", "n_rows": 500, "mae": 1.30},
        # A row with a different subset should be ignored
        {"gw": 1, "model": "C3", "subset": "starters", "n_rows": 200, "mae": 1.50},
        {"gw": 2, "model": "C3", "subset": "all", "n_rows": 500, "mae": 1.15},
        {"gw": 2, "model": "C1", "subset": "all", "n_rows": 500, "mae": 1.05},
    ]

    with csv_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["gw", "model", "subset", "n_rows", "mae"])
        writer.writeheader()
        writer.writerows(rows)

    season_doc = build_xp_accuracy_season("2026/27", "prospective", csv_file)
    assert season_doc["season"] == "2026/27"
    assert season_doc["kind"] == "prospective"
    assert len(season_doc["gameweeks"]) == 2
    assert season_doc["gameweeks"][0]["mae"]["champion"] == 1.20
    assert season_doc["gameweeks"][0]["mae"]["challenger"] == 1.10
    # a_odds had no rows
    assert "a_odds" in season_doc["missing_models"]

    doc = build_xp_accuracy([("2026/27", "prospective", csv_file)])
    assert doc["contract_version"] == CONTRACT_VERSION
    assert len(doc["seasons"]) == 1

    contract = Contract(root=find_contracts_root())
    contract.validate("xp_accuracy", doc)


def test_builder_validates_accuracy_payload(tmp_path: Path) -> None:
    csv_file = tmp_path / "xp_scores.csv"
    with csv_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["gw", "model", "subset", "n_rows", "mae"])
        writer.writeheader()
        writer.writerow({"gw": 1, "model": "C3", "subset": "all", "n_rows": 100, "mae": 1.0})

    contract = Contract(root=find_contracts_root())
    builder = ModelBenchmarkBuilder(contract=contract)
    doc = builder.build_and_validate_accuracy([("2026/27", "prospective", csv_file)])
    assert doc["contract_version"] == CONTRACT_VERSION
    assert len(doc["seasons"]) == 1
