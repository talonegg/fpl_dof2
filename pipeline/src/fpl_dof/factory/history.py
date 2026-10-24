"""Each strategy's own season over the standing backtest's folds: the models history (ORC-06).

A virtual season per strategy and archive season: a fresh squad at its first graded gameweek, then
every graded gameweek the decision engine's week (transfers and hits, XI, captain) on that
strategy's walk-forward forecast, scored by the one realised-points scorer (ORC-04) on what the
players actually did. No chips, a one-gameweek horizon, free transfers as the rules earn and roll
them. A backtest, not real play: every strategy plays its own squad, so the seasons differ by
forecast and policy alone.

The forecast is the walk's own: each fold's prediction was made from data strictly before that
deadline (Invariant 5), and the captain rule's B0 is fitted on the strategy's training window
before it. Its spread is the strategy's own error over its earlier folds, by position, so it too is
knowable at the deadline (Invariant 6). Pure: frames in, rows out (DP-03). Strategies are
simulated in parallel, one process each (``backtest.strategy_workers``); one whose season cannot be
simulated is recorded with the reason and the others finish (D-32), and one lost to a crashed
worker is simulated again in this process.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any

import pandas as pd

from fpl_dof.config.models import Config, UncertaintyConfig
from fpl_dof.decision import decide
from fpl_dof.factory.registry import Strategy
from fpl_dof.forecast.backtest import deadlines_for, prediction_column, run_isolated
from fpl_dof.forecast.baselines import fit_b0
from fpl_dof.forecast.entry import price_position_line
from fpl_dof.forecast.features import TARGET
from fpl_dof.frames import as_float, as_int
from fpl_dof.optimise.squad import optimise_squad
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import Lineup, performances, score_lineup
from fpl_dof.squad.state import HeldPlayer, Provenance, SquadState, free_transfers_after

#: What every simulated season assumes, published as the history's provenance.
SETTINGS: dict[str, str] = {
    "simulator": (
        "fpl_dof.factory.history: the decision engine's week on each strategy's walk-forward "
        "forecast (ORC-06)"
    ),
    "scorer": "rules/realised.py, the one realised-points scorer (ORC-04)",
    "captain": (
        "each strategy's own captain rule (registry policy.captain_rule); B0 fitted on its "
        "training window before each deadline"
    ),
    "settings": (
        "fresh squad at the first graded gameweek; the game's auto-subs and vice fallback; free "
        "transfers earned and rolled as the rules set, extra transfers charged; no chips; a "
        "one-gameweek horizon; no availability news (the archive carries none)"
    ),
}

_PREDICTION_KEYS = ("season", "gameweek", "player_code", "position", "team_id", "price", TARGET)
_HISTORY_KEYS = (
    *("season", "gameweek", "player_code", "web_name", "position", "price", "minutes"),
    *(TARGET, "kickoff_time"),
)


def season_histories(
    predictions: pd.DataFrame,
    history: pd.DataFrame,
    strategies: Sequence[Strategy],
    rules: GameRules,
    config: Config,
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, str]]:
    """Season -> strategy id -> one row per graded gameweek, and strategy id -> why it has none.

    ``predictions`` is the backtest's (``BacktestResult.predictions``); a strategy without a
    prediction column there was not graded and is not simulated.
    """
    seasons = config.backtest.training_seasons
    played = history[history["season"].isin(seasons)] if seasons else history
    played = played[[c for c in _HISTORY_KEYS if c in played.columns]]
    jobs = [s for s in strategies if prediction_column(s.id) in predictions.columns]
    frames = {
        s.id: predictions[[*_PREDICTION_KEYS, prediction_column(s.id)]].dropna() for s in jobs
    }
    calls = [partial(simulate, frames[s.id], played, s, rules, config) for s in jobs]
    outcomes = run_isolated(calls, config.backtest.strategy_workers)
    results: dict[str, dict[str, list[dict[str, Any]]]] = {}
    failures: dict[str, str] = {}
    for strategy, outcome in zip(jobs, outcomes, strict=True):
        if isinstance(outcome, Exception):
            failures[strategy.id] = (
                f"its season could not be simulated: {type(outcome).__name__}: {outcome}"
            )
        else:
            results[strategy.id] = outcome

    by_season: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for sid, seasons_rows in results.items():
        for season, rows in seasons_rows.items():
            by_season.setdefault(season, {})[sid] = rows
    return by_season, failures


def simulate(
    predictions: pd.DataFrame,
    history: pd.DataFrame,
    strategy: Strategy,
    rules: GameRules,
    config: Config,
) -> dict[str, list[dict[str, Any]]]:
    """One strategy's seasons: season -> one row per graded gameweek, in the history's shape."""
    column = prediction_column(strategy.id)
    deadlines = {(season, gw): deadline for season, gw, deadline in deadlines_for(history)}
    names = history.drop_duplicates("player_code", keep="last").set_index("player_code")["web_name"]
    errors = pd.DataFrame(
        {
            "deadline": [
                deadlines[(str(s), as_int(g))]
                for s, g in zip(predictions["season"], predictions["gameweek"], strict=True)
            ],
            "position": predictions["position"],
            "error": predictions[TARGET] - predictions[column],
        }
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for season, rows in predictions.groupby("season", sort=True):
        played = history[history["season"] == season]
        window = history if strategy.forecaster.training_window == "all_seasons" else played
        out[str(season)] = _season(
            rows, played, window, strategy, rules, config, column, deadlines, names, errors
        )
    return out


def _season(
    rows: pd.DataFrame,
    played: pd.DataFrame,
    window: pd.DataFrame,
    strategy: Strategy,
    rules: GameRules,
    config: Config,
    column: str,
    deadlines: Mapping[tuple[str, int], pd.Timestamp],
    names: pd.Series,
    errors: pd.DataFrame,
) -> list[dict[str, Any]]:
    state: SquadState | None = None
    out: list[dict[str, Any]] = []
    for gameweek, week in rows.groupby("gameweek", sort=True):
        gw = as_int(gameweek)
        season = str(week["season"].iloc[0])
        earlier = errors[errors["deadline"] < deadlines[(season, gw)]]
        spread = earlier.groupby("position")["error"].std()
        frame = _frame(week, column, names, state, spread, config.forecast.uncertainty)
        transfers = config.transfers
        if state is None:
            squad, _ = optimise_squad(frame, rules, config.optimiser)
            bought = tuple(
                HeldPlayer(
                    p.player_id, p.position, p.team_id, p.price, p.price, _name(names, p.player_id)
                )
                for p in squad.players
            )
            spent = sum(p.price for p in squad.players)
            bank = round(rules.squad.budget - spent, 1)
            state = SquadState(None, gw, bought, bank, 0, (), Provenance.DECLARED)
            transfers = transfers.model_copy(update={"max_transfers": 0})  # GW1 of a squad
        else:
            state = dataclasses.replace(state, gameweek=gw, players=repriced(state, frame))

        line = None
        if strategy.policy.captain_rule == "price_position":
            before = window[window["kickoff_time"] < deadlines[(season, gw)]]
            line = price_position_line(fit_b0(before, TARGET)) if not before.empty else None
        policy = dataclasses.replace(
            strategy.decision_policy(config, line), plan=False, transfers=transfers
        )
        decision = decide(frame, state, rules, policy)
        option, selection = decision.recommendation.recommended, decision.selection

        # Every pool player's position, so one with no fixture still counts in the formation check.
        positions = {
            as_int(i): Position(str(q))
            for i, q in zip(frame["player_id"], frame["position"], strict=True)
        }
        perfs = performances(
            played[played["gameweek"] == gw], key="player_code", positions=positions
        )
        scored = score_lineup(
            Lineup(
                starting=selection.starting,
                bench_order=selection.bench_order,
                bench_gkp=selection.reserve_goalkeeper,
                captain=selection.captain,
                vice_captain=selection.vice_captain,
                transfers_made=option.transfers,
                free_transfers=state.free_transfers,
            ),
            perfs,
            rules,
        )
        captain = perfs.get(selection.captain)
        out.append(
            {
                "gw": gw,
                "points": float(scored.net_points),
                "points_before_hits": float(scored.points_before_hits),
                "hit_points": float(-scored.hit_points),
                "n_transfers": option.transfers,
                "transfers": [f"{m.player_out_name} → {m.player_in_name}" for m in option.moves],
                "captain": _name(names, selection.captain),
                "vice_captain": _name(names, selection.vice_captain),
                "captain_points": float(captain.points if captain and captain.minutes else 0),
                "vice_used": scored.vice_used,
                "n_autosubs": len(scored.autosubs_in),
            }
        )
        state = next_state(
            state, option.squad_after, option.bank_after, option.transfers, frame, rules
        )
    return out


def _frame(
    week: pd.DataFrame,
    column: str,
    names: pd.Series,
    state: SquadState | None,
    spread: pd.Series,
    uncertainty: UncertaintyConfig,
) -> pd.DataFrame:
    """The gameweek's forecast frame: one row per player, a double gameweek's fixtures summed.

    A fixture's standard deviation is ``spread``, the strategy's error over its folds before this
    deadline, for the player's position; with none yet (the first folds) it is the forecast's own
    band for a player it knows nothing about (``forecast.uncertainty``, D-09). Never below the
    band's floor; a double gameweek's fixtures add their variances.

    A held player with no row (a blank, or gone from the league) is priced at his last price with
    no expected points and the floor's spread, so the squad can still be decided on.

    shortcut: the spread is per position, not per player, and the one-gameweek week step reads
    none of it; model it per player if the history ever weighs risk.
    """
    floor = uncertainty.floor
    band = (week[column].abs() * uncertainty.coefficient_of_variation["none"]).clip(lower=floor)
    sd = week["position"].map(spread).fillna(band).clip(lower=floor)
    pool = (
        week.assign(variance=sd**2)
        .groupby("player_code", sort=True)
        .agg(
            position=("position", "first"),
            team_id=("team_id", "first"),
            price=("price", "first"),
            xp_next=(column, "sum"),
            variance=("variance", "sum"),
        )
    )
    if state is not None:
        missing = [p for p in state.players if p.player_id not in pool.index]
        extra = pd.DataFrame(
            {
                "position": [p.position.value for p in missing],
                "team_id": [p.team_id for p in missing],
                "price": [p.current_price for p in missing],
                "xp_next": [0.0 for _ in missing],
                "variance": [uncertainty.floor**2 for _ in missing],
            },
            index=pd.Index([p.player_id for p in missing], name="player_code"),
        )
        pool = pd.concat([pool, extra]) if missing else pool
    frame = pool.reset_index().rename(columns={"player_code": "player_id"})
    frame["player_id"] = frame["player_id"].astype(int)
    frame["team_id"] = frame["team_id"].astype(int)
    frame["price"] = frame["price"].astype(float)
    frame["xp_next"] = frame["xp_next"].astype(float)
    frame["xp_horizon"] = frame["xp_next"]
    frame["xp_next_sd"] = frame.pop("variance").astype(float) ** 0.5
    frame["xp_horizon_sd"] = frame["xp_next_sd"]
    # The archive carries no availability news, so the start-probability floor never binds.
    frame["start_probability"] = 1.0
    frame["web_name"] = [_name(names, i) for i in frame["player_id"]]
    return frame


def repriced(state: SquadState, frame: pd.DataFrame) -> tuple[HeldPlayer, ...]:
    """The held players at this gameweek's price and club; what each was bought for is kept."""
    by_id = frame.set_index("player_id")
    return tuple(
        dataclasses.replace(
            p,
            current_price=as_float(by_id.at[p.player_id, "price"]),
            team_id=as_int(by_id.at[p.player_id, "team_id"]),
        )
        for p in state.players
    )


def next_state(
    state: SquadState,
    squad_after: Sequence[int],
    bank_after: float,
    transfers: int,
    frame: pd.DataFrame,
    rules: GameRules,
    *,
    chip: str | None = None,
) -> SquadState:
    """The squad going into the next gameweek: a player bought now is bought at today's price.
    ``chip`` is the one played this gameweek, which a free week's transfers do not draw on."""
    by_id = frame.set_index("player_id")
    held = {p.player_id: p for p in state.players}
    players = tuple(
        held[pid]
        if pid in held
        else HeldPlayer(
            player_id=pid,
            position=Position(str(by_id.at[pid, "position"])),
            team_id=as_int(by_id.at[pid, "team_id"]),
            current_price=as_float(by_id.at[pid, "price"]),
            purchase_price=as_float(by_id.at[pid, "price"]),
            web_name=str(by_id.at[pid, "web_name"]),
        )
        for pid in squad_after
    )
    return dataclasses.replace(
        state,
        players=players,
        bank=bank_after,
        free_transfers=free_transfers_after(
            state.free_transfers, transfers, rules, chip_played=chip
        ),
        chips_used=(*state.chips_used, chip) if chip else state.chips_used,
    )


def _name(names: pd.Series, code: int) -> str:
    found = names.get(code)
    return str(found) if found is not None else f"#{code}"


__all__ = ["SETTINGS", "next_state", "repriced", "season_histories", "simulate"]
