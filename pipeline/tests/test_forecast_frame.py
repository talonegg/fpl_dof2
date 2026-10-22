"""MOD-02 — the forecast-frame contract, and captaincy as policy (DL-76).

Two seams are pinned here. The frame a forecaster hands the decision engine is validated before the
engine reads it, so a frame without variance never reaches a solver (Invariant 6). And the price and
position captain rule reads its fitted line as a policy input, not as a forecast column — which must
not move the champion's armband: the pinned captains below are what the forecast-column path chose
on the same snapshot before the change.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pydantic
import pytest

from conftest import before_next_deadline
from decisions import OPTIMISER, decision, fixture_table, forecast, pool, state
from fpl_dof.config.models import Config, TransferConfig
from fpl_dof.factory.registry import champion, digest, load_strategy
from fpl_dof.forecast import ForecastInputs, publishable
from fpl_dof.forecast.xp_v0 import MODEL_NAME as XP_V0
from fpl_dof.forecast.xp_v1 import MODEL_NAME as XP_V1
from fpl_dof.optimise.captain import PricePositionLine, pick_captains
from fpl_dof.optimise.frame import ForecastFrameError, validate_forecast_frame
from fpl_dof.optimise.plan import build_plan
from fpl_dof.optimise.squad import optimise_squad
from fpl_dof.optimise.transfer import recommend_transfers
from fpl_dof.rules.models import GameRules
from test_xp_v1_live import (
    CONFIG,
    TEAMS,
    _fixtures,
    _gameweeks,
    _player_gameweek,
    _players,
    _season_history,
)

GAMEWEEKS = (2, 3, 4)


def _snapshot(played: int) -> ForecastInputs:
    """The xp_v1 fixture league, with prices and points that give B0 a real slope per position."""
    history = _player_gameweek()
    slot = (history["player_id"] - 1) % 4
    history["price"] = 4.0 + slot * 0.5 + history["team_id"] * 0.3
    history["total_points"] = ((history.index * 7) % 11) / 2.0 + history["team_id"] * 0.4
    history = history[history["gameweek"] <= played]
    gameweeks = _gameweeks()
    gameweeks["finished"] = gameweeks["gameweek"] <= played
    return ForecastInputs(
        players=_players(history),
        teams=pd.DataFrame([{"team_id": team, "short_name": f"T{team}"} for team in TEAMS]),
        fixtures=_fixtures(),
        gameweeks=gameweeks,
        as_of=before_next_deadline(gameweeks),
        history=_season_history(history),
        player_gameweek=history,
    )


# Pinned from the forecast-column path (`captain_score`) on this snapshot, before MOD-02.
_XP_V1_SCORES = {
    1: 3.2429, 2: 2.9571, 3: 2.5929, 4: 3.25, 5: 3.5214, 6: 3.2357, 7: 3.1857, 8: 3.6071,
    9: 3.8, 10: 3.5143, 11: 3.7786, 12: 3.9643, 13: 4.0786, 14: 3.7929, 15: 4.3714,
    16: 4.3214, 999: 4.6786,
}  # fmt: skip
_XP_V0_SCORES = {
    1: 1.875, 2: 2.375, 3: 2.875, 4: 3.65, 5: 2.625, 6: 3.125, 7: 3.625, 8: 3.3, 9: 3.375,
    10: 3.875, 11: 4.375, 12: 2.95, 13: 4.125, 14: 4.625, 15: 5.125, 16: 2.6, 999: 2.25,
}  # fmt: skip


@pytest.mark.parametrize(
    ("played", "model", "scores", "captains"),
    [(8, XP_V1, _XP_V1_SCORES, (999, 15)), (2, XP_V0, _XP_V0_SCORES, (15, 14))],
)
def test_the_champions_captain_and_vice_are_unchanged(
    game_rules: GameRules,
    played: int,
    model: str,
    scores: dict[int, float],
    captains: tuple[int, int],
) -> None:
    result = publishable(_snapshot(played), game_rules, CONFIG)
    assert result.model == model
    assert "captain_score" not in result.frame.columns, "captaincy is policy, not forecast"
    assert result.captain_line is not None
    line = PricePositionLine.model_validate_json(result.captain_line.model_dump_json())
    got = line.scores(result.frame)
    assert {k: round(v, 4) for k, v in got.items()} == scores
    assert pick_captains(tuple(int(i) for i in result.frame["player_id"]), got) == captains


def test_nothing_played_means_no_captain_line(game_rules: GameRules) -> None:
    """Preseason: B0 has nothing to fit on, and the rule falls back rather than inventing a line."""
    inputs = _snapshot(8)
    preseason = ForecastInputs(
        players=inputs.players,
        teams=inputs.teams,
        fixtures=inputs.fixtures,
        gameweeks=_gameweeks().assign(finished=False),
        as_of=before_next_deadline(_gameweeks().assign(finished=False)),
        history=inputs.history,
        player_gameweek=None,
    )
    assert publishable(preseason, game_rules, CONFIG).captain_line is None


def test_the_champion_strategy_stamps_a_valid_frame_that_survives_parquet(
    game_rules: GameRules, tmp_path: Path, config: Config
) -> None:
    run_config = config.model_copy(update={"forecast": CONFIG})
    result = champion().forecast(_snapshot(8), game_rules, run_config)
    result.frame.to_parquet(tmp_path / "xp.parquet", index=False)
    frame = validate_forecast_frame(pd.read_parquet(tmp_path / "xp.parquet"))
    assert set(frame["strategy"]) == {champion().id}
    assert set(frame["strategy_digest"]) == {digest(champion(), run_config)}


def test_a_strategy_without_a_live_forecaster_says_so(
    game_rules: GameRules, config: Config
) -> None:
    with pytest.raises(NotImplementedError, match="a"):
        load_strategy("a").forecast(
            _snapshot(8), game_rules, config.model_copy(update={"forecast": CONFIG})
        )


def test_the_captain_line_refuses_an_unknown_position_or_a_non_finite_number() -> None:
    with pytest.raises(pydantic.ValidationError):
        PricePositionLine(intercept_by_position={"ST": 1.0}, slope_by_position={}, fallback=2.0)
    with pytest.raises(pydantic.ValidationError):
        PricePositionLine(intercept_by_position={}, slope_by_position={}, fallback=float("nan"))


# --- the frame is validated before the engine reads it -------------------------------------------


def _frame() -> pd.DataFrame:
    return forecast(pool(), GAMEWEEKS)


def test_a_well_formed_frame_passes_unchanged() -> None:
    frame = _frame()
    assert validate_forecast_frame(frame) is frame


@pytest.mark.parametrize("column", ["xp_next_sd", "xp_horizon_sd", "xp_gw_3_sd"])
def test_a_frame_missing_an_sd_column_is_refused(column: str) -> None:
    with pytest.raises(ForecastFrameError, match=column):
        validate_forecast_frame(_frame().drop(columns=column))


@pytest.mark.parametrize("bad", [-0.5, np.nan])
@pytest.mark.parametrize("column", ["xp_next_sd", "xp_horizon_sd", "xp_gw_2_sd"])
def test_a_negative_or_missing_sd_is_refused(column: str, bad: float) -> None:
    frame = _frame()
    frame.loc[0, column] = bad
    with pytest.raises(ForecastFrameError, match=column):
        validate_forecast_frame(frame)


def _entry_points(rules: GameRules) -> dict[str, Callable[[pd.DataFrame], object]]:
    squad = pool()
    held = state(rules, squad, gameweek=GAMEWEEKS[0])
    return {
        "recommend_transfers": lambda f: recommend_transfers(
            f, held, rules, TransferConfig(), OPTIMISER
        ),
        "optimise_squad": lambda f: optimise_squad(f, rules, OPTIMISER),
        "build_plan": lambda f: build_plan(
            players=f,
            state=held,
            rules=rules,
            decision=decision(gameweeks=len(GAMEWEEKS), simulate=False),
            optimiser=OPTIMISER,
            fixtures=fixture_table(squad, GAMEWEEKS),
        ),
    }


@pytest.mark.parametrize("entry", ["recommend_transfers", "optimise_squad", "build_plan"])
def test_every_engine_entry_point_refuses_a_frame_without_variance(
    game_rules: GameRules, entry: str
) -> None:
    run = _entry_points(game_rules)[entry]
    with pytest.raises(ForecastFrameError, match="xp_next_sd"):
        run(_frame().drop(columns="xp_next_sd"))
    negative = _frame()
    negative["xp_horizon_sd"] = -1.0
    with pytest.raises(ForecastFrameError, match="xp_horizon_sd"):
        run(negative)


def test_the_week_reads_the_captain_line_the_forecast_stage_wrote(tmp_path: Path) -> None:
    from fpl_dof.stages import week
    from fpl_dof.stages.forecast import CAPTAIN_LINE_FILENAME

    line = PricePositionLine(
        intercept_by_position={"MID": 1.0}, slope_by_position={"MID": 2.0}, fallback=0.5
    )
    (tmp_path / CAPTAIN_LINE_FILENAME).write_text(line.model_dump_json(), encoding="utf-8")
    assert week._read_captain_line(tmp_path) == line
    assert week._read_captain_line(tmp_path / "absent") is None
