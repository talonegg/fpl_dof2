"""DL-67: the from-scratch squad solve runs preseason only, and never aborts an in-season run.

The failure this guards against is dated: on 2026-09-16 both CI runs died at ``optimise`` with an
infeasibility that had nothing to do with the in-season decision, and no transfer recommendation
was published. The stage's decision to run or skip is pure, so it is tested without a solver, and
the skipped artefact is validated against the contract it will be published under.
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.publish.contract import CONTRACT_VERSION, Contract, find_contracts_root
from fpl_dof.stages.optimise import SKIPPED_STATUS, skip_reason, skipped_payload


def _forecast(next_gameweek: int) -> pd.DataFrame:
    return pd.DataFrame([{"player_id": 1, "next_gameweek": next_gameweek}])


def test_preseason_solves() -> None:
    assert skip_reason(_forecast(1), "preseason") is None


def test_in_season_is_skipped_with_a_reason_naming_the_gameweek() -> None:
    reason = skip_reason(_forecast(5), "preseason")
    assert reason is not None
    assert "gameweek 5" in reason
    assert "week.json" in reason


def test_always_overrides_the_preseason_rule() -> None:
    assert skip_reason(_forecast(5), "always") is None


def test_an_empty_forecast_is_treated_as_preseason() -> None:
    """Nothing to read means nothing to skip on; the solver reports its own infeasibility."""
    assert skip_reason(pd.DataFrame(), "preseason") is None


def test_the_skipped_artefact_validates_against_the_squad_contract() -> None:
    payload = skipped_payload("run-1", "the season is under way")
    payload["contract_version"] = CONTRACT_VERSION
    payload["budget"] = 100.0
    Contract(root=find_contracts_root()).validate("squad", payload)
    assert payload["status"] == SKIPPED_STATUS
    assert payload["skipped"] is True
    assert payload["players"] == []
    assert payload["captain_id"] is None
