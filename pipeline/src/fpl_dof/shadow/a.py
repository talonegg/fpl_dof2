"""A — component expected points: P(play) x the FPL points of each modelled event | play.

Port of the frozen bundle's ``backtest/comp_model.py`` (factory ``comp_A``), the ``a`` challenger's
forecaster. Per position, HistGBMs fitted on every season silver holds predict P(play), P(a full
appearance | play), and the Poisson rates of bonus, goals and assists (outfield) or saves
(goalkeepers) given he plays; a classifier predicts the defensive-contribution award. The club layer
is C1's: P(clean sheet) = exp(-lambda) and goals conceded ~ Poisson(lambda), lambda the mean of the
club's rolling xG against and the opponent's rolling xG for, per fixture. Each event is priced by
:class:`~fpl_dof.rules.models.GameRules` (Invariant 2), and cards, own goals and penalties are left
out as the frozen model left them (small and noisy).

**Built on C1.** A's features are C1's (:func:`fpl_dof.shadow.c1.build_features`, as the frozen A
was built on ``vector_models.build_features``) plus the rolling goals, assists, saves and award of
:func:`specs`; its frame is C1's one-gameweek frame (:func:`~fpl_dof.shadow.c1.forecast_with`):
P(play) scaled by availability news, the two-state mixture's variance and its own B0 captain line.

**Variance (Invariant 6).** Points given play are a sum of independent events, each with its own
variance: Bernoulli for the full appearance, clean sheet and award, Poisson for bonus, goals and
assists, and the exact moments of floor(N / k) for saves and goals conceded. Covariances between
events (a clean sheet and goals conceded, say) are ignored; the mixture over playing adds the term
that dominates.

Differences from the frozen original, all deliberate (05 §5.2):

- Points per event from ``GameRules``, never literals: goals and clean sheets by position, assists,
  bonus, the appearance points and the minutes threshold between them, saves per point, goals
  conceded per point, and the award's threshold and points by position. A position whose rules give
  no award gets none; goals conceded cost what the rules say by position, not only for GKP and DEF.
- The award is gated on the data: its classifier is fitted only where silver records defensive
  contributions (none before 2025/26) and applied wherever it was fitted, never on a season label.
- Hyperparameters, windows, the club-goals prior and its bounds from ``forecast.a`` (DP-06); every
  fit seeded (DP-11).
- Refitted every run, not every fourth gameweek; the live fit stops at the first unfinished
  gameweek (REM-08), as C1's does.
- Its own variance and P(play) scaled by availability, where the frozen frame carried a mean only
  and the harness scaled it afterwards.
- A position where every row played, or a count never above zero, gets a constant rather than a
  fit that would fail.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from fpl_dof.config.models import AConfig, ForecastConfig
from fpl_dof.forecast import baselines
from fpl_dof.forecast.baselines import FittedBaseline
from fpl_dof.forecast.entry import Forecast
from fpl_dof.forecast.features import TARGET, FeatureSpec, Knowability, assert_no_look_ahead
from fpl_dof.forecast.fit import ColdStartError
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.rules.models import GameRules, Position, PositionMap
from fpl_dof.shadow import c1

MODEL_NAME = "a_component_xp"

#: The per-gameweek counts A models beyond C1's features: its name -> the silver column summed.
COUNTS = {"goals": "goals_scored", "assists": "assists", "saves": "saves"}
#: Whether the player earned the defensive-contribution award in the gameweek.
AWARD = "dc"
#: Outcome columns A reads that an upcoming row has no value for yet.
OUTCOMES = (*COUNTS.values(), "defensive_contribution")


def specs(config: AConfig) -> tuple[FeatureSpec, ...]:
    """C1's features, and A's rolling counts, each with the moment it becomes knowable."""
    window = config.component_window
    extra = tuple(
        FeatureSpec(
            f"{name}_l{window}",
            Knowability.BEFORE_DEADLINE,
            f"Mean {name} per gameweek over the player's previous {window} this season",
            (source,),
        )
        for name, source in {**COUNTS, AWARD: "defensive_contribution"}.items()
    )
    return (*c1.specs(config), *extra)


def input_features(config: AConfig) -> tuple[str, ...]:
    return tuple(s.name for s in specs(config) if s.is_input)


def _by_position(positions: pd.Series, values: PositionMap) -> pd.Series:
    return positions.map({p.value: v for p, v in values.items()}).astype(float)


def _award(rows: pd.DataFrame, rules: GameRules) -> pd.Series:
    """1 where the gameweek's defensive contribution met the rules' threshold, 0 where not or where
    the position earns no award, NaN where silver recorded none (before 2025/26)."""
    count = pd.to_numeric(rows["defensive_contribution"], errors="coerce").astype(float)
    threshold = _by_position(rows["position"], rules.scoring.defensive_contribution_threshold)
    points = _by_position(rows["position"], rules.scoring.defensive_contribution)
    hit = (count >= threshold).astype(float).where(points > 0, 0.0)
    return hit.where(count.notna())


def build_features(
    past: pd.DataFrame,
    upcoming: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    config: AConfig,
    rules: GameRules,
) -> pd.DataFrame:
    """C1's feature rows, plus each count's mean over the previous ``component_window`` gameweeks
    of the same season (shifted, as C1's are) and the gameweek's own counts as targets."""
    g = c1.build_features(past, upcoming, as_of=as_of, config=config)
    rows = pd.concat([past, upcoming], ignore_index=True)
    rows = rows.assign(
        key=rows["season"] + "|" + rows["player_code"].astype(str), **{AWARD: _award(rows, rules)}
    )
    sums: dict[str, tuple[str, str]] = {name: (source, "sum") for name, source in COUNTS.items()}
    counts = rows.groupby(["key", "gameweek"], as_index=False).agg(
        **sums, **{AWARD: (AWARD, "max")}
    )
    g = g.merge(counts, on=["key", "gameweek"], how="left")
    window = config.component_window
    for name in (*COUNTS, AWARD):
        shifted = g.groupby("key")[name].shift(1)
        rolled = shifted.groupby(g["key"]).rolling(window, min_periods=1).mean()
        g[f"{name}_l{window}"] = rolled.reset_index(0, drop=True)
    g[f"{AWARD}_l{window}"] = g[f"{AWARD}_l{window}"].fillna(-1)  # no record: as C1's prev_*
    return g


class _Constant:
    """A component with nothing to learn: every row of its target had the same value."""

    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.full(len(x), self.value)

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        return np.column_stack([1.0 - self.predict(x), self.predict(x)])


def _classifier(kw: dict[str, Any], x: pd.DataFrame, y: pd.Series) -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier

    target = y.astype(int)
    if target.nunique() < 2:
        return _Constant(float(target.iloc[0]))
    return HistGradientBoostingClassifier(**kw).fit(x, target)


def _rate(kw: dict[str, Any], x: pd.DataFrame, y: pd.Series) -> Any:
    from sklearn.ensemble import HistGradientBoostingRegressor

    target = y.astype(float)
    if not (target > 0).any():
        return _Constant(0.0)
    return HistGradientBoostingRegressor(loss="poisson", **kw).fit(x, target)


def floor_moments(rate: np.ndarray, per: int, support: int) -> tuple[np.ndarray, np.ndarray]:
    """E[floor(N / per)] and E[floor(N / per)^2] for N ~ Poisson(``rate``), over 0..support-1."""
    lam = np.asarray(rate, dtype=float).reshape(-1, 1)
    counts = np.arange(support)
    ratio = lam / np.maximum(counts, 1)
    ratio[:, 0] = 1.0
    pmf = np.exp(-lam) * np.cumprod(ratio, axis=1)  # P(N = n) = e^-lam * prod_{j<=n} lam / j
    units = (counts // per).astype(float)
    return pmf @ units, pmf @ units**2


def club_layer(rows: pd.DataFrame, config: AConfig, rules: GameRules) -> pd.DataFrame:
    """Per row, the clean-sheet and goals-conceded sums over the gameweek's fixtures, from the
    club's rolling xG against and the opponent's xG for (the frozen candidate's opposition)."""
    fixtures = rows["nfix"].clip(lower=1).to_numpy(dtype=float)
    prior = config.team_goals_prior
    against = (rows["xga_r"].fillna(prior) + rows["opp_xgf_r"].fillna(prior)) / 2
    lam = (against.to_numpy(dtype=float) / fixtures).clip(
        config.fixture_goals_minimum, config.fixture_goals_maximum
    )
    clean = np.exp(-lam)
    first, second = floor_moments(
        lam, rules.scoring.goals_conceded_per_point, config.poisson_support
    )
    return pd.DataFrame(
        {
            "cs_sum": fixtures * clean,
            "cs_sq_sum": fixtures * clean**2,
            "gc_mean": fixtures * first,
            "gc_second": fixtures * second,
            "gc_mean_sq": fixtures * first**2,
        },
        index=rows.index,
    )


def points_given_play(
    table: pd.DataFrame, positions: pd.Series, rules: GameRules
) -> tuple[pd.Series, pd.Series]:
    """Mean and variance of a player's points given he plays, from the component ``table``.

    Each event is independent: the appearance (short, or long with P(full)), clean sheets and goals
    conceded (counted only on a full appearance), bonus, goals, assists, saves and the award.
    """
    sc = rules.scoring
    full = table["p_long"]
    fixtures = table["nfix"]
    gain = sc.long_play - sc.short_play
    mean = fixtures * (sc.short_play + full * gain)
    var = fixtures * full * (1 - full) * gain**2
    clean = _by_position(positions, sc.clean_sheets)
    mean += clean * full * table["cs_sum"]
    var += clean**2 * (full * table["cs_sum"] - full**2 * table["cs_sq_sum"])
    conceded = _by_position(positions, sc.goals_conceded)
    mean += conceded * full * table["gc_mean"]
    var += conceded**2 * (full * table["gc_second"] - full**2 * table["gc_mean_sq"])
    goal = _by_position(positions, sc.goals_scored)
    award = _by_position(positions, sc.defensive_contribution)
    for points, rate in (
        (sc.bonus, table["bonus"]),
        (goal, table["goals"]),
        (sc.assists, table["assists"]),
    ):
        mean += points * rate
        var += points**2 * rate
    mean += sc.saves * table["saves_mean"]
    var += sc.saves**2 * table["saves_var"]
    mean += award * table[AWARD]
    var += award**2 * table[AWARD] * (1 - table[AWARD])
    return mean, var.clip(lower=0.0)


def summarise(rows: pd.DataFrame, table: pd.DataFrame, rules: GameRules) -> pd.DataFrame:
    """What :func:`~fpl_dof.shadow.c1.forecast_with` reads, from the component ``table``."""
    mean, var = points_given_play(table, rows["position"], rules)
    return pd.DataFrame(
        {
            "player_code": rows["player_code"],
            "p_play": table["p_play"],
            "mean_if_play": mean,
            "sd_if_play": np.sqrt(var),
        }
    )


@dataclass(frozen=True, slots=True)
class FittedA:
    """A fitted on everything played before ``as_of``: per position its component models, and B0
    on the same rows. ``train`` keeps the feature rows, which A_odds' share prior is a mean over."""

    config: AConfig
    rules: GameRules
    as_of: pd.Timestamp
    past: pd.DataFrame
    train: pd.DataFrame
    models: dict[str, dict[str, Any]]
    b0: FittedBaseline

    def rebased(self, past: pd.DataFrame, as_of: pd.Timestamp) -> FittedA:
        """These weights, predicting at an earlier deadline from ``past`` (ORC-13, DL-97)."""
        return dataclasses.replace(self, past=past, as_of=c1.utc_deadline(as_of))

    def rows(self, upcoming: pd.DataFrame) -> pd.DataFrame:
        """The feature rows of the players in ``upcoming`` (one gameweek, a row per fixture)."""
        missing = {c: np.nan for c in OUTCOMES if c not in upcoming.columns}
        g = build_features(
            self.past,
            upcoming.assign(**missing),
            as_of=self.as_of,
            config=self.config,
            rules=self.rules,
        )
        assert_no_look_ahead(g, self.past, as_of=self.as_of)
        return g[g[c1.UPCOMING]].reset_index(drop=True)

    def components(self, rows: pd.DataFrame) -> pd.DataFrame:
        """Each row's component rates given he plays, and its club layer. A position with no
        fitted model reads 0 throughout."""
        saves_per_point = self.rules.scoring.saves_per_point
        table = pd.DataFrame(
            0.0,
            index=rows.index,
            columns=["p_play", "p_long", "bonus", "goals", "assists", "saves_mean", "saves_var"],
        )
        table[AWARD] = 0.0
        table["nfix"] = rows["nfix"].clip(lower=1).astype(float)
        features = list(input_features(self.config))
        for position, models in self.models.items():
            mask = rows["position"] == position
            if not mask.any():
                continue
            x = rows.loc[mask, features]
            table.loc[mask, "p_play"] = models["play"].predict_proba(x)[:, 1]
            table.loc[mask, "p_long"] = models["long"].predict_proba(x)[:, 1]
            table.loc[mask, "bonus"] = models["bonus"].predict(x)
            for name in ("goals", "assists"):
                if name in models:
                    table.loc[mask, name] = models[name].predict(x)
            if "saves" in models:
                first, second = floor_moments(
                    models["saves"].predict(x), saves_per_point, self.config.poisson_support
                )
                table.loc[mask, "saves_mean"] = first
                table.loc[mask, "saves_var"] = second - first**2
            if models.get(AWARD) is not None:
                table.loc[mask, AWARD] = models[AWARD].predict_proba(x)[:, 1]
        return table.join(club_layer(rows, self.config, self.rules))

    def predict(self, upcoming: pd.DataFrame) -> pd.DataFrame:
        """``player_code``, ``p_play``, ``mean_if_play`` and ``sd_if_play`` for each player."""
        rows = self.rows(upcoming)
        return summarise(rows, self.components(rows), self.rules)


def fit_as_of(
    past: pd.DataFrame, as_of: pd.Timestamp, config: AConfig, rules: GameRules
) -> FittedA:
    """Fit A on ``past``, every row of which must have kicked off before ``as_of``."""
    moment = c1.utc_deadline(as_of)
    g = build_features(past, past.iloc[:0], as_of=moment, config=config, rules=rules)
    assert_no_look_ahead(g, past, as_of=moment)
    train = g[g.gp > 0]
    if train.empty:
        raise ColdStartError("A has no player with an earlier gameweek to learn from")
    features = list(input_features(config))
    kw: dict[str, Any] = {
        "max_iter": config.max_iter,
        "learning_rate": config.learning_rate,
        "min_samples_leaf": config.min_samples_leaf,
        "early_stopping": config.early_stopping,
        "random_state": config.seed,
    }
    awards = rules.scoring.defensive_contribution
    models: dict[str, dict[str, Any]] = {}
    for position in Position:
        p = train[train.position == position.value]
        played = p[p.minutes > 0]
        if played.empty:
            continue
        x = played[features]
        m: dict[str, Any] = {
            "play": _classifier(kw, p[features], p.minutes > 0),
            "long": _classifier(kw, x, played.minutes >= rules.scoring.long_play_minutes),
            "bonus": _rate(kw, x, played.bonus),
        }
        if position is Position.GKP:
            m["saves"] = _rate(kw, x, played.saves)
        else:
            m["goals"] = _rate(kw, x, played.goals)
            m["assists"] = _rate(kw, x, played.assists)
        recorded = played[played[AWARD].notna()]
        if awards[position] > 0 and len(recorded) > config.defensive_contribution_minimum_rows:
            m[AWARD] = _classifier(kw, recorded[features], recorded[AWARD])
        models[position.value] = m
    return FittedA(
        config=config,
        rules=rules,
        as_of=moment,
        past=past,
        train=train,
        models=models,
        b0=baselines.fit_b0(train, TARGET),
    )


def forecast(
    inputs: ForecastInputs,
    rules: GameRules,
    config: ForecastConfig,
    *,
    fitted: c1.Fitted | None = None,
) -> Forecast:
    """A's forecast frame for the gameweek being decided, fitted on history before its cutoff."""
    return c1.forecast_with(
        inputs,
        rules,
        config,
        MODEL_NAME,
        lambda past, cutoff: fit_as_of(past, cutoff, config.a, rules),
        fitted=fitted,
    )


class APredictor(c1.C1Predictor):
    """A behind the walk-forward harness's interface, as :class:`~fpl_dof.shadow.c1.C1Predictor`."""

    name = MODEL_NAME

    def _fit(self, past: pd.DataFrame, moment: pd.Timestamp) -> c1.Fitted:
        return fit_as_of(past, moment, self.config.a, self.rules)


__all__ = [
    "AWARD",
    "COUNTS",
    "MODEL_NAME",
    "OUTCOMES",
    "APredictor",
    "FittedA",
    "build_features",
    "club_layer",
    "fit_as_of",
    "floor_moments",
    "forecast",
    "input_features",
    "points_given_play",
    "specs",
    "summarise",
]
