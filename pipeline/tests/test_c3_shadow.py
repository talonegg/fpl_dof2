"""C3 (club-cap crash fix + price+position captain) and the C1 shadow's isolation."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from fpl_dof.config.models import EntryConfig, OptimiserConfig, TransferConfig
from fpl_dof.optimise.captain import apply_price_position_captain, pick_captains
from fpl_dof.optimise.transfer import recommend_transfers
from fpl_dof.rules.models import GameRules
from fpl_dof.shadow import c1
from fpl_dof.squad.state import SquadState, load_squad_state
from squads import legal_declaration
from squads import players as _players

CONFIG = OptimiserConfig(enforce_start_probability_floor=False)


def _forecast(players: pd.DataFrame, xp: dict[int, float] | None = None) -> pd.DataFrame:
    frame = players.copy()
    frame["xp_next"] = [(xp or {}).get(int(p), 2.0) for p in frame["player_id"]]
    frame["xp_horizon"] = frame["xp_next"] * 6
    frame["xp_next_sd"] = 1.0
    frame["xp_horizon_sd"] = 2.0
    frame["start_probability"] = 0.9
    frame["start_floor"] = 0.6
    frame["confidence"] = "medium"
    return frame


def _state(rules: GameRules, players: pd.DataFrame) -> SquadState:
    return load_squad_state(
        entry_config=EntryConfig(
            team_id=1, declared_squad=legal_declaration(players), declared_bank=0.0
        ),
        rules=rules,
        players=players,
        next_gameweek=2,
    )


def _over_cap(rules: GameRules) -> tuple[pd.DataFrame, SquadState, int]:
    """A legal held squad, then one held player 'moves' to a club the squad already has 3 of."""
    players = _players()
    state = _state(rules, players)
    held = sorted(state.player_ids())
    team = players.set_index("player_id")["team_id"]
    counts = Counter(int(team[i]) for i in held)
    full = next(c for c, n in counts.items() if n == rules.squad.club_limit)
    mover = next(i for i in held if int(team[i]) != full)
    moved = players.copy()
    moved.loc[moved.player_id == mover, "team_id"] = full
    return moved, state, full


def test_over_cap_squad_after_club_move_does_not_crash(game_rules: GameRules) -> None:
    moved, state, full = _over_cap(game_rules)
    # Make buying from the over-cap club tempting, so the test proves the cap still binds on buys.
    tempting = {
        int(p): 9.0 for p in moved[moved.team_id == full].player_id if p not in state.player_ids()
    }
    rec = recommend_transfers(
        _forecast(moved, tempting), state, game_rules, TransferConfig(), CONFIG
    )
    team = moved.set_index("player_id")["team_id"]
    held_full = sum(1 for i in state.player_ids() if int(team[i]) == full)
    assert held_full == game_rules.squad.club_limit + 1
    for option in rec.options:
        bought = set(option.squad_after) - state.player_ids()
        assert not any(int(team[i]) == full for i in bought), "bought into an over-cap club"
        assert sum(1 for i in option.squad_after if int(team[i]) == full) <= held_full


def test_legal_squad_still_capped_on_buys(game_rules: GameRules) -> None:
    players = _players()
    state = _state(game_rules, players)
    rec = recommend_transfers(
        _forecast(players, dict.fromkeys(range(1, 40), 9.0)),
        state,
        game_rules,
        TransferConfig(),
        CONFIG,
    )
    team = players.set_index("player_id")["team_id"]
    for option in rec.options:
        assert (
            max(Counter(int(team[i]) for i in option.squad_after).values())
            <= game_rules.squad.club_limit
        )


def test_pick_captains_is_highest_then_second_within_xi() -> None:
    assert pick_captains((1, 2, 3), {1: 2.0, 2: 5.0, 3: 4.0, 99: 50.0}) == (2, 3)
    assert pick_captains((4, 5), {}) == (4, 5)  # no scores: deterministic by id


def test_price_position_captain_moves_only_the_armband(game_rules: GameRules) -> None:
    players = _players()
    state = _state(game_rules, players)
    fc = _forecast(players)
    rec = recommend_transfers(fc, state, game_rules, TransferConfig(), CONFIG)
    xi = rec.recommended.starting
    scores = {i: float(n) for n, i in enumerate(reversed(xi))}  # first starter scores lowest
    target = max(xi, key=lambda i: scores[i])
    out = apply_price_position_captain(rec, fc, scores, 2)
    assert out.recommended.captain_id == target
    assert out.recommended.vice_captain_id != target and out.recommended.vice_captain_id in xi
    assert out.recommended.starting == xi
    assert out.recommended.squad_after == rec.recommended.squad_after
    assert out.recommended.transfers == rec.recommended.transfers


def test_captain_rule_flag_defaults_on_and_minutes_v2_on_in_production() -> None:
    from fpl_dof.config import load_config
    from fpl_dof.factory.registry import champion

    assert champion().policy.captain_rule == "price_position"
    assert OptimiserConfig().shadow_c1 is True
    cfg, _ = load_config(environ={})
    assert cfg.forecast.discrimination.minutes_v2 is True


def test_shadow_failure_is_logged_not_raised(
    game_rules: GameRules, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    players = _players()
    state = _state(game_rules, players)
    fc = _forecast(players)
    engine = recommend_transfers(fc, state, game_rules, TransferConfig(), CONFIG)

    def boom(**_: object) -> None:
        raise RuntimeError("shadow exploded")

    monkeypatch.setattr(c1, "run_shadow", boom)
    path = c1.run_shadow_safely(
        gold=tmp_path,
        run_id="r",
        gameweek=2,
        engine=engine,
        forecast=fc,
        history=pd.DataFrame(),
        players=players,
        fixtures=pd.DataFrame(),
        state=state,
        rules=game_rules,
        transfer_config=TransferConfig(),
        optimiser_config=CONFIG,
    )
    assert path is not None
    payload = json.loads(path.read_text())
    assert payload["status"] == "failed" and "shadow exploded" in payload["error"]
    assert payload["affects_live_recommendation"] is False
    assert payload["engine"]["captain"] == engine.recommended.captain_id


def test_shadow_real_failure_with_no_history_is_contained(
    game_rules: GameRules, tmp_path: Path
) -> None:
    players = _players()
    state = _state(game_rules, players)
    fc = _forecast(players)
    engine = recommend_transfers(fc, state, game_rules, TransferConfig(), CONFIG)
    before = fc.copy()
    path = c1.run_shadow_safely(
        gold=tmp_path,
        run_id="r",
        gameweek=2,
        engine=engine,
        forecast=fc,
        history=pd.DataFrame(),
        players=players,
        fixtures=pd.DataFrame(),
        state=state,
        rules=game_rules,
        transfer_config=TransferConfig(),
        optimiser_config=CONFIG,
    )
    assert path is not None
    assert json.loads(Path(path).read_text())["status"] == "failed"
    pd.testing.assert_frame_equal(fc, before)  # the live forecast frame is never mutated


def test_shadow_unwritable_gold_returns_none(
    game_rules: GameRules, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    players = _players()
    state = _state(game_rules, players)
    fc = _forecast(players)
    engine = recommend_transfers(fc, state, game_rules, TransferConfig(), CONFIG)
    monkeypatch.setattr(c1, "run_shadow", lambda **_: engine)
    assert (
        c1.run_shadow_safely(
            gold=blocker / "gold",
            run_id="r",
            gameweek=2,
            engine=engine,
            forecast=fc,
            history=pd.DataFrame(),
            players=players,
            fixtures=pd.DataFrame(),
            state=state,
            rules=game_rules,
            transfer_config=TransferConfig(),
            optimiser_config=CONFIG,
        )
        is None
    )
