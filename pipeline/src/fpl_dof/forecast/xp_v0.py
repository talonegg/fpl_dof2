"""Expected points, version 0 — the cold-start model.

Preseason has **no current-season data at all**, so this is entirely a prior-construction problem.
There is nothing to fit. The whole model is: take what a player did last season, decide how much of
it to believe, adjust for who they are playing and whether they will play, and convert to points
using the rules module.

Signal stack, in descending weight:

1. Prior-season per-90 rates — goals, assists, clean sheets, saves, cards, bonus.
2. Per-90 Defensive Contribution, from 2025/26 only. Rate-driven and far more stable week to week
   than goal involvement, so it earns high weight despite one season of evidence.
3. FPL's own price, as a market-implied prior on role and expected value, via the group prior that
   thin samples shrink toward.
4. Position-and-price-tier baselines for players with no top-flight history.
5. An availability haircut from ``status``.
6. Fixture difficulty over the horizon.

**Where this is weakest, stated plainly.** There is no minutes model (debt D-02) and no start model
(D-12): start probability is last season's start rate shrunk toward a price-tier prior. In preseason
the FPL status flags say almost nothing — nearly every player is ``a`` — so that prior is the only
thing standing between the optimiser and a bench full of players who will never play.

**Two absence-of-measurement traps**, both live in this data and both handled explicitly:
Defensive Contribution reads zero for every season before 2025/26, and ``starts`` reads zero before
2022/23. Neither means the player did nothing. Treating them as evidence would systematically
underrate exactly the defenders and defensive midfielders the design says this model should beat
intuition on.

See :mod:`fpl_dof.forecast.diagnostics` for the R-15 check that decides whether any of this is
adding information beyond price.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.frames import as_int, gameweek_column, gameweek_sd_column
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules, Position

log = get_logger(__name__)

#: Rates modelled per 90 minutes. Each maps a silver column to the component it feeds.
RATE_COLUMNS = (
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "yellow_cards",
    "bonus",
)

CONFIDENCE_ORDER = ("high", "medium", "low", "none")

#: What this model calls itself wherever a published artefact has to say which model ran.
MODEL_NAME = "xp_v0"


def poisson_survival(threshold: int, mean: float) -> float:
    """``P(X >= threshold)`` for ``X ~ Poisson(mean)``.

    Used for Defensive Contribution, which is a threshold event: a defender scores the award for
    reaching 10 defensive actions in a match, and nothing extra for reaching 20. Modelling the
    per-match count as Poisson around the player's per-90 rate is the simplest assumption that
    gets the threshold behaviour right, and it is one you can argue with (DP-10) — a real count
    distribution is over-dispersed, so this slightly understates both tails.
    """
    if threshold <= 0:
        return 1.0
    if mean <= 0:
        return 0.0
    cumulative = 0.0
    term = math.exp(-mean)
    for k in range(threshold):
        if k > 0:
            term *= mean / k
        cumulative += term
    return max(0.0, min(1.0, 1.0 - cumulative))


def _season_sort_key(season: str) -> int:
    """``"2025/26"`` -> 2025. Sorts seasons without parsing them as dates."""
    try:
        return int(season.split("/")[0])
    except ValueError, IndexError:
        return -1


def summarise_history(history: pd.DataFrame, config: ForecastConfig) -> pd.DataFrame:
    """Collapse a player's prior seasons into one recency-weighted evidence row.

    Recent seasons count for more, and every season is weighted by the minutes behind it, so a
    player with one full season and one cameo is not treated as having two seasons of evidence.
    """
    if history.empty:
        return pd.DataFrame(columns=["player_id"])

    frame = history.copy()
    frame["season_start"] = frame["season_name"].map(_season_sort_key)
    latest = as_int(frame["season_start"].max())
    age = latest - frame["season_start"]
    frame = frame[age < config.max_history_seasons].copy()
    age = latest - frame["season_start"]
    frame["recency"] = config.season_recency_decay**age
    frame["weight"] = frame["minutes"] * frame["recency"]

    rows: list[dict[str, float]] = []
    defcon_seasons = set(config.defensive_contribution_seasons)
    starts_from = _season_sort_key(config.starts_recorded_from_season)

    for player_id, group in frame.groupby("player_id", sort=True):
        weight = float(group["weight"].sum())
        record: dict[str, float] = {
            "player_id": as_int(player_id),
            "evidence_minutes": float((group["minutes"] * group["recency"]).sum()),
            "raw_minutes": float(group["minutes"].sum()),
        }
        for column in RATE_COLUMNS:
            total = float((group[column] * group["recency"]).sum())
            record[f"{column}_per90"] = total / (weight / 90.0) if weight > 0 else 0.0

        # Defensive Contribution: only seasons in which it was actually recorded.
        defcon = group[group["season_name"].isin(defcon_seasons)]
        defcon_minutes = float(defcon["minutes"].sum())
        record["defcon_minutes"] = defcon_minutes
        record["defensive_contribution_per90"] = (
            float(defcon["defensive_contribution"].sum()) / (defcon_minutes / 90.0)
            if defcon_minutes > 0
            else float("nan")
        )

        # Starts: only seasons in which they were recorded.
        startable = group[group["season_start"] >= starts_from]
        games = float(len(startable)) * config.minutes.team_games_per_season
        record["start_games"] = games
        record["start_rate"] = (
            float((startable["starts"] * startable["recency"]).sum())
            / float((startable["recency"] * config.minutes.team_games_per_season).sum())
            if len(startable) > 0
            else float("nan")
        )
        rows.append(record)

    return pd.DataFrame(rows)


def _price_tier(players: pd.DataFrame, tiers: int) -> pd.Series:
    """Quantile buckets within position. FPL prices on expected returns, so this is a real prior."""

    def bucket(group: pd.Series) -> pd.Series:
        if group.nunique() < 2:
            return pd.Series(0, index=group.index)
        return pd.qcut(group.rank(method="first"), tiers, labels=False, duplicates="drop")

    return players.groupby("position", observed=True)["price"].transform(bucket).fillna(0)


def _shrink(
    own: pd.Series, evidence: pd.Series, prior: pd.Series, prior_weight: float
) -> pd.Series:
    """Pull a player's own rate toward its group prior, in inverse proportion to evidence.

    With zero evidence — a new signing, a promoted-club player — the result is exactly the prior,
    which is the behaviour the cold start needs.
    """
    own = pd.to_numeric(own, errors="coerce").fillna(prior).astype(float)
    evidence = pd.to_numeric(evidence, errors="coerce").fillna(0.0).astype(float)
    return ((own * evidence + prior * prior_weight) / (evidence + prior_weight)).astype(float)


def _weighted_mean_by(frame: pd.DataFrame, key: str) -> pd.Series:
    """Weighted mean of ``value`` by ``weight``, per ``key``. NaN where a group has no weight."""
    products = (frame["value"] * frame["weight"]).groupby(frame[key], observed=True).sum()
    weights = frame["weight"].groupby(frame[key], observed=True).sum()
    return (products / weights).where(weights > 0)


def _group_prior(
    values: pd.Series, weights: pd.Series, groups: pd.Series, fallback: pd.Series
) -> pd.Series:
    """Minutes-weighted mean within each position/price-tier group, with a fallback ladder.

    A price tier can legitimately contain nobody with any history — the only player at that price
    in that position might be a new signing. Without a fallback their prior is zero, and zero is
    not "we know nothing about them", it is "we are certain they are worthless". It would make
    them unselectable for no reason at all.

    So the ladder is: price tier, then position, then the whole population (DP-15).
    """
    frame = pd.DataFrame(
        {
            "value": pd.to_numeric(values, errors="coerce").fillna(0.0).to_numpy(),
            "weight": pd.to_numeric(weights, errors="coerce").fillna(0.0).to_numpy(),
            "group": groups.to_numpy(),
            "fallback": fallback.to_numpy(),
        },
        index=values.index,
    )

    by_group = _weighted_mean_by(frame, "group")
    by_fallback = _weighted_mean_by(frame, "fallback")
    total_weight = float(frame["weight"].sum())
    overall = (
        float((frame["value"] * frame["weight"]).sum() / total_weight) if total_weight > 0 else 0.0
    )

    prior = frame["group"].map(by_group)
    prior = prior.fillna(frame["fallback"].map(by_fallback))
    return prior.fillna(overall).astype(float)


def fixture_multipliers(
    inputs: ForecastInputs, config: ForecastConfig, gameweeks: list[int]
) -> pd.DataFrame:
    """Per-team attack and defence multipliers, discounted across the horizon.

    A team with two fixtures in a gameweek gets both; a team with none gets zero for it, which is
    how a blank gameweek correctly costs a player their expected points.
    """
    fixtures = inputs.fixtures[inputs.fixtures["gameweek"].isin(gameweeks)]
    rows: list[dict[str, float]] = []
    for _, fixture in fixtures.iterrows():
        gameweek = as_int(fixture["gameweek"])
        discount = config.horizon_discount ** (gameweek - gameweeks[0])
        for side, opponent_side in (("home", "away"), ("away", "home")):
            difficulty = int(fixture[f"{side}_difficulty"])
            rows.append(
                {
                    "team_id": int(fixture[f"{side}_team_id"]),
                    "gameweek": gameweek,
                    "discount": discount,
                    "attack": config.fixture_difficulty.attack.get(difficulty, 1.0),
                    "defence": config.fixture_difficulty.defence.get(difficulty, 1.0),
                    "opponent_id": int(fixture[f"{opponent_side}_team_id"]),
                    "difficulty": difficulty,
                }
            )
    return pd.DataFrame(rows)


def confidence_tier(minutes: pd.Series, config: ForecastConfig) -> pd.Series:
    """Weighted minutes of evidence -> one of four tiers.

    Public because ``xp_v1`` reports the same four tiers over its own evidence base, and two
    definitions of "how much do we know about this player" would be two different scales printed
    under one set of names.
    """
    return pd.Series(
        np.select(
            [
                minutes >= config.confidence_minutes_high,
                minutes >= config.confidence_minutes_medium,
                minutes > 0,
            ],
            ["high", "medium", "low"],
            default="none",
        ),
        index=minutes.index,
    )


def build_forecast(
    inputs: ForecastInputs, rules: GameRules, config: ForecastConfig
) -> pd.DataFrame:
    """Produce the expected-points table.

    Returns one row per player with a per-gameweek expectation, a horizon total, a component
    decomposition, an uncertainty band and a confidence tier (Invariant 6, DP-09).
    """
    players = inputs.players.copy()
    evidence = summarise_history(inputs.history, config)
    frame = players.merge(evidence, on="player_id", how="left")

    frame["price_tier"] = _price_tier(frame, config.price_tiers)
    frame["group"] = (
        frame["position"].astype(str) + "|" + frame["price_tier"].astype(int).astype(str)
    )
    frame["evidence_minutes"] = frame["evidence_minutes"].fillna(0.0)

    # --- rates, shrunk toward the position-and-price-tier prior ---
    prior_weight = config.shrinkage.rate_prior_minutes
    for column in RATE_COLUMNS:
        rate = f"{column}_per90"
        prior = _group_prior(
            frame[rate], frame["evidence_minutes"], frame["group"], frame["position"]
        )
        frame[rate] = _shrink(frame[rate], frame["evidence_minutes"], prior, prior_weight)

    defcon_prior = _group_prior(
        frame["defensive_contribution_per90"],
        frame["defcon_minutes"].fillna(0.0),
        frame["group"],
        frame["position"],
    )
    frame["defensive_contribution_per90"] = _shrink(
        frame["defensive_contribution_per90"],
        frame["defcon_minutes"].fillna(0.0),
        defcon_prior,
        prior_weight,
    )

    # --- start probability ---
    start_prior = _group_prior(
        frame["start_rate"], frame["evidence_minutes"], frame["group"], frame["position"]
    )
    games_of_evidence = frame["evidence_minutes"] / config.minutes.full_match
    frame["start_probability_raw"] = _shrink(
        frame["start_rate"], games_of_evidence, start_prior, config.shrinkage.start_prior_games
    ).clip(0.0, 1.0)

    availability = pd.to_numeric(
        frame["status"].map(config.status_multiplier), errors="coerce"
    ).fillna(0.0)
    # A stated chance of playing overrides the flag when FPL gives one. Coerced explicitly: an
    # all-null column arrives as object dtype, and object arithmetic silently poisons everything
    # downstream of it.
    stated = pd.to_numeric(frame["chance_of_playing_next_round"], errors="coerce") / 100.0
    availability = stated.where(stated.notna(), availability).astype(float)
    frame["availability"] = availability.clip(0.0, 1.0)
    frame["start_probability"] = (frame["start_probability_raw"] * frame["availability"]).clip(0, 1)

    frame["confidence"] = confidence_tier(frame["evidence_minutes"], config)

    # --- horizon ---
    upcoming = inputs.gameweeks[~inputs.gameweeks["finished"]].sort_values("gameweek")
    next_gw = as_int(upcoming.iloc[0]["gameweek"])
    horizon = [
        gw
        for gw in range(next_gw, next_gw + config.horizon_gameweeks)
        if gw <= as_int(inputs.gameweeks["gameweek"].max())
    ]
    multipliers = fixture_multipliers(inputs, config, horizon)

    per_gameweek = _score_gameweeks(frame, multipliers, rules, config, horizon, next_gw)
    result = frame.merge(per_gameweek, on="player_id", how="left")

    for column in ("xp_next", "xp_horizon"):
        result[column] = result[column].fillna(0.0)

    cv = result["confidence"].map(config.uncertainty.coefficient_of_variation).astype(float)
    result["xp_next_sd"] = np.maximum(result["xp_next"].abs() * cv, config.uncertainty.floor)
    result["xp_horizon_sd"] = np.maximum(
        result["xp_horizon"].abs() * cv, config.uncertainty.floor * math.sqrt(len(horizon))
    )
    # Per-gameweek uncertainty travels with the per-gameweek mean, because the optimiser contract
    # carries variance from day one even where the solver only approximates its use (Invariant 6).
    for gameweek in horizon:
        column = gameweek_column(gameweek)
        if column not in result.columns:
            continue
        result[column] = result[column].fillna(0.0)
        result[gameweek_sd_column(gameweek)] = np.maximum(
            result[column].abs() * cv, config.uncertainty.floor
        )
    result["next_gameweek"] = next_gw
    result["horizon_gameweeks"] = len(horizon)

    log.info(
        "forecast.built",
        extra={
            "players": len(result),
            "next_gameweek": next_gw,
            "horizon": len(horizon),
            "mean_xp_next": round(float(result["xp_next"].mean()), 3),
        },
    )
    return result


def _score_gameweeks(
    frame: pd.DataFrame,
    multipliers: pd.DataFrame,
    rules: GameRules,
    config: ForecastConfig,
    horizon: list[int],
    next_gameweek: int,
) -> pd.DataFrame:
    """Convert rates into points, one fixture at a time, using the rules module."""
    scoring = rules.scoring
    minutes = config.minutes

    p_start = frame["start_probability"].to_numpy()
    p_appear_short = (
        (1.0 - p_start) * minutes.appearance_rate_if_not_starting * frame["availability"].to_numpy()
    )
    expected_minutes = (
        p_start * minutes.starter_minutes + p_appear_short * minutes.substitute_minutes
    )
    minute_share = expected_minutes / minutes.full_match

    positions = frame["position"].to_numpy()
    goal_value = np.array([scoring.goals_scored[Position(p)] for p in positions], dtype=float)
    cs_value = np.array([scoring.clean_sheets[Position(p)] for p in positions], dtype=float)
    gc_value = np.array([scoring.goals_conceded[Position(p)] for p in positions], dtype=float)
    defcon_value = np.array(
        [scoring.defensive_contribution[Position(p)] for p in positions], dtype=float
    )
    defcon_threshold = np.array(
        [scoring.defensive_contribution_threshold[Position(p)] for p in positions], dtype=int
    )

    by_team: dict[int, pd.DataFrame] = {
        as_int(team): group for team, group in multipliers.groupby("team_id")
    }

    components = {
        key: np.zeros(len(frame))
        for key in (
            "appearance",
            "goals",
            "assists",
            "clean_sheet",
            "goals_conceded",
            "saves",
            "defensive_contribution",
            "bonus",
            "cards",
        )
    }
    xp_next = np.zeros(len(frame))
    xp_horizon = np.zeros(len(frame))
    per_gameweek: dict[str, np.ndarray] = {}
    team_ids = frame["team_id"].to_numpy()

    for gameweek in horizon:
        attack = np.zeros(len(frame))
        defence = np.zeros(len(frame))
        discount = np.zeros(len(frame))
        for index, team_id in enumerate(team_ids):
            fixtures = by_team.get(int(team_id))
            if fixtures is None:
                continue
            this_week = fixtures[fixtures["gameweek"] == gameweek]
            if this_week.empty:
                continue  # a blank gameweek: no fixture, no points
            attack[index] = float(this_week["attack"].sum())
            defence[index] = float(this_week["defence"].sum())
            discount[index] = float(this_week["discount"].mean())

        played = attack > 0
        weight = np.where(played, discount, 0.0)

        appearance = p_start * scoring.long_play + p_appear_short * scoring.short_play
        goals = frame["goals_scored_per90"].to_numpy() * minute_share * attack
        assists = frame["assists_per90"].to_numpy() * minute_share * attack
        clean_sheet = np.clip(frame["clean_sheets_per90"].to_numpy() * defence, 0.0, 1.0) * p_start
        conceded = (
            frame["goals_conceded_per90"].to_numpy()
            * minute_share
            * np.where(defence > 0, 2.0 - defence, 0.0)
        )
        saves = frame["saves_per90"].to_numpy() * minute_share * np.where(played, 1.0, 0.0)
        bonus = frame["bonus_per90"].to_numpy() * minute_share * np.where(played, 1.0, 0.0)
        yellows = frame["yellow_cards_per90"].to_numpy() * minute_share * np.where(played, 1.0, 0.0)

        defcon_rate = frame["defensive_contribution_per90"].to_numpy() * minute_share
        defcon_probability = np.array(
            [
                poisson_survival(int(threshold), float(rate))
                for threshold, rate in zip(defcon_threshold, defcon_rate, strict=True)
            ]
        )

        contribution = {
            "appearance": appearance * np.where(played, 1.0, 0.0),
            "goals": goals * goal_value,
            "assists": assists * scoring.assists,
            "clean_sheet": clean_sheet * cs_value,
            "goals_conceded": (conceded / scoring.goals_conceded_per_point) * gc_value,
            "saves": (saves / scoring.saves_per_point) * scoring.saves,
            "defensive_contribution": defcon_probability
            * defcon_value
            * np.where(played, 1.0, 0.0),
            "bonus": bonus * scoring.bonus,
            "cards": yellows * scoring.yellow_cards,
        }
        total = sum(contribution.values())

        if gameweek == next_gameweek:
            xp_next = total.copy()
            for key, value in contribution.items():
                components[key] = value.copy()
        xp_horizon += total * weight
        # Kept per gameweek as well as summed. The multi-gameweek optimiser (E4-S2) needs μ[p,w],
        # and the alternative — reconstructing a per-week number in the decision layer — would put
        # a second copy of the forecast inside the solver, which is exactly what DP-02 forbids.
        per_gameweek[gameweek_column(gameweek)] = total.copy()

    output = pd.DataFrame({"player_id": frame["player_id"].to_numpy()})
    output["xp_next"] = xp_next
    output["xp_horizon"] = xp_horizon
    for column, values in per_gameweek.items():
        output[column] = values
    output["expected_minutes"] = expected_minutes
    for key, value in components.items():
        output[f"component_{key}"] = value
    return output
