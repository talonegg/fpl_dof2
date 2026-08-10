"""The web contract.

The seam between Python and the browser (DP-04). These tests are about the contract holding, not
about the numbers: if the published shape drifts from the schema, the failure shows up in a browser,
which is the slowest place to find anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.publish.contract import (
    ARTEFACTS,
    CONTRACT_VERSION,
    Contract,
    ContractViolationError,
    find_contracts_root,
)
from fpl_dof.publish.typescript import generate


@pytest.fixture(scope="session")
def contract() -> Contract:
    return Contract(root=find_contracts_root())


def test_every_artefact_has_a_schema(contract: Contract) -> None:
    for artefact in ARTEFACTS:
        schema = contract.schema(artefact)
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert "description" in schema, f"{artefact} schema must explain what it is"


def test_a_missing_schema_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ContractViolationError, match="no schema"):
        Contract(root=tmp_path).schema("meta")


def test_contracts_root_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ContractViolationError):
        find_contracts_root(tmp_path)


def _meta() -> dict[str, Any]:
    return {
        "contract_version": 1,
        "generated_at": "2026-08-10T10:00:00Z",
        "run_id": "20260810T100000Z-abcd1234",
        "git_sha": None,
        "season": "2026/27",
        "next_gameweek": 1,
        "deadline_utc": "2026-08-21T17:30:00Z",
        "horizon_gameweeks": 6,
        "model": {
            "name": "xp_v0",
            "r_squared_on_price": 0.494,
            "price_dependence": "informative",
        },
        "counts": {"players": 573, "teams": 20},
    }


def test_a_valid_meta_passes(contract: Contract) -> None:
    contract.validate("meta", _meta())


def test_an_unknown_contract_version_is_rejected(contract: Contract) -> None:
    payload = _meta()
    payload["contract_version"] = 2
    with pytest.raises(ContractViolationError, match="contract_version"):
        contract.validate("meta", payload)


def test_an_unexpected_field_is_rejected(contract: Contract) -> None:
    """additionalProperties: false. A field the app does not know about must be a decision."""
    payload = _meta()
    payload["surprise"] = 1
    with pytest.raises(ContractViolationError):
        contract.validate("meta", payload)


def test_an_invalid_price_dependence_is_rejected(contract: Contract) -> None:
    payload = _meta()
    payload["model"]["price_dependence"] = "excellent"
    with pytest.raises(ContractViolationError, match=r"price_dependence|excellent"):
        contract.validate("meta", payload)


def test_a_missing_required_field_is_rejected(contract: Contract) -> None:
    payload = _meta()
    del payload["run_id"]
    with pytest.raises(ContractViolationError, match="run_id"):
        contract.validate("meta", payload)


def _player() -> dict[str, Any]:
    return {
        "id": 1,
        "name": "Raya",
        "full_name": "David Raya",
        "position": "GKP",
        "team": "ARS",
        "team_id": 1,
        "price": 6.0,
        "xp_next": 4.2,
        "xp_next_sd": 1.9,
        "xp_horizon": 19.3,
        "xp_horizon_sd": 8.7,
        "start_probability": 0.94,
        "confidence": "high",
        "selected_by_percent": 31.0,
        "status": "a",
        "news": "",
        "components": {
            "appearance": 2.0,
            "goals": 0.0,
            "assists": 0.0,
            "clean_sheet": 1.2,
            "goals_conceded": -0.4,
            "saves": 0.8,
            "defensive_contribution": 0.0,
            "bonus": 0.6,
            "cards": 0.0,
        },
    }


def test_a_valid_player_list_passes(contract: Contract) -> None:
    contract.validate("players", {"contract_version": 1, "players": [_player()]})


def test_uncertainty_is_mandatory_on_every_player(contract: Contract) -> None:
    """Invariant 6: a mean is never published without its uncertainty."""
    player = _player()
    del player["xp_next_sd"]
    with pytest.raises(ContractViolationError, match="xp_next_sd"):
        contract.validate("players", {"contract_version": 1, "players": [player]})


def test_a_negative_uncertainty_is_rejected(contract: Contract) -> None:
    player = _player()
    player["xp_next_sd"] = -1.0
    with pytest.raises(ContractViolationError):
        contract.validate("players", {"contract_version": 1, "players": [player]})


def test_an_unknown_position_is_rejected(contract: Contract) -> None:
    player = _player()
    player["position"] = "STRIKER"
    with pytest.raises(ContractViolationError):
        contract.validate("players", {"contract_version": 1, "players": [player]})


def test_a_start_probability_above_one_is_rejected(contract: Contract) -> None:
    player = _player()
    player["start_probability"] = 1.5
    with pytest.raises(ContractViolationError):
        contract.validate("players", {"contract_version": 1, "players": [player]})


def test_the_decomposition_is_mandatory(contract: Contract) -> None:
    """DP-09: every number carries its derivation."""
    player = _player()
    del player["components"]
    with pytest.raises(ContractViolationError, match="components"):
        contract.validate("players", {"contract_version": 1, "players": [player]})


def test_nothing_is_written_when_validation_fails(contract: Contract, tmp_path: Path) -> None:
    payload = _meta()
    del payload["season"]
    with pytest.raises(ContractViolationError):
        contract.write("meta", payload, tmp_path)
    assert not (tmp_path / "meta.json").exists()


def test_a_valid_payload_is_written(contract: Contract, tmp_path: Path) -> None:
    path = contract.write("meta", _meta(), tmp_path)
    assert path.name == "meta.json"
    assert json.loads(path.read_text(encoding="utf-8"))["season"] == "2026/27"


# --- the published artefacts themselves --------------------------------------------------------


def test_the_published_artefacts_validate(contract: Contract, layout_web: Path | None) -> None:
    """If a real run has published, its output must match the schemas it claims to obey."""
    if layout_web is None:
        pytest.skip("no published artefacts on this machine; run `fpl-dof publish`")
    for artefact in ARTEFACTS:
        payload = json.loads((layout_web / f"{artefact}.json").read_text(encoding="utf-8"))
        contract.validate(artefact, payload)


@pytest.fixture(scope="session")
def layout_web() -> Path | None:
    from fpl_dof.paths import find_repo_root

    root = find_repo_root()
    if root is None:
        return None
    directory = root / "data" / "web" / f"v{CONTRACT_VERSION}"
    return directory if directory.is_dir() else None


# --- generated TypeScript ----------------------------------------------------------------------


def test_typescript_is_generated_for_every_artefact(contract: Contract) -> None:
    source = generate(contract)
    for name in ("Meta", "Rules", "Players", "Squad"):
        assert f"export interface {name} " in source
    assert "export const CONTRACT_VERSION = 1;" in source
    assert "do not edit by hand" in source


def test_generated_types_carry_the_enums(contract: Contract) -> None:
    source = generate(contract)
    assert '"GKP" | "DEF" | "MID" | "FWD"' in source
    assert '"informative" | "thin" | "repricing"' in source


def test_generated_types_mark_optional_fields(contract: Contract) -> None:
    source = generate(contract)
    assert "git_sha?:" in source
    assert "run_id: string;" in source
