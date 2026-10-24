"""A_odds — model A with the betting market's club layer wherever the market covers the gameweek.

Port of the frozen bundle's ``backtest/ot_models.py`` ``CompOT`` (factory ``comp_ot``), the
``a_odds`` challenger's forecaster. For a player whose club has odds for every one of its fixtures
in the gameweek, knowable before the deadline, the market replaces A's club layer:

- clean sheets: the market's P(clean sheet) per fixture; goals conceded ~ Poisson(the market's
  expected goals against), per fixture;
- goals: the club's market expected goals times the player's share of his club's xG over the
  last ``forecast.a.component_window`` gameweeks, shrunk toward his position and price band's mean
  share until he has played; assists likewise, times ``assist_fraction``;
- goalkeeper saves ~ Poisson(market expected goals against x saves per goal conceded), per fixture.

P(play), P(a full appearance), bonus and the award stay A's, and so does every other player-week:
A's own estimate stands wherever the market does not cover the club's whole gameweek, as the
frozen model's did. Points come from :class:`~fpl_dof.rules.models.GameRules` and variance is A's
(:func:`fpl_dof.shadow.a.points_given_play`).

**Odds and knowability.** Odds are silver ``team_match_expectation`` (the forecast inputs'
``match_odds``), de-vigged behind the source adapter. A fixture's odds are its latest capture at or
before its gameweek's deadline (:func:`fpl_dof.gold.match_odds.knowable`, the rule gold applies);
a past season's deadline is its gameweek's earliest kickoff, the backtest's convention
(``forecast.backtest.deadlines_for``), and no capture after the run's ``as_of`` is read
(Invariant 5).

Differences from the frozen original, all deliberate (05 §5.2):

- Odds from silver, de-vigged by the source adapter, not the bundle's own Pinnacle-first reading
  with a Shin de-vig (DL-89 item 7); P(clean sheet) is the source's rather than recomputed as
  exp(-lambda); captures are filtered by the gold deadline rule above.
- Shots on target are not in silver. Saves per goal conceded, measured over goalkeepers' played
  gameweeks before the deadline, replaces the frozen shots on target per goal less one; its default,
  floor and minimum sample are ``forecast.a_odds``.
- No odds knowable for the gameweek being decided is :class:`MissingOddsError`, so the strategy
  records "no advice" (DL-87); the frozen harness fell back to A silently. The walk-forward
  predictor still falls back to A per club-gameweek, as the frozen backtest did.
- Points from ``GameRules`` and every tunable from ``forecast.a_odds`` and ``forecast.a``; A's
  own differences (``shadow/a.py``) apply beneath it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fpl_dof.config.models import AOddsConfig, ForecastConfig
from fpl_dof.forecast import live
from fpl_dof.forecast.baselines import FittedBaseline
from fpl_dof.forecast.entry import Forecast
from fpl_dof.forecast.features import season_start_year
from fpl_dof.forecast.inputs import ForecastInputs, MissingInputError
from fpl_dof.gold.match_odds import club_coded, knowable
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.shadow import a, c1
from fpl_dof.silver.tables import Table

MODEL_NAME = "a_odds_team_layer"

#: One club-fixture of market expectations, in the forecast history's team ids.
ODDS_COLUMNS = ("season", "gameweek", "team_id", "goals_for", "goals_against", "clean_sheet")
#: The club-layer columns of A's component table the market replaces.
CLUB_COLUMNS = ("cs_sum", "cs_sq_sum", "gc_mean", "gc_second", "gc_mean_sq")


class MissingOddsError(MissingInputError):
    """No match odds are knowable for the gameweek being decided: A_odds has no advice (DL-87)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, (Table.TEAM_MATCH_EXPECTATION.value,))


def _calendar(inputs: ForecastInputs, season: str) -> pd.DataFrame:
    """Every fixture odds can belong to, by club code, with its gameweek's deadline: this season's
    from the fixture list, earlier seasons' from the played history."""
    codes = dict(zip(inputs.teams["team_id"], inputs.teams["code"], strict=True))
    fixtures = inputs.fixtures.dropna(subset=["gameweek"]).merge(
        inputs.gameweeks[["gameweek", "deadline_time"]], on="gameweek", how="left"
    )
    current = fixtures.assign(
        season=season,
        home_team_code=fixtures["home_team_id"].map(codes),
        away_team_code=fixtures["away_team_id"].map(codes),
    )
    frames = [current]
    history = inputs.player_gameweek
    if history is not None and not history.empty:
        home = history[(history["season"] != season) & history["was_home"].astype(bool)]
        frames.append(
            home.assign(
                home_team_code=home["team_id"],
                away_team_code=home["opponent_team_id"],
                deadline_time=home.groupby(["season", "gameweek"])["kickoff_time"].transform("min"),
            ).drop_duplicates(["season", "fixture_id"])
        )
    columns = ["season", "home_team_code", "away_team_code", "fixture_id", "gameweek"]
    calendar = pd.concat([f[[*columns, "deadline_time"]] for f in frames], ignore_index=True)
    return calendar.astype({"home_team_code": "Int64", "away_team_code": "Int64"})


def team_odds(inputs: ForecastInputs, season: str) -> pd.DataFrame:
    """Each club's market expectations per fixture (:data:`ODDS_COLUMNS`), knowable before its
    gameweek's deadline and the run's ``as_of``, in the history's team ids (season-local in
    ``season``, the archive's club codes before it)."""
    odds = inputs.match_odds
    if odds is None or odds.empty:
        return pd.DataFrame(columns=list(ODDS_COLUMNS))
    odds = odds[odds["captured_at"] <= pd.Timestamp(inputs.as_of)]
    latest = knowable(club_coded(odds, season, inputs.teams), _calendar(inputs, season))
    latest = latest.dropna(subset=["gameweek"])
    sides = pd.concat(
        [
            latest.assign(
                code=latest["home_team_code"],
                goals_for=latest["expected_goals_home"],
                goals_against=latest["expected_goals_away"],
                clean_sheet=latest["clean_sheet_probability_home"],
            ),
            latest.assign(
                code=latest["away_team_code"],
                goals_for=latest["expected_goals_away"],
                goals_against=latest["expected_goals_home"],
                clean_sheet=latest["clean_sheet_probability_away"],
            ),
        ],
        ignore_index=True,
    )
    local = dict(zip(inputs.teams["code"], inputs.teams["team_id"], strict=True))
    team = sides["code"].where(sides["season"] != season, sides["code"].map(local))
    return (
        sides.assign(team_id=team, gameweek=sides["gameweek"].astype(int))
        .dropna(subset=["team_id"])
        .astype({"team_id": int})[list(ODDS_COLUMNS)]
        .reset_index(drop=True)
    )


def club_expected(history: pd.DataFrame, window: int) -> pd.DataFrame:
    """Each club's mean xG and xA per gameweek over its previous ``window`` this season, by
    ``(season, t, team_id)``, ``t`` as C1's feature rows carry it."""
    year = history["season"].map(season_start_year).astype(int)
    d = history.assign(t=year * 100 + history["gameweek"])
    stats = ["expected_goals", "expected_assists"]
    club = d.groupby(["season", "t", "team_id"], as_index=False)[stats].sum()
    club = club.sort_values("t", kind="stable")
    grouped = club.groupby(["season", "team_id"])
    for stat in stats:
        club[f"club_{stat}"] = grouped[stat].transform(
            lambda x: x.shift(1).rolling(window, min_periods=1).mean()
        )
    return club[["season", "t", "team_id", "club_expected_goals", "club_expected_assists"]]


def shares(
    rows: pd.DataFrame, club: pd.DataFrame, config: AOddsConfig, window: int
) -> pd.DataFrame:
    """Each row's share of his club's xG and xA per match played, over the last ``window``
    gameweeks, and his price band; aligned to ``rows``."""
    r = rows[["season", "t", "team_id"]].merge(club, on=["season", "t", "team_id"], how="left")
    r.index = rows.index
    played = (rows[f"minutes_l{window}"].fillna(0) / config.match_minutes).clip(
        lower=config.minimum_play_fraction
    )
    out = pd.DataFrame(index=rows.index)
    for share, stat in (("xg_share", "expected_goals"), ("xa_share", "expected_assists")):
        club_rate = r[f"club_{stat}"].clip(lower=config.team_xg_floor)
        out[share] = (rows[f"{stat}_l{window}"] / club_rate / played).clip(0.0, 1.0)
    edges = [-np.inf, *config.price_band_edges, np.inf]
    out["band"] = pd.cut(rows["price"], edges, labels=False)
    out["position"] = rows["position"]
    return out


def saves_per_goal_conceded(past: pd.DataFrame, config: AOddsConfig) -> float:
    """Goalkeeper saves per goal conceded over the played gameweeks in ``past``, floored; the
    configured default when there are too few appearances to measure it."""
    keepers = past[(past["position"] == Position.GKP.value) & (past["minutes"] > 0)]
    conceded = float(keepers["goals_conceded"].sum())
    if len(keepers) < config.saves_rate_minimum_appearances or conceded <= 0:
        rate = config.saves_per_goal_conceded_default
    else:
        rate = float(keepers["saves"].sum()) / conceded
    return max(rate, config.saves_per_goal_conceded_floor)


@dataclass(frozen=True, slots=True)
class FittedAOdds:
    """A fitted before the deadline, with the market odds, the share prior by position and price
    band, and the saves rate the market layer reads."""

    base: a.FittedA
    config: AOddsConfig
    odds: pd.DataFrame
    prior: pd.DataFrame
    saves_per_goal: float

    @property
    def past(self) -> pd.DataFrame:
        return self.base.past

    @property
    def b0(self) -> FittedBaseline:
        return self.base.b0

    def rebased(self, past: pd.DataFrame, as_of: pd.Timestamp) -> FittedAOdds:
        """These weights, predicting at an earlier deadline from ``past`` (ORC-13, DL-97)."""
        return dataclasses.replace(self, base=self.base.rebased(past, as_of))

    def predict(self, upcoming: pd.DataFrame) -> pd.DataFrame:
        """A's prediction, with the market's club layer for every player whose club's gameweek
        it covers."""
        rows = self.base.rows(upcoming)
        table = self.base.components(rows)
        club = club_expected(pd.concat([self.past, upcoming], ignore_index=True), self.window)
        return a.summarise(rows, self._market(rows, table, club), self.base.rules)

    @property
    def window(self) -> int:
        return self.base.config.component_window

    def _market(self, rows: pd.DataFrame, table: pd.DataFrame, club: pd.DataFrame) -> pd.DataFrame:
        scoring = self.base.rules.scoring
        support = self.base.config.poisson_support
        o = self.odds
        gc1, gc2 = a.floor_moments(
            o["goals_against"].to_numpy(dtype=float), scoring.goals_conceded_per_point, support
        )
        sv1, sv2 = a.floor_moments(
            o["goals_against"].to_numpy(dtype=float) * self.saves_per_goal,
            scoring.saves_per_point,
            support,
        )
        per_fixture = o.assign(
            n_odds=1.0,
            cs_sum=o["clean_sheet"],
            cs_sq_sum=o["clean_sheet"] ** 2,
            gc_mean=gc1,
            gc_second=gc2,
            gc_mean_sq=gc1**2,
            saves_mean=sv1,
            saves_var=sv2 - sv1**2,
        )
        summed = ["n_odds", "goals_for", *CLUB_COLUMNS, "saves_mean", "saves_var"]
        club_week = per_fixture.groupby(["season", "gameweek", "team_id"], as_index=False)[
            summed
        ].sum()
        keys = ["season", "gameweek", "team_id"]
        m = rows[keys].merge(club_week, on=keys, how="left")
        m.index = rows.index
        covered = m["n_odds"] == rows["nfix"]  # every fixture of the club's gameweek priced
        keeper = rows["position"] == Position.GKP.value
        out = table.copy()
        out.loc[covered, list(CLUB_COLUMNS)] = m.loc[covered, list(CLUB_COLUMNS)]
        out.loc[covered & keeper, ["saves_mean", "saves_var"]] = m.loc[
            covered & keeper, ["saves_mean", "saves_var"]
        ]
        outfield = covered & ~keeper
        if outfield.any():
            own = shares(rows, club, self.config, self.window)
            goals = m["goals_for"] * self._shrunk(rows, own, "xg_share")
            assists = m["goals_for"] * self._shrunk(rows, own, "xa_share")
            out.loc[outfield, "goals"] = goals[outfield]
            out.loc[outfield, "assists"] = assists[outfield] * self.config.assist_fraction
        return out

    def _shrunk(self, rows: pd.DataFrame, own: pd.DataFrame, share: str) -> pd.Series:
        keys = pd.MultiIndex.from_frame(own[["position", "band"]])
        prior = pd.Series(keys.map(self.prior[share].to_dict()), index=rows.index).astype(float)
        seen = rows["gp"].clip(upper=self.window).astype(float)
        weight = self.config.share_shrinkage
        return (seen * own[share].fillna(0.0) + weight * prior.fillna(0.0)) / (seen + weight)


def fit_as_of(
    past: pd.DataFrame,
    as_of: pd.Timestamp,
    config: ForecastConfig,
    rules: GameRules,
    odds: pd.DataFrame,
) -> FittedAOdds:
    """Fit A on ``past`` (every row kicked off before ``as_of``), and the market layer's share
    prior and saves rate on the same rows."""
    base = a.fit_as_of(past, as_of, config.a, rules)
    window = config.a.component_window
    played = base.train[base.train["minutes"] > 0]
    own = shares(played, club_expected(past, window), config.a_odds, window)
    prior = own.groupby(["position", "band"])[["xg_share", "xa_share"]].mean()
    return FittedAOdds(
        base=base,
        config=config.a_odds,
        odds=odds,
        prior=prior,
        saves_per_goal=saves_per_goal_conceded(past, config.a_odds),
    )


def forecast(
    inputs: ForecastInputs,
    rules: GameRules,
    config: ForecastConfig,
    *,
    fitted: FittedAOdds | None = None,
) -> Forecast:
    """A_odds' forecast frame for the gameweek being decided, or :class:`MissingOddsError` when
    no odds are knowable for it. Given ``fitted``, its weights read these inputs' odds."""
    gameweek, _, _ = live.next_deadline(inputs.gameweeks, config, as_of=inputs.as_of)
    odds = team_odds(inputs, rules.season)
    if not ((odds["season"] == rules.season) & (odds["gameweek"] == gameweek)).any():
        raise MissingOddsError(f"no match odds knowable before the gameweek {gameweek} deadline")
    return c1.forecast_with(
        inputs,
        rules,
        config,
        MODEL_NAME,
        lambda past, cutoff: fit_as_of(past, cutoff, config, rules, odds),
        fitted=None if fitted is None else dataclasses.replace(fitted, odds=odds),
    )


class AOddsPredictor(c1.C1Predictor):
    """A_odds behind the walk-forward harness's interface, with the odds it reads
    (:func:`team_odds`) given up front; a club-gameweek without them is A's estimate."""

    name = MODEL_NAME

    def __init__(self, config: ForecastConfig, rules: GameRules, odds: pd.DataFrame) -> None:
        super().__init__(config, rules)
        self.odds = odds

    def _fit(self, past: pd.DataFrame, moment: pd.Timestamp) -> c1.Fitted:
        return fit_as_of(past, moment, self.config, self.rules, self.odds)


__all__ = [
    "CLUB_COLUMNS",
    "MODEL_NAME",
    "ODDS_COLUMNS",
    "AOddsPredictor",
    "FittedAOdds",
    "MissingOddsError",
    "club_expected",
    "fit_as_of",
    "forecast",
    "saves_per_goal_conceded",
    "shares",
    "team_odds",
]
