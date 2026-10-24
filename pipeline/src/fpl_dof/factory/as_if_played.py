"""The live season as if each model had played it, in-sample (ORC-13, DL-97).

Each strategy is fitted once, on everything knowable now, by its own live forecast
(:meth:`~fpl_dof.factory.registry.Strategy.forecast`). Those weights then replay every finished
gameweek from GW1 on the strategy's own squad: a from-scratch squad under the budget at the first
gameweek it plays (the squad MILP the preseason solve uses), then the decision engine at every
deadline — the week's transfers and hits, or the plan's week when the plan plays a chip in it —
scored by the one realised-points scorer (ORC-04) on what the players actually did.

**In-sample.** Only the weights are later than the gameweek they play: everything the forecast reads
is cut to the deadline by :func:`inputs_at` (Invariant 5). It flatters every model, most of all one
that fits this season's noise, so it is labelled in-sample wherever it is shown and nothing in the
champion's selection or a promotion reads it (DL-97).

A strategy that cannot forecast at a deadline (its inputs absent then) is unavailable that
gameweek, with the reason, and its squad carries over untouched. One whose forecast today has no
fitted weights (the cold-start fallback) is unavailable for the season. Strategies are replayed in
parallel, one process each (``backtest.strategy_workers``). Pure: frames in, rows out (DP-03).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from functools import partial
from typing import Any

import pandas as pd

from fpl_dof.config.models import Config, OptimiserConfig
from fpl_dof.decision import decide
from fpl_dof.factory.history import next_state, repriced
from fpl_dof.factory.registry import Strategy
from fpl_dof.forecast.backtest import run_isolated
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.frames import as_int
from fpl_dof.optimise.horizon import PlannedWeek
from fpl_dof.optimise.squad import InfeasibleError, optimise_squad
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import Lineup, PlayerPerformance, performances, score_lineup
from fpl_dof.squad.state import HeldPlayer, Provenance, SquadState

#: The replay's provenance, published with it.
SETTINGS: dict[str, str] = {
    "simulator": (
        "fpl_dof.factory.as_if_played: each strategy's live forecast, fitted once on everything "
        "knowable now, replayed at every finished deadline (ORC-13, DL-97)"
    ),
    "scorer": "rules/realised.py, the one realised-points scorer (ORC-04)",
    "settings": (
        "in-sample: today's weights; a from-scratch squad under the budget at the first gameweek "
        "played, the start-probability floor relaxed if it cannot be met; the decision engine's "
        "week, or the plan's when it plays a chip; features, prices and fixtures as known at each "
        "deadline; no availability news, which is not recorded per deadline"
    ),
}

Row = dict[str, Any]


def inputs_at(
    inputs: ForecastInputs, season: str, gameweek: int, prices: pd.DataFrame | None
) -> ForecastInputs:
    """What was knowable just before ``gameweek``'s deadline in ``season`` (Invariant 5).

    Played rows that kicked off before the deadline; each player's price the last ``prices``
    (``price_history``) observation at or before it, else the price FPL recorded for him that
    gameweek, else he is left out (not yet registered); his club that gameweek; every fixture
    and gameweek from this one on unfinished; odds captured before it.

    shortcut: no availability news is used, since status is not recorded per deadline (less than
    was known, never more); and a fixture moved after the deadline is seen at its new gameweek.
    Record status in price_history if the replay should weigh news.
    """
    gameweeks = inputs.gameweeks
    deadline = pd.Timestamp(
        gameweeks.loc[gameweeks["gameweek"] == gameweek, "deadline_time"].iloc[0]
    ).tz_convert("UTC")
    history = inputs.player_gameweek
    before = history[history["kickoff_time"] < deadline] if history is not None else None
    fixtures = inputs.fixtures.assign(finished=inputs.fixtures["gameweek"] < gameweek)
    marked = gameweeks.assign(finished=gameweeks["gameweek"] < gameweek)
    if "is_next" in marked.columns:
        marked = marked.assign(is_next=marked["gameweek"] == gameweek)
    odds = inputs.match_odds
    if odds is not None:
        odds = odds[odds["captured_at"] < deadline]
    return dataclasses.replace(
        inputs,
        players=_players_at(inputs.players, history, prices, season, gameweek, deadline),
        fixtures=fixtures,
        gameweeks=marked,
        player_gameweek=before,
        match_odds=odds,
        as_of=(deadline - pd.Timedelta(seconds=1)).to_pydatetime(),
    )


def _players_at(
    players: pd.DataFrame,
    history: pd.DataFrame | None,
    prices: pd.DataFrame | None,
    season: str,
    gameweek: int,
    deadline: pd.Timestamp,
) -> pd.DataFrame:
    # Today's ownership is no more knowable then than today's news: the observation's, else none.
    frame = players.assign(
        status="a", chance_of_playing_next_round=None, news="", selected_by_percent=0.0
    )
    if history is not None and not history.empty:
        # Club and recorded price for the gameweek, read from its row: known before its kickoff.
        rows = history[(history["season"] == season) & (history["gameweek"] <= gameweek)]
        then = rows.sort_values("gameweek").drop_duplicates("player_id", keep="last")
        then = then.set_index("player_id")
        club = frame["player_id"].map(then["team_id"])
        frame["team_id"] = club.where(club.notna(), frame["team_id"]).astype(
            players["team_id"].dtype
        )
        recorded = frame["player_id"].map(then["price"])
    else:
        recorded = pd.Series(float("nan"), index=frame.index)
    observed = pd.Series(dtype=float)
    if prices is not None and not prices.empty:
        seen = prices[prices["observed_at"] <= deadline].sort_values("observed_at")
        last = seen.drop_duplicates("player_id", keep="last").set_index("player_id")
        observed = last["price"]
        owned = frame["player_id"].map(last["selected_by_percent"])
        frame["selected_by_percent"] = owned.where(owned.notna(), 0.0)
    price = frame["player_id"].map(observed)
    frame["price"] = price.where(price.notna(), recorded)
    return frame[frame["price"].notna()].reset_index(drop=True)


def replay(
    strategy: Strategy,
    inputs: ForecastInputs,
    rules: GameRules,
    config: Config,
    *,
    finished: Collection[int],
    prices: pd.DataFrame | None = None,
    chips: pd.DataFrame | None = None,
) -> tuple[list[Row], dict[int, str]]:
    """One strategy's season: one row per gameweek played, and gameweek -> why it could not be."""
    today = strategy.forecast(inputs, rules, config)
    if today.fitted is None:
        raise ValueError(
            f"today's forecast is {today.model}, a cold-start fallback with no fitted weights"
        )
    last = as_int(inputs.gameweeks["gameweek"].max())
    history = inputs.player_gameweek
    season_rows = (
        history[history["season"] == rules.season] if history is not None else pd.DataFrame()
    )
    state: SquadState | None = None
    rows: list[Row] = []
    skipped: dict[int, str] = {}
    for gw in sorted(finished):
        try:
            at = inputs_at(inputs, rules.season, gw, prices)
            forecast = strategy.forecast(at, rules, config, fitted=today.fitted)
            row, state = _play(
                strategy, forecast.frame, forecast.captain_line, state, at, rules, config,
                gw=gw, chips=chips, last=last, season_rows=season_rows,
            )  # fmt: skip
        except Exception as exc:
            skipped[gw] = f"{type(exc).__name__}: {exc}"
            continue
        rows.append(row)
    return rows, skipped


def _play(
    strategy: Strategy,
    frame: pd.DataFrame,
    captain_line: Any,
    state: SquadState | None,
    at: ForecastInputs,
    rules: GameRules,
    config: Config,
    *,
    gw: int,
    chips: pd.DataFrame | None,
    last: int,
    season_rows: pd.DataFrame,
) -> tuple[Row, SquadState]:
    """One gameweek decided and scored, and the squad going into the next."""
    transfers, optimiser = config.transfers, config.optimiser
    if state is None:
        state, optimiser = _first_squad(frame, rules, optimiser, gw)
        transfers = transfers.model_copy(update={"max_transfers": 0})  # GW1 of a squad
    else:
        state = dataclasses.replace(state, gameweek=gw, players=repriced(state, frame))
    policy = dataclasses.replace(
        strategy.decision_policy(config, captain_line), transfers=transfers, optimiser=optimiser
    )
    decision = decide(
        frame, state, rules, policy, fixtures=at.fixtures, chips=chips, last_gameweek=last
    )
    names = dict(zip(frame["player_id"].map(as_int), frame["web_name"].astype(str), strict=True))
    positions = {
        as_int(i): Position(str(q))
        for i, q in zip(frame["player_id"], frame["position"], strict=True)
    }
    played = season_rows[season_rows["gameweek"] == gw] if not season_rows.empty else season_rows
    perfs = performances(played, key="player_id", positions=positions)
    week = _chip_week(decision.plan, gw)
    if week is None:
        option, selection = decision.recommendation.recommended, decision.selection
        lineup = Lineup(
            starting=selection.starting,
            bench_order=selection.bench_order,
            bench_gkp=selection.reserve_goalkeeper,
            captain=selection.captain,
            vice_captain=selection.vice_captain,
            transfers_made=option.transfers,
            free_transfers=state.free_transfers,
        )
        moves = [f"{m.player_out_name} → {m.player_in_name}" for m in option.moves]
        after = next_state(
            state, option.squad_after, option.bank_after, option.transfers, frame, rules
        )
    else:
        bench = set(week.bench_order)
        lineup = Lineup(
            starting=week.starting,
            bench_order=week.bench_order,
            bench_gkp=next(
                (i for i in week.fielded if i not in week.starting and i not in bench), None
            ),
            captain=week.captain_id,
            vice_captain=week.vice_captain_id,
            chip=week.chip,
            transfers_made=len(week.transfers_in),
            free_transfers=state.free_transfers,
        )
        moves = [
            f"{names.get(o, f'#{o}')} → {names.get(i, f'#{i}')}"
            for o, i in zip(week.transfers_out, week.transfers_in, strict=False)
        ]
        # The persistent squad: under a Free Hit what is kept, not what was fielded.
        after = next_state(
            state, week.squad, week.bank_after, len(week.transfers_in), frame, rules,
            chip=week.chip,
        )  # fmt: skip
    return _row(gw, lineup, perfs, names, moves, rules), after


def _chip_week(plan: Any, gw: int) -> PlannedWeek | None:
    """The plan's week when it plays a chip this gameweek: the advice then follows the plan."""
    weeks = plan.recommended.plan.weeks if plan is not None else ()
    week: PlannedWeek | None = weeks[0] if weeks else None
    return week if week is not None and week.gameweek == gw and week.chip else None


def _first_squad(
    frame: pd.DataFrame, rules: GameRules, optimiser: OptimiserConfig, gw: int
) -> tuple[SquadState, OptimiserConfig]:
    """A from-scratch squad under the budget: the squad MILP the preseason solve uses, and the
    optimiser config it was solved under.

    A season's first deadline has no played gameweek, so a model's start probabilities can sit
    below the floor for every player; the floor is then relaxed for that gameweek, as the decision
    engine relaxes it for an XI that cannot meet it (DP-15), rather than the model sitting it out.
    """
    try:
        squad, _ = optimise_squad(frame, rules, optimiser)
    except InfeasibleError:
        optimiser = optimiser.model_copy(update={"enforce_start_probability_floor": False})
        squad, _ = optimise_squad(frame, rules, optimiser)
    names = dict(zip(frame["player_id"].map(as_int), frame["web_name"].astype(str), strict=True))
    bought = tuple(
        HeldPlayer(p.player_id, p.position, p.team_id, p.price, p.price, names.get(p.player_id, ""))
        for p in squad.players
    )
    bank = round(rules.squad.budget - sum(p.price for p in squad.players), 1)
    return SquadState(None, gw, bought, bank, 0, (), Provenance.DECLARED), optimiser


def _row(
    gw: int,
    lineup: Lineup,
    perfs: Mapping[int, PlayerPerformance],
    names: Mapping[int, str],
    moves: Sequence[str],
    rules: GameRules,
) -> Row:
    scored = score_lineup(lineup, perfs, rules)
    captain = perfs.get(lineup.captain)
    return {
        "gw": gw,
        "points": float(scored.net_points),
        "points_before_hits": float(scored.points_before_hits),
        "hit_points": float(-scored.hit_points),
        "n_transfers": lineup.transfers_made,
        "transfers": list(moves),
        "captain": names.get(lineup.captain, f"#{lineup.captain}"),
        "vice_captain": names.get(lineup.vice_captain, f"#{lineup.vice_captain}"),
        "captain_points": float(captain.points if captain and captain.minutes else 0),
        "vice_used": scored.vice_used,
        "n_autosubs": len(scored.autosubs_in),
        "chip": lineup.chip,
    }


def as_if_played(
    inputs: ForecastInputs,
    strategies: Sequence[Strategy],
    rules: GameRules,
    config: Config,
    *,
    finished: Collection[int],
    prices: pd.DataFrame | None = None,
    chips: pd.DataFrame | None = None,
) -> tuple[dict[str, list[Row]], dict[str, str], dict[str, dict[int, str]]]:
    """Every strategy's season: strategy id -> its rows, strategy id -> why it has none, and
    strategy id -> gameweek -> why it could not play that gameweek."""
    calls = [
        partial(replay, s, inputs, rules, config, finished=finished, prices=prices, chips=chips)
        for s in strategies
    ]
    rows: dict[str, list[Row]] = {}
    unavailable: dict[str, str] = {}
    skipped: dict[str, dict[int, str]] = {}
    for strategy, outcome in zip(
        strategies, run_isolated(calls, config.backtest.strategy_workers), strict=True
    ):
        if isinstance(outcome, Exception):
            unavailable[strategy.id] = (
                f"today's fit could not be replayed: {type(outcome).__name__}: {outcome}"
            )
            continue
        played, missed = outcome
        rows[strategy.id] = played
        if missed:
            skipped[strategy.id] = missed
    return rows, unavailable, skipped


__all__ = ["SETTINGS", "as_if_played", "inputs_at", "replay"]
