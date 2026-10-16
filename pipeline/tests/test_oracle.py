"""Tests for pipeline/src/fpl_dof/week/oracle.py (E14-S3).

Verifies the hindsight oracle transfer and lineup solver:
- Identifies optimal starting XI and captaincy using actual points;
- Solves optimal transfers within budget, club limits, and formation constraints;
- Emits baseline roll, optimal single transfer, and overall optimal ceiling.
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.rules.models import GameRules, Position
from fpl_dof.squad.state import HeldPlayer, Provenance, SquadState
from fpl_dof.week.oracle import solve_hindsight_optimal


def _player_row(
    pid: int, name: str, pos: str, tid: int, price: float, actual_pts: float
) -> dict[str, object]:
    return {
        "player_id": pid,
        "web_name": name,
        "position": pos,
        "team_id": tid,
        "price": price,
        "xp_next": actual_pts,
        "chance_of_playing_next_round": 100,
        "status": "a",
    }


def _build_test_squad_and_pool() -> tuple[SquadState, pd.DataFrame]:
    # 15 squad players: 2 GKP, 5 DEF, 5 MID, 3 FWD
    rows: list[dict[str, object]] = []
    squad_players: list[HeldPlayer] = []

    # GKP
    rows.append(_player_row(1, "Raya", "GKP", 1, 5.5, 6.0))
    rows.append(_player_row(2, "Ward", "GKP", 2, 4.0, 0.0))
    squad_players.extend(
        [
            HeldPlayer(
                player_id=1,
                position=Position.GKP,
                team_id=1,
                purchase_price=5.5,
                current_price=5.5,
                web_name="Raya",
            ),
            HeldPlayer(
                player_id=2,
                position=Position.GKP,
                team_id=2,
                purchase_price=4.0,
                current_price=4.0,
                web_name="Ward",
            ),
        ]
    )

    # DEF
    rows.append(_player_row(3, "Gabriel", "DEF", 1, 6.0, 7.0))
    rows.append(_player_row(4, "Saliba", "DEF", 1, 6.0, 6.0))
    rows.append(_player_row(5, "Alexander-Arnold", "DEF", 3, 7.0, 2.0))
    rows.append(_player_row(6, "Porro", "DEF", 4, 5.5, 2.0))
    rows.append(_player_row(7, "Greaves", "DEF", 5, 4.0, 1.0))
    squad_players.extend(
        [
            HeldPlayer(
                player_id=3,
                position=Position.DEF,
                team_id=1,
                purchase_price=6.0,
                current_price=6.0,
                web_name="Gabriel",
            ),
            HeldPlayer(
                player_id=4,
                position=Position.DEF,
                team_id=1,
                purchase_price=6.0,
                current_price=6.0,
                web_name="Saliba",
            ),
            HeldPlayer(
                player_id=5,
                position=Position.DEF,
                team_id=3,
                purchase_price=7.0,
                current_price=7.0,
                web_name="Alexander-Arnold",
            ),
            HeldPlayer(
                player_id=6,
                position=Position.DEF,
                team_id=4,
                purchase_price=5.5,
                current_price=5.5,
                web_name="Porro",
            ),
            HeldPlayer(
                player_id=7,
                position=Position.DEF,
                team_id=5,
                purchase_price=4.0,
                current_price=4.0,
                web_name="Greaves",
            ),
        ]
    )

    # MID
    rows.append(_player_row(8, "Saka", "MID", 1, 10.0, 3.0))
    rows.append(_player_row(9, "Palmer", "MID", 6, 10.5, 12.0))  # Captain candidate
    rows.append(_player_row(10, "Rogers", "MID", 7, 5.0, 2.0))
    rows.append(_player_row(11, "Smith Rowe", "MID", 8, 5.5, 2.0))
    rows.append(_player_row(12, "Winks", "MID", 2, 4.5, 2.0))
    squad_players.extend(
        [
            HeldPlayer(
                player_id=8,
                position=Position.MID,
                team_id=1,
                purchase_price=10.0,
                current_price=10.0,
                web_name="Saka",
            ),
            HeldPlayer(
                player_id=9,
                position=Position.MID,
                team_id=6,
                purchase_price=10.5,
                current_price=10.5,
                web_name="Palmer",
            ),
            HeldPlayer(
                player_id=10,
                position=Position.MID,
                team_id=7,
                purchase_price=5.0,
                current_price=5.0,
                web_name="Rogers",
            ),
            HeldPlayer(
                player_id=11,
                position=Position.MID,
                team_id=8,
                purchase_price=5.5,
                current_price=5.5,
                web_name="Smith Rowe",
            ),
            HeldPlayer(
                player_id=12,
                position=Position.MID,
                team_id=2,
                purchase_price=4.5,
                current_price=4.5,
                web_name="Winks",
            ),
        ]
    )

    # FWD
    rows.append(_player_row(13, "Haaland", "FWD", 9, 15.0, 16.0))  # Best Captain
    rows.append(_player_row(14, "Isak", "FWD", 10, 8.5, 2.0))
    rows.append(_player_row(15, "Wood", "FWD", 11, 6.0, 8.0))
    squad_players.extend(
        [
            HeldPlayer(
                player_id=13,
                position=Position.FWD,
                team_id=9,
                purchase_price=15.0,
                current_price=15.0,
                web_name="Haaland",
            ),
            HeldPlayer(
                player_id=14,
                position=Position.FWD,
                team_id=10,
                purchase_price=8.5,
                current_price=8.5,
                web_name="Isak",
            ),
            HeldPlayer(
                player_id=15,
                position=Position.FWD,
                team_id=11,
                purchase_price=6.0,
                current_price=6.0,
                web_name="Wood",
            ),
        ]
    )

    # Out of squad players available for transfer
    # Player 16: Mbeumo (MID, £7.0m, scored 15.0 pts)
    rows.append(_player_row(16, "Mbeumo", "MID", 12, 7.0, 15.0))
    # Player 17: Watkins (FWD, £9.0m, scored 14.0 pts)
    rows.append(_player_row(17, "Watkins", "FWD", 7, 9.0, 14.0))

    pool = pd.DataFrame(rows)
    state = SquadState(
        entry_id=1,
        gameweek=6,
        players=tuple(squad_players),
        bank=1.0,
        free_transfers=1,
        chips_used=(),
        provenance=Provenance.DECLARED,
    )
    return state, pool


def test_solve_hindsight_optimal_zero_transfers(game_rules: GameRules) -> None:
    state, pool = _build_test_squad_and_pool()
    result = solve_hindsight_optimal(6, state, pool, game_rules, max_transfers=0)

    assert result.gameweek == 6
    # Haaland should be captain (16 pts * 2 = 32 pts)
    assert result.baseline_roll.captain_id == 13
    assert result.baseline_roll.transfers_count == 0
    assert result.baseline_roll.hit_points == 0
    # Starters should include highest scoring squad players
    assert 13 in result.baseline_roll.starting  # Haaland (16)
    assert 9 in result.baseline_roll.starting  # Palmer (12)
    assert 15 in result.baseline_roll.starting  # Wood (8)
    assert 3 in result.baseline_roll.starting  # Gabriel (7)
    assert 4 in result.baseline_roll.starting  # Saliba (6)


def test_solve_hindsight_optimal_finds_winning_transfer(game_rules: GameRules) -> None:
    state, pool = _build_test_squad_and_pool()
    # Isak (£8.5m selling value) + £1.0m bank = £9.5m budget.
    # Watkins costs £9.0m and scored 14 pts (vs Isak 2 pts).
    # Mbeumo costs £7.0m and scored 15 pts (vs Rogers/Smith Rowe 2 pts).
    result = solve_hindsight_optimal(6, state, pool, game_rules, max_transfers=2)

    assert result.optimal_single is not None
    assert result.optimal_single.transfers_count == 1
    assert result.optimal_single.net_points > result.baseline_roll.net_points
    # The optimal single move should be bringing in Mbeumo (15 pts) or Watkins (14 pts)
    in_names = [m.player_in_name for m in result.optimal_single.moves]
    assert "Mbeumo" in in_names or "Watkins" in in_names
    assert result.optimal_overall.net_points >= result.optimal_single.net_points
