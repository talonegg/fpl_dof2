"""Shared builders for the E4 decision-engine tests.

A module rather than fixtures for the same reason ``squads.py`` is one: these are called with
arguments and composed, and one test file importing another gives that file two module names and
confuses type checking.

The pool here is deliberately the same trimmed one E1's tests use — six clubs, thirty-nine players.
That matters for one constraint in particular: a fifteen-man squad drawn from six clubs is far more
concentrated than a real one, which is exactly the case that makes C16's same-club starting cap
unsatisfiable and is therefore worth exercising rather than avoiding.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import pandas as pd

from fpl_dof.config.models import (
    ChipConfig,
    DecisionConfig,
    EntryConfig,
    HorizonConfig,
    OptimiserConfig,
    RiskConfig,
    SimulationConfig,
)
from fpl_dof.frames import gameweek_column, gameweek_sd_column
from fpl_dof.rules.models import GameRules
from fpl_dof.squad.state import SquadState, load_squad_state
from squads import legal_declaration
from squads import players as _players

#: Solver overrides used by every test here. The start-probability floor is off because the fixture
#: pool has no minutes model behind it, and it is E0's constraint rather than E4's.
OPTIMISER = OptimiserConfig(enforce_start_probability_floor=False)


def pool() -> pd.DataFrame:
    return _players()


def forecast(
    players: pd.DataFrame,
    gameweeks: tuple[int, ...],
    *,
    mean: Mapping[int, float] | float = 2.0,
    sd: Mapping[int, float] | float = 1.0,
    ownership: Mapping[int, float] | None = None,
    sd_by_gameweek: Mapping[int, Mapping[int, float]] | None = None,
) -> pd.DataFrame:
    """The forecast columns E4 reads, including per-gameweek ``mu`` and ``sigma``."""
    frame = players.copy()
    frame["xp_next"] = [_lookup(mean, int(pid)) for pid in frame["player_id"]]
    frame["xp_horizon"] = frame["xp_next"] * len(gameweeks)
    frame["xp_next_sd"] = [_lookup(sd, int(pid)) for pid in frame["player_id"]]
    frame["xp_horizon_sd"] = frame["xp_next_sd"] * 2
    frame["start_probability"] = 0.9
    frame["start_floor"] = 0.6
    frame["confidence"] = "medium"
    if ownership is not None:
        frame["selected_by_percent"] = [_lookup(ownership, int(pid)) for pid in frame["player_id"]]
    for gameweek in gameweeks:
        frame[gameweek_column(gameweek)] = frame["xp_next"]
        override = (sd_by_gameweek or {}).get(gameweek)
        frame[gameweek_sd_column(gameweek)] = (
            frame["xp_next_sd"]
            if override is None
            else [_lookup(override, int(pid)) for pid in frame["player_id"]]
        )
    return frame


def _lookup(source: Mapping[int, float] | float, player_id: int) -> float:
    if isinstance(source, Mapping):
        return float(source.get(player_id, 2.0))
    return float(source)


def state(
    rules: GameRules,
    players: pd.DataFrame,
    *,
    bank: float = 2.0,
    free_transfers: int = 1,
    gameweek: int = 2,
    chips_used: tuple[str, ...] = (),
) -> SquadState:
    return load_squad_state(
        entry_config=EntryConfig(
            team_id=1,
            declared_squad=legal_declaration(players),
            declared_bank=bank,
            declared_free_transfers=free_transfers,
            declared_chips_used=chips_used,
        ),
        rules=rules,
        players=players,
        next_gameweek=gameweek,
    )


def decision(
    *,
    gameweeks: int = 3,
    max_transfers: int = 2,
    dial: Literal["safe", "balanced", "aggressive"] = "balanced",
    simulate: bool = True,
    draws: int = 600,
    club_cap: int = 3,
    max_scenarios: int = 24,
    force_chip: dict[str, int] | None = None,
    forbid_chip: dict[str, tuple[int, ...]] | None = None,
    **horizon: int | float | str,
) -> DecisionConfig:
    """A small, fast configuration. Three gameweeks keeps the solves quick without making the
    free-transfer ledger trivial — two weeks would never reach the five-transfer cap."""
    return DecisionConfig(
        horizon=HorizonConfig(
            gameweeks=gameweeks,
            max_transfers_per_gameweek=max_transfers,
            solve_time_limit_seconds=30,
            scenario_time_budget_seconds=300,
            **horizon,
        ),
        risk=RiskConfig(dial=dial, same_club_starting_limit=club_cap),
        simulation=SimulationConfig(enabled=simulate, draws=draws),
        chips=ChipConfig(
            max_scenarios=max_scenarios,
            force_chip_gameweek=force_chip or {},
            forbid_chip_gameweeks=forbid_chip or {},
        ),
    )


def chip_table(bootstrap: dict[str, object]) -> pd.DataFrame:
    """The silver chip table, built from the recorded bootstrap fixture.

    Built from the real published windows rather than hand-written, because "set one expires at
    GW19" is exactly the fact this module must not be the one asserting (Invariant 2).
    """
    chips = bootstrap["chips"]
    assert isinstance(chips, list)
    return pd.DataFrame(
        [
            {
                "chip_id": chip["id"],
                "name": chip["name"],
                "chip_type": chip["chip_type"],
                "start_event": chip["start_event"],
                "stop_event": chip["stop_event"],
            }
            for chip in chips
        ]
    )


def fixture_table(players: pd.DataFrame, gameweeks: tuple[int, ...]) -> pd.DataFrame:
    """A fixture list where every club plays once a gameweek, plus a double in the last one.

    The double is not decoration: without a gameweek that differs in shape there is nothing for the
    chip calendar to find, and a calendar test that passes against a flat season is testing nothing.
    """
    teams = sorted({int(t) for t in players["team_id"]})
    rows = []
    fixture_id = 1
    for gameweek in gameweeks:
        pairs = list(zip(teams[::2], teams[1::2], strict=False))
        for home, away in pairs:
            rows.append(
                {
                    "fixture_id": fixture_id,
                    "gameweek": gameweek,
                    "kickoff_time": pd.Timestamp("2026-08-01", tz="UTC"),
                    "home_team_id": home,
                    "away_team_id": away,
                    "home_difficulty": 3,
                    "away_difficulty": 3,
                    "finished": False,
                }
            )
            fixture_id += 1
        if gameweek == gameweeks[-1] and len(teams) >= 2:
            rows.append(
                {
                    "fixture_id": fixture_id,
                    "gameweek": gameweek,
                    "kickoff_time": pd.Timestamp("2026-08-01", tz="UTC"),
                    "home_team_id": teams[1],
                    "away_team_id": teams[0],
                    "home_difficulty": 3,
                    "away_difficulty": 3,
                    "finished": False,
                }
            )
            fixture_id += 1
    return pd.DataFrame(rows)
