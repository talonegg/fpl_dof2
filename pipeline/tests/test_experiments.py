"""MOD-08: the standing multi-strategy backtest and its experiments store.

Every strategy is walked over the same folds and graded on the same rows, inside its own training
window; each challenger is paired against the champion per gameweek with a seeded bootstrap; and
every run stamps one record per strategy, which the model card reads for the champion's current
digest only. Synthetic data throughout, kept small so the suite stays fast.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from fpl_dof.config.models import BacktestConfig, Config, ForecastConfig
from fpl_dof.factory import ForecastInputs, Graded, experiment_records, latest_verdict
from fpl_dof.factory.experiments import EXPERIMENTS_DIR, entrants, grade, load_declared
from fpl_dof.factory.registry import load_registry, stamp, strategies
from fpl_dof.forecast.backtest import BacktestResult, Entrant, prediction_column, walk_forward
from fpl_dof.forecast.features import rolling_feature_names
from fpl_dof.forecast.metrics import bootstrap_ci, paired_deltas
from fpl_dof.forecast.models import RATE_COMPONENTS
from fpl_dof.rules.models import GameRules
from fpl_dof.shadow import c1
from fpl_dof.silver.tables import Table
from test_backtest import SEASON, RateFromFeatures, make_history
from test_decide import _forecast_config, _snapshot, match_odds
from test_strategy_registry import _entry, _write

PRIOR = "2024/25"
BACKTEST = BacktestConfig(minimum_training_matches=3)


def _two_seasons() -> pd.DataFrame:
    """Two eight-gameweek seasons, the earlier a year before the later."""
    prior = make_history(gameweeks=8, season=PRIOR, seed=3)
    prior["kickoff_time"] = prior["kickoff_time"] - pd.Timedelta(days=365)
    return pd.concat([prior, make_history(gameweeks=8)], ignore_index=True)


def _walk(history: pd.DataFrame, *entered: Entrant) -> BacktestResult:
    return walk_forward(
        history, list(entered), forecast_config=ForecastConfig(), backtest_config=BACKTEST
    )


class Offset(RateFromFeatures):
    """A worse forecaster: the correct one, shifted by a constant."""

    def predict(self, features: pd.DataFrame, *, gameweek: int | None = None) -> pd.Series:
        return super().predict(features, gameweek=gameweek) + 3.0


class WindowRecorder(RateFromFeatures):
    """Records which seasons each fit and each prediction was built from."""

    def __init__(self) -> None:
        super().__init__()
        self.fits: list[tuple[str, set[str], set[str]]] = []
        self.most_matches: list[int] = []

    def fit_as_of(
        self,
        history: pd.DataFrame,
        deadline: pd.Timestamp,
        *,
        training: pd.DataFrame | None = None,
        season: str,
    ) -> None:
        assert training is not None
        self.fits.append((season, set(history["season"]), set(training["season"])))
        super().fit_as_of(history, deadline, training=training, season=season)

    def predict(self, features: pd.DataFrame, *, gameweek: int | None = None) -> pd.Series:
        self.most_matches.append(int(features["matches_observed"].max()))
        return super().predict(features, gameweek=gameweek)


def test_every_entrant_is_graded_on_the_same_folds_and_rows() -> None:
    history = make_history(gameweeks=8)
    alone = _walk(history, Entrant("c3", RateFromFeatures()))
    paired = _walk(history, Entrant("c3", RateFromFeatures()), Entrant("worse", Offset()))

    # Adding a challenger changes nothing about the champion's grade.
    assert paired.model.as_dict() == alone.model.as_dict()
    assert [(f.season, f.gameweek) for f in paired.folds] == [
        (f.season, f.gameweek) for f in alone.folds
    ]
    assert list(paired.strategies) == ["c3", "worse"]
    rows = paired.predictions
    assert rows[[prediction_column("c3"), prediction_column("worse")]].notna().all().all()
    assert paired.strategies["worse"].observations == paired.model.observations
    published = paired.as_dict()["strategies"]
    assert isinstance(published, dict) and "worse" in published


def test_each_strategy_sees_only_its_training_window() -> None:
    """F3: a ``current_season`` strategy is fitted and featured from the fold's season alone."""
    current, everything = WindowRecorder(), WindowRecorder()
    result = _walk(
        _two_seasons(),
        Entrant("c3", current, "current_season"),
        Entrant("c1", everything, "all_seasons"),
    )

    for season, history_seasons, training_seasons in current.fits:
        assert history_seasons == {season} and training_seasons == {season}
    later = [fit for fit in everything.fits if fit[0] == SEASON]
    assert later and all(fit[1] == {PRIOR, SEASON} == fit[2] for fit in later)
    # Features too: the current-season entrant never sees more matches than its season has had.
    assert max(current.most_matches) <= 8 < max(everything.most_matches)
    # A fold is graded only once every window holds three played gameweeks.
    assert min(f.gameweek for f in result.folds if f.season == SEASON) == 4
    assert result.training_windows == {"c3": "current_season", "c1": "all_seasons"}


def test_refit_interval_reuses_a_fit_and_refits_at_a_new_season() -> None:
    recorder = WindowRecorder()
    walk_forward(
        _two_seasons(),
        [Entrant("c3", recorder, "current_season")],
        forecast_config=ForecastConfig(),
        backtest_config=BacktestConfig(minimum_training_matches=3, refit_every_gameweeks=4),
    )
    # Five graded folds a season (GW4-8): fits at the first and fifth of each season's run.
    assert [season for season, _, _ in recorder.fits] == [PRIOR, PRIOR, SEASON, SEASON]


def test_paired_deltas_and_their_bootstrap_are_seeded_and_deterministic() -> None:
    history = make_history(gameweeks=8)
    first = _walk(history, Entrant("c3", RateFromFeatures()), Entrant("worse", Offset()))
    again = _walk(history, Entrant("c3", RateFromFeatures()), Entrant("worse", Offset()))
    assert first.paired == again.paired

    mae = first.paired["worse"]["mae"]
    assert mae.gameweeks == len(first.folds)
    assert mae.mean > 0 and mae.significant  # three points worse on every row, every gameweek

    assert bootstrap_ci([2.0] * 10, draws=200, seed=0) == (2.0, 2.0)
    assert bootstrap_ci([], draws=200, seed=0) == (0.0, 0.0)
    noisy = [0.3, -0.1, 0.2, 0.5, -0.4]
    assert bootstrap_ci(noisy, draws=200, seed=1) == bootstrap_ci(noisy, draws=200, seed=1)

    same = pd.DataFrame(
        {"season": "s", "gameweek": [1, 1, 2, 2], "a": [1.0, 2.0, 3.0, 4.0], "y": [1, 3, 2, 5]}
    )
    zero = paired_deltas(
        same.assign(b=same["a"]),
        champion="a",
        challenger="b",
        actual="y",
        top_n=1,
        group=("season", "gameweek"),
        draws=100,
        seed=0,
    )
    assert {d.mean for d in zero.values()} == {0.0}
    assert not any(d.significant for d in zero.values())


def _registry(tmp_path: Path) -> Any:
    return load_registry(
        _write(
            tmp_path / "strategies",
            _entry("c3", role="champion", published=True),
            _entry("probe", role="experiment", published=False),
            _entry(
                "frozen_x",
                forecaster={"type": "frozen", "model": "comp_A", "training_window": "all_seasons"},
            ),
            _entry("old", role="retired"),
        )
    )


def test_the_registry_accepts_an_unpublished_experiment_and_the_backtest_grades_it(
    tmp_path: Path, game_rules: GameRules
) -> None:
    graded, skipped = entrants(_registry(tmp_path), game_rules, Config())
    assert [e.id for e in graded] == ["c3", "probe"]
    assert skipped["old"] == "retired" and "frozen" in skipped["frozen_x"]


def _graded(tmp_path: Path) -> tuple[Graded, Any]:
    registered = _registry(tmp_path)
    result = _walk(
        make_history(gameweeks=8), Entrant("c3", RateFromFeatures()), Entrant("probe", Offset())
    )
    return Graded(result=result, skipped={"frozen_x": "frozen", "old": "retired"}), registered


def test_every_strategy_gets_one_stamped_record(tmp_path: Path) -> None:
    graded, registered = _graded(tmp_path)
    config = Config()
    moment = dt.datetime(2026, 10, 27, 16, 17, tzinfo=dt.UTC)
    records = experiment_records(
        graded, registered, config, run_id="20261027T161700Z-ab12cd34", recorded_at=moment
    )

    by_id = {r["strategy"]["id"]: r for r in records}
    assert list(by_id) == ["c3", "probe", "frozen_x", "old"]
    for strategy in registered:
        record = by_id[strategy.id]
        assert record["strategy"] == stamp(strategy, config)
        assert record["run_id"] == "20261027T161700Z-ab12cd34"
        assert record["recorded_at"] == moment.isoformat()
        assert len(record["config_digest"]) == 64
        assert record["data_window"] == {
            "seasons": [SEASON],
            "first": {"season": SEASON, "gameweek": graded.result.folds[0].gameweek},
            "last": {"season": SEASON, "gameweek": 8},
            "folds": len(graded.result.folds),
        }
    assert by_id["c3"]["verdict"] == graded.result.verdict()
    assert by_id["c3"]["paired_vs_champion"] is None
    assert by_id["probe"]["paired_vs_champion"]["mae"]["significant"] is True
    assert "verdict" not in by_id["probe"]
    assert by_id["frozen_x"]["not_graded"] == "frozen" and "metrics" not in by_id["frozen_x"]


def test_the_latest_verdict_is_for_the_current_digest_only(tmp_path: Path) -> None:
    graded, registered = _graded(tmp_path)
    config = Config()

    def run(run_id: str, day: int) -> list[dict[str, Any]]:
        moment = dt.datetime(2026, 10, day, tzinfo=dt.UTC)
        return experiment_records(graded, registered, config, run_id=run_id, recorded_at=moment)

    records = [*run("older", 20), *run("newer", 27)]
    current = stamp(registered[0], config)["digest"]
    latest = latest_verdict(records, "c3", current)
    assert latest is not None and latest["run_id"] == "newer"
    assert latest_verdict(records, "c3", "0" * 64) is None
    assert latest_verdict(records, "probe", stamp(registered[1], config)["digest"]) is None


def test_an_entrants_feature_override_reaches_its_own_rows() -> None:
    """A registry override on the features changes the rows the entrant is scored on, not just
    its fit; the champion's rows are untouched."""

    class Seen(RateFromFeatures):
        def __init__(self) -> None:
            super().__init__()
            self.columns: set[str] = set()

        def predict(self, features: pd.DataFrame, *, gameweek: int | None = None) -> pd.Series:
            self.columns |= set(features.columns)
            return super().predict(features, gameweek=gameweek)

    base = ForecastConfig()
    wider = base.features.model_copy(
        update={"rolling_statistics": (*base.features.rolling_statistics, "threat")}
    )
    plain, variant = Seen(), Seen()
    _walk(
        make_history(gameweeks=8),
        Entrant("c3", plain),
        Entrant("c3_f1", variant, features=wider),
    )
    assert "threat_per90_last6" in variant.columns
    assert "threat_per90_last6" not in plain.columns


def test_declared_experiments_load_against_the_shipped_registry() -> None:
    declared = load_declared(load_registry())
    assert {e.id for e in declared} == {"f1_card_rates", "f3_training_window"}
    assert all(e.baseline == "c3" for e in declared)


def test_a_declared_experiment_refuses_unknown_fields_and_unregistered_strategies(
    tmp_path: Path,
) -> None:
    registered = load_registry()
    text = (EXPERIMENTS_DIR / "f1_card_rates.yaml").read_text(encoding="utf-8")
    for bad in (text + "extra: 1\n", text.replace("variant: c3_f1", "variant: nobody")):
        (tmp_path / "f1_card_rates.yaml").write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="f1_card_rates"):
            load_declared(registered, tmp_path)


def test_every_rate_component_has_a_rolling_feature() -> None:
    """F1: M7 reads ``<column>_per90_last6``; a component without one gets the position prior."""
    config = ForecastConfig()
    xg = config.expected_goals
    names = rolling_feature_names(config.features)
    for component in RATE_COMPONENTS:
        column = xg.rate_sources.get(component, component) if xg.enabled else component
        assert f"{column}_per90_last6" in names, component


def _registry_backtest(game_rules: GameRules) -> tuple[pd.DataFrame, Config, ForecastInputs]:
    """The decision fixture's played gameweeks, its config graded over its own season, and its
    inputs with odds captured the day before each played gameweek's deadline."""
    inputs, _ = _snapshot(game_rules)
    history = inputs.player_gameweek
    assert history is not None
    fixtures, gameweeks = inputs.fixtures, inputs.gameweeks
    played = set(history["gameweek"])
    odds = pd.concat(
        [
            match_odds(
                fixtures[fixtures["gameweek"] == gw],
                game_rules.season,
                pd.Timestamp(deadline) - pd.Timedelta(days=1),
                home_goals=2.4,
            )
            for gw, deadline in zip(gameweeks["gameweek"], gameweeks["deadline_time"], strict=True)
            if gw in played
        ],
        ignore_index=True,
    )
    config = _forecast_config()
    window = {"training_seasons": (game_rules.season,), "minimum_training_matches": 2}
    # Two played gameweeks are too few rows for the boosted fits' stratified validation split.
    forecast = config.forecast.model_copy(
        update={
            name: getattr(config.forecast, name).model_copy(update={"early_stopping": False})
            for name in ("c1", "a")
        }
    )
    config = config.model_copy(
        update={"backtest": config.backtest.model_copy(update=window), "forecast": forecast}
    )
    return history, config, dataclasses.replace(inputs, match_odds=odds)


def test_the_real_registry_grades_a_odds_and_skips_what_it_cannot_build(
    game_rules: GameRules,
) -> None:
    """The standing backtest over the shipped registry: A_odds is graded on the silver odds, and
    without them it is skipped with the reason while every other strategy is still graded."""
    history, config, inputs = _registry_backtest(game_rules)
    one_fold = config.backtest.model_copy(update={"minimum_training_matches": 3})  # fast
    config = config.model_copy(update={"backtest": one_fold})
    graded = grade(history, strategies(), game_rules, config, inputs=inputs)
    assert "a_odds" in graded.result.strategies and "a_odds" not in graded.skipped
    rows = graded.result.predictions
    assert not rows[prediction_column("a_odds")].equals(rows[prediction_column("a")])

    bare, skipped = entrants(strategies(), game_rules, config)
    assert Table.TEAM_MATCH_EXPECTATION.value in skipped["a_odds"]
    assert {e.id for e in bare} == set(graded.result.strategies) - {"a_odds"}


class _Recording:
    """A fitted C1 that records the gameweek of every row it is asked to predict."""

    def __init__(self, inner: c1.Fitted, seen: list[int]) -> None:
        self.inner, self.seen = inner, seen

    @property
    def past(self) -> pd.DataFrame:
        return self.inner.past

    @property
    def b0(self) -> Any:
        return self.inner.b0

    def predict(self, upcoming: pd.DataFrame) -> pd.DataFrame:
        self.seen.extend(sorted(set(upcoming["gameweek"])))
        return self.inner.predict(upcoming)


def test_a_reused_fit_predicts_the_folds_own_gameweek(game_rules: GameRules) -> None:
    """With ``refit_every_gameweeks`` 2 a C1 fit is reused for the next fold, which must still be
    predicted as that fold's gameweek (its fixtures, its odds), not the refit's."""
    history, config, _ = _registry_backtest(game_rules)
    seen: list[int] = []
    fits: list[pd.Timestamp] = []

    class Spy(c1.C1Predictor):
        def _fit(self, past: pd.DataFrame, moment: pd.Timestamp) -> c1.Fitted:
            fits.append(moment)
            return _Recording(super()._fit(past, moment), seen)

    result = walk_forward(
        history,
        [Entrant("c1", Spy(config.forecast, game_rules))],
        forecast_config=config.forecast,
        backtest_config=config.backtest.model_copy(update={"refit_every_gameweeks": 2}),
        seasons=(game_rules.season,),
    )
    assert seen == [f.gameweek for f in result.folds]
    assert len(fits) < len(seen)  # a fit was reused
