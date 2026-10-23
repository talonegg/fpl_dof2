"""The backtest stage degrades, not crashes, when odds exist but another silver table is missing."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from fpl_dof.config import Config
from fpl_dof.paths import DataLayout
from fpl_dof.pipeline import StageContext
from fpl_dof.silver.tables import Table
from fpl_dof.stages import backtest


class _StopError(Exception):
    pass


def test_missing_table_means_no_inputs_not_a_crash(
    config: Config, layout: DataLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame({"x": [1]})
    present = {Table.PLAYER_GAMEWEEK, Table.TEAM_MATCH_EXPECTATION, Table.PLAYER}  # no TEAM etc.
    seen: dict[str, Any] = {}

    def grade(*_args: Any, **kwargs: Any) -> None:
        seen["inputs"] = kwargs["inputs"]
        raise _StopError

    monkeypatch.setattr(backtest, "read_rules", lambda *_a: type("R", (), {"season": "2026/27"})())
    monkeypatch.setattr(
        backtest, "read_table_optional", lambda _s, _y, t: frame if t in present else None
    )
    monkeypatch.setattr(backtest, "strategies", lambda: {})
    monkeypatch.setattr(backtest, "grade", grade)

    with pytest.raises(_StopError):
        backtest.run(StageContext(config=config, layout=layout, run_id="r"))
    assert seen["inputs"] is None
