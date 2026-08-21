"""The published forecast: ``xp_v1`` assembled into the frame the rest of the pipeline reads.

`DL-46 <../../../docs/planning/00-decision-log.md>`_ settled what E9-S1 delivers: ``xp_v1`` is the
model the live pipeline publishes, because the defect D-25 records is that the shipped model was not
the graded one — a delivery bug, not an unproven candidate needing a shadow window.

What this module adds over :mod:`fpl_dof.forecast.xp_v1` is **assembly, not modelling**. Not one
number here is computed differently from the way the backtest computes it; the components are fitted
through the same :func:`~fpl_dof.forecast.backtest.fold_rows` the harness uses, scored through the
same :func:`~fpl_dof.forecast.xp_v1.score_player`, and spread over the horizon by the same
:mod:`~fpl_dof.forecast.horizon` scorer the chip replay uses. What is added is everything that is
about *publishing*: player identity, availability news, a confidence tier, and the exact column set
``xp_v0`` has always produced, so every downstream consumer keeps working unchanged.

**Two deliberate seams to the cold start.**

* A player with no minutes this season still gets a row. His features are empty rather than absent,
  so each rate model returns its position prior — the same "group prior, not a zero" rule ``xp_v0``
  applies to a new signing (DP-15). Dropping him instead would make him silently unselectable.
* If the season is too young for the component chain to be fitted at all, this raises
  :class:`ColdStartError` and the stage falls back to ``xp_v0``, visibly.
"""

from __future__ import annotations

import pandas as pd

from fpl_dof.config.models import ForecastConfig
from fpl_dof.forecast.backtest import deadlines_for, fold_rows, training_rows
from fpl_dof.forecast.features import build_features
from fpl_dof.forecast.horizon import fixture_index_from_fixtures, horizon_frame
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.models import fit_components
from fpl_dof.forecast.xp_v0 import confidence_tier
from fpl_dof.forecast.xp_v1 import MODEL_NAME, team_matches
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.rules.models import GameRules

log = get_logger(__name__)

#: Columns copied from the published player record onto every forecast row.
IDENTITY_COLUMNS = (
    "player_id",
    "web_name",
    "full_name",
    "position",
    "team_id",
    "price",
    "status",
    "news",
    "selected_by_percent",
    "chance_of_playing_next_round",
)


class ColdStartError(RuntimeError):
    """Too little current-season history for the component chain to be fitted.

    Not a failure: the season genuinely has not happened yet. The caller falls back to ``xp_v0``
    and says so — degrade, never break, and never silently (DP-15, DL-46).
    """


def completed_gameweeks(player_gameweek: pd.DataFrame | None, *, before: pd.Timestamp) -> int:
    """How many gameweeks have actually been played before ``before``.

    Counted on kickoffs rather than on a ``finished`` flag, because the kickoff is the same
    knowability boundary every feature is stamped against (Invariant 5).
    """
    if player_gameweek is None or player_gameweek.empty:
        return 0
    played = player_gameweek.dropna(subset=["kickoff_time"])
    played = played[played["kickoff_time"] < pd.Timestamp(before).tz_convert("UTC")]
    if played.empty:
        return 0
    return int(played["gameweek"].nunique())


def next_deadline(
    gameweeks: pd.DataFrame, config: ForecastConfig
) -> tuple[int, pd.Timestamp, list[int]]:
    """The gameweek being decided, its deadline, and the horizon that follows it."""
    upcoming = gameweeks[~gameweeks["finished"]].sort_values("gameweek")
    if upcoming.empty:
        raise ColdStartError("every gameweek is finished; there is nothing to forecast")
    first = upcoming.iloc[0]
    next_gameweek = as_int(first["gameweek"])
    last = as_int(gameweeks["gameweek"].max())
    horizon = [
        gameweek
        for gameweek in range(next_gameweek, next_gameweek + config.horizon_gameweeks)
        if gameweek <= last
    ]
    return next_gameweek, pd.Timestamp(first["deadline_time"]).tz_convert("UTC"), horizon


def build_forecast(
    inputs: ForecastInputs, rules: GameRules, config: ForecastConfig
) -> pd.DataFrame:
    """Produce the expected-points table from the component chain.

    Returns exactly the shape :func:`fpl_dof.forecast.xp_v0.build_forecast` returns — one row per
    player, per-gameweek expectations, a horizon total, a component decomposition, a standard
    deviation on every mean (Invariant 6) and a confidence tier — so the optimiser, the weekly
    decision and the publisher need no knowledge of which model produced it.
    """
    history = inputs.player_gameweek
    next_gameweek, deadline, horizon = next_deadline(inputs.gameweeks, config)
    if history is None or history.empty:
        raise ColdStartError("no per-gameweek history: the component chain has nothing to fit")

    past = history[history["kickoff_time"] < deadline]
    if past.empty:
        raise ColdStartError(f"no gameweek has kicked off before {deadline:%Y-%m-%d}")

    # **Team strength is fitted on this season only, and the restriction is deliberate.** Club ids
    # come from two sources in two spaces: the live feed writes FPL's *season-local* team id, and
    # the archive writes the stable club *code* (D-26), because a season-local id points at a
    # different club every year. Both are correct within their own season and meaningless across
    # the boundary, so pooling them would rate this season's clubs partly on numbers that belong to
    # other clubs — the same silent, plausible-looking wrongness the fixture ticker already refuses
    # (DL-37). This is also exactly what the live path did before D-26 was fixed, when every
    # archive row's null club was dropped here: the filter preserves the shipped behaviour rather
    # than changing it. Widening M2 to prior seasons is a model change and needs DP-08's evidence,
    # not a side effect of a source repair.
    #
    # The rate models below are unaffected: they are keyed on the player's stable code, which does
    # cross seasons, so they keep training on everything.
    this_season = past[past["season"] == rules.season]
    models = fit_components(
        training_set(history, deadline, config),
        team_matches(this_season, use_xg=config.expected_goals.team_strength_from_xg),
        config,
        rules,
    )

    identity = _identity(inputs.players, config)
    features = _features(
        past, identity, deadline=deadline, season=rules.season, inputs=inputs, config=config
    )
    # The tier describes the evidence the model actually had, so it is derived from the features
    # and carried onto the player record rather than the other way round.
    identity["confidence"] = (
        features.set_index("player_code")["confidence"].reindex(identity.index).fillna("none")
    )

    frame = horizon_frame(
        features,
        identity=identity,
        horizon=horizon,
        fixtures=fixture_index_from_fixtures(inputs.fixtures, horizon),
        models=models,
        rules=rules,
        config=config,
        status_multipliers=dict(identity["availability"]),
        discount=config.horizon_discount,
    )
    if frame.empty:
        raise ColdStartError("no player could be scored from the component chain")

    # M1 gives P(60+ minutes) directly, which is what "will he start" means for scoring purposes.
    # xp_v0 had to infer it from last season's start rate; this is the measured version (D-12).
    frame["start_probability"] = frame["p_long_appearance"].astype(float).clip(0.0, 1.0)
    frame["next_gameweek"] = next_gameweek
    frame["horizon_gameweeks"] = len(horizon)

    log.info(
        "forecast.built",
        extra={
            "model": MODEL_NAME,
            "players": len(frame),
            "next_gameweek": next_gameweek,
            "horizon": len(horizon),
            "mean_xp_next": round(float(frame["xp_next"].mean()), 3),
        },
    )
    return frame


def training_set(
    history: pd.DataFrame, deadline: pd.Timestamp, config: ForecastConfig
) -> pd.DataFrame:
    """Every (player, gameweek) outcome knowable at the deadline, with its features.

    Assembled through the walk-forward harness's own functions rather than by a second route. A
    second assembly of the training set is a second chance to leak (Invariant 5), and it is also
    the only way to be sure the live model is fitted on what the backtest graded.
    """
    cache: dict[pd.Timestamp, pd.DataFrame] = {}
    for season, gameweek, moment in deadlines_for(history):
        if moment >= deadline:
            continue
        cache[moment] = fold_rows(history, season, gameweek, moment, config)
    training = training_rows(cache, before=deadline)
    if training.empty:
        raise ColdStartError(
            "no completed gameweek has both features and outcomes before the deadline"
        )
    return training


def _identity(players: pd.DataFrame, config: ForecastConfig) -> pd.DataFrame:
    """The published player record, indexed by ``player_code``, plus availability and confidence."""
    frame = players.copy()
    frame["player_code"] = frame["code"].map(as_int)

    availability = pd.to_numeric(
        frame["status"].map(config.status_multiplier), errors="coerce"
    ).fillna(0.0)
    # A stated chance of playing overrides the flag when FPL gives one. Coerced explicitly: an
    # all-null column arrives as object dtype, and object arithmetic silently poisons everything
    # downstream of it.
    stated = pd.to_numeric(frame["chance_of_playing_next_round"], errors="coerce") / 100.0
    frame["availability"] = stated.where(stated.notna(), availability).astype(float).clip(0.0, 1.0)

    columns = [column for column in IDENTITY_COLUMNS if column in frame.columns]
    identity = frame[["player_code", *columns, "availability"]].drop_duplicates("player_code")
    return identity.set_index("player_code")


def _features(
    past: pd.DataFrame,
    identity: pd.DataFrame,
    *,
    deadline: pd.Timestamp,
    season: str,
    inputs: ForecastInputs,
    config: ForecastConfig,
) -> pd.DataFrame:
    """The feature store's view of every player, including those it has never seen."""
    features = build_features(
        past,
        as_of=deadline,
        config=config.features,
        positions=past[["player_code", "position"]],
        metrics=inputs.metrics,
        season=season,
    )
    if features.empty:
        raise ColdStartError(f"no feature row could be built at {deadline:%Y-%m-%d}")

    minutes = past.groupby("player_code")["minutes"].sum()
    features["evidence_minutes"] = features["player_code"].map(minutes).astype(float).fillna(0.0)
    completed = _unseen_players(features, identity, deadline=deadline, config=config)
    if not completed.empty:
        features = pd.concat([features, completed], ignore_index=True)
    features["confidence"] = confidence_tier(features["evidence_minutes"], config)
    return features


def _unseen_players(
    features: pd.DataFrame,
    identity: pd.DataFrame,
    *,
    deadline: pd.Timestamp,
    config: ForecastConfig,
) -> pd.DataFrame:
    """Empty feature rows for players with no minutes yet, so each model returns its prior.

    A new signing, a promoted club's squad, a player back from a long injury: none of them have a
    rolling rate, and none of them is worth zero points. Absent rows would drop them from the
    published frame entirely, which is how a player becomes silently unselectable.
    """
    seen = set(features["player_code"])
    missing = [code for code in identity.index if as_int(code) not in seen]
    if not missing:
        return pd.DataFrame()
    rows = [
        {
            "player_code": as_int(code),
            "as_of": deadline,
            "position": str(identity.loc[code, "position"]),
            "matches_observed": 0,
            "appearance_rate": 0.0,
            "evidence_minutes": 0.0,
            # Zero rather than null: "no minutes observed" is a measurement, and a null here would
            # reach the rate models as a NaN and propagate through their shrinkage arithmetic.
            **{f"minutes_mean_last{window}": 0.0 for window in config.features.rolling_windows},
        }
        for code in missing
    ]
    return pd.DataFrame(rows)


__all__ = [
    "IDENTITY_COLUMNS",
    "MODEL_NAME",
    "ColdStartError",
    "build_forecast",
    "completed_gameweeks",
    "next_deadline",
    "training_set",
]
