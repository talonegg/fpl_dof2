"""Replaying real historical deadlines through the decision engine. Repays D-18.

An evaluation that fits models, so it lives in the model factory (MOD-04): the decision engine in
``core`` imports nothing from here. Uses :func:`~fpl_dof.forecast.fit.fit_as_of` for consistent
model fitting.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fpl_dof.config.models import (
    BacktestConfig,
    ChipReplayConfig,
    DecisionConfig,
    ForecastConfig,
    OptimiserConfig,
)
from fpl_dof.forecast.backtest import deadlines_for, fold_rows, training_rows
from fpl_dof.forecast.fit import ColdStartError, fit_as_of
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.plan import DecisionPlan, build_plan
from fpl_dof.optimise.squad import InfeasibleError, optimise_squad
from fpl_dof.rules.models import GameRules
from fpl_dof.rules.realised import Lineup, PlayerPerformance, performances, score_lineup
from fpl_dof.squad.state import HeldPlayer, Provenance, SquadState

log = get_logger(__name__)

ChipAssignments = tuple[tuple[int, str], ...]


def _missing(value: Any) -> bool:
    """Null-safe, and typed. ``pd.isna`` returns an array for a sequence, which is not a truth."""
    return bool(pd.isna(value))


@dataclass(frozen=True, slots=True)
class ReplayFold:
    """One historical deadline, planned twice."""

    season: str
    gameweek: int
    deadline: pd.Timestamp
    training_rows: int
    with_rerank: ChipAssignments
    without_rerank: ChipAssignments
    with_label: str
    without_label: str
    actual_points_with: float | None
    actual_points_without: float | None
    seconds: float

    @property
    def changed(self) -> bool:
        return self.with_rerank != self.without_rerank

    @property
    def improved(self) -> bool | None:
        if not self.changed:
            return None
        if self.actual_points_with is None or self.actual_points_without is None:
            return None
        return self.actual_points_with > self.actual_points_without

    def as_dict(self) -> dict[str, object]:
        return {
            "season": self.season,
            "gameweek": self.gameweek,
            "deadline": str(self.deadline),
            "training_rows": self.training_rows,
            "with_rerank": [list(item) for item in self.with_rerank],
            "without_rerank": [list(item) for item in self.without_rerank],
            "with_label": self.with_label,
            "without_label": self.without_label,
            "actual_points_with": self.actual_points_with,
            "actual_points_without": self.actual_points_without,
            "changed": self.changed,
            "improved": self.improved,
            "seconds": round(self.seconds, 2),
        }


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """What the sample found, and the verdict it supports."""

    folds: tuple[ReplayFold, ...]
    seconds: float
    warnings: tuple[str, ...] = field(default=())

    @property
    def changed(self) -> tuple[ReplayFold, ...]:
        return tuple(fold for fold in self.folds if fold.changed)

    def verdict(self) -> str:
        if not self.folds:
            return (
                "No historical deadline could be replayed, so nothing was measured. That is a "
                "different situation from measuring a re-rank that does nothing."
            )
        changed = self.changed
        if not changed:
            return (
                f"Across {len(self.folds)} real historical deadlines the simulation re-rank did "
                "not change a single chip recommendation. The mechanism is not inert — a "
                "constructed tie flips it — but real chip timings in this sample were not close "
                "enough on expected points for a percentile to overturn one. E4-S4a's acceptance "
                "criterion is therefore still unmet on real data."
            )
        better = sum(1 for fold in changed if fold.improved is True)
        worse = sum(1 for fold in changed if fold.improved is False)
        return (
            f"The re-rank changed the chip recommendation at {len(changed)} of "
            f"{len(self.folds)} real historical deadlines. Scored against what actually happened, "
            f"{better} of those changes moved the chip to the better gameweek and {worse} to the "
            "worse one. The sample is far too small to call that skill; the criterion it does "
            "meet is that the re-rank moves real decisions, not only constructed ties."
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "deadlines": len(self.folds),
            "changed": len(self.changed),
            "seconds": round(self.seconds, 1),
            "verdict": self.verdict(),
            "folds": [fold.as_dict() for fold in self.folds],
            "warnings": list(self.warnings),
        }


def attach_team_ids(history: pd.DataFrame) -> pd.DataFrame:
    """Fill in any club the source did not resolve — and only those."""
    frame = history.copy()
    if "team_id" not in frame.columns:
        frame["team_id"] = pd.array([None] * len(frame), dtype="Int64")
    stated = frame["team_id"]
    if stated.notna().all() and len(frame):
        return frame
    usable = frame.dropna(subset=["fixture_id", "opponent_team_id"])
    pairs: dict[tuple[str, int], set[int]] = {}
    for row in usable.itertuples():
        key = (str(row.season), as_int(row.fixture_id))
        pairs.setdefault(key, set()).add(as_int(row.opponent_team_id))

    resolved: list[int | None] = []
    for row in frame.itertuples():
        if _missing(row.fixture_id) or _missing(row.opponent_team_id):
            resolved.append(None)
            continue
        clubs = pairs.get((str(row.season), as_int(row.fixture_id)), set())
        opponent = as_int(row.opponent_team_id)
        others = clubs - {opponent}
        resolved.append(others.pop() if len(others) == 1 else None)
    reconstructed = pd.array(resolved, dtype="Int64")
    frame["team_id"] = stated.combine_first(pd.Series(reconstructed, index=frame.index))
    frame["team_id"] = frame["team_id"].astype("Int64")
    return frame


def sample_deadlines(
    history: pd.DataFrame, config: BacktestConfig
) -> list[tuple[str, int, pd.Timestamp]]:
    """The bounded set of deadlines to replay, and the reason it is bounded is in the config."""
    replay = config.chip_replay
    eligible = [
        entry
        for entry in deadlines_for(history)
        if replay.first_gameweek <= entry[1] <= replay.last_gameweek
    ]
    strided = eligible[:: replay.deadline_stride]
    return strided[: replay.max_deadlines]


def replay_chip_decisions(
    history: pd.DataFrame,
    *,
    rules: GameRules,
    chips: pd.DataFrame,
    forecast_config: ForecastConfig,
    backtest_config: BacktestConfig,
    decision: DecisionConfig,
    optimiser: OptimiserConfig,
) -> ReplayResult:
    """Plan a sample of real historical deadlines twice, with the re-rank on and off."""
    if history.empty:
        raise ValueError("cannot replay an empty history")

    started = time.monotonic()
    frame = attach_team_ids(history)
    warnings: list[str] = []
    folds: list[ReplayFold] = []

    for season, gameweek, deadline, training in _sampled(
        frame, backtest_config, forecast_config, warnings
    ):
        try:
            fold = _replay_one(
                frame,
                season=season,
                gameweek=gameweek,
                deadline=deadline,
                training=training,
                rules=rules,
                chips=chips,
                forecast_config=forecast_config,
                replay=backtest_config.chip_replay,
                decision=decision,
                optimiser=optimiser,
            )
        except (InfeasibleError, ColdStartError) as exc:
            warnings.append(f"{season} GW{gameweek}: no plan could be built ({exc})")
            continue
        folds.append(fold)
        log.info(
            "replay.fold",
            extra={
                "season": season,
                "gameweek": gameweek,
                "with_rerank": list(fold.with_rerank),
                "without_rerank": list(fold.without_rerank),
                "changed": fold.changed,
            },
        )

    return ReplayResult(
        folds=tuple(folds),
        seconds=time.monotonic() - started,
        warnings=tuple(warnings),
    )


def replay_chip_timing(
    history: pd.DataFrame,
    *,
    rules: GameRules,
    chips: pd.DataFrame,
    forecast_config: ForecastConfig,
    backtest_config: BacktestConfig,
    decision: DecisionConfig,
    optimiser: OptimiserConfig,
) -> dict[str, Any]:
    """D-21 as a declared experiment (EXP-02, ``config/experiments/d21_chip_timing.yaml``).

    Every sampled deadline is fitted once and planned at every dial three ways: re-rank off, on
    with the shipped discounted percentile, and on with the discount taken out of the percentile.
    The finding is how often each arm puts its first chip on the first horizon gameweek, and what
    that chip week actually scored.
    """
    if history.empty:
        raise ValueError("cannot replay an empty history")
    started = time.monotonic()
    frame = attach_team_ids(history)
    dials = tuple(decision.simulation.percentile_by_dial)
    arms = {
        f"{dial}/{name}": _arm(decision, simulate=simulate, dial=dial, undiscounted=undiscounted)
        for dial in dials
        for name, simulate, undiscounted in (
            ("off", False, False),
            ("discounted", True, False),
            ("undiscounted", True, True),
        )
    }
    warnings: list[str] = []
    folds: list[dict[str, Any]] = []
    for season, gameweek, deadline, training in _sampled(
        frame, backtest_config, forecast_config, warnings
    ):
        try:
            plan = _planner(
                frame,
                season=season,
                gameweek=gameweek,
                deadline=deadline,
                training=training,
                rules=rules,
                chips=chips,
                forecast_config=forecast_config,
                replay=backtest_config.chip_replay,
                decision=decision,
                optimiser=optimiser,
            )
            plans = {key: plan(config) for key, config in arms.items()}
        except (InfeasibleError, ColdStartError) as exc:
            warnings.append(f"{season} GW{gameweek}: no plan could be built ({exc})")
            continue
        actuals = _actual_points(frame, season)
        folds.append(
            {
                "season": season,
                "gameweek": gameweek,
                "arms": {
                    key: {
                        "chips": [list(item) for item in made.chips_recommended],
                        "offset": (
                            made.chips_recommended[0][0] - gameweek
                            if made.chips_recommended
                            else None
                        ),
                        "actual_points": _scored_chip_week(made, actuals, rules),
                    }
                    for key, made in plans.items()
                },
            }
        )
        log.info("replay.timing_fold", extra={"season": season, "gameweek": gameweek})
    return timing_summary(folds, dials, time.monotonic() - started, warnings)


def timing_summary(
    folds: Sequence[Mapping[str, Any]],
    dials: Sequence[str],
    seconds: float,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Per arm, how often the first chip lands on the first horizon gameweek, and the verdict.

    The share of the re-rank's excess front-loading that removing the discount takes away, pooled
    over the dials, is the measure of whether the discount is D-21's mechanism: near one, it is;
    near zero, it is not.
    """
    summary: dict[str, dict[str, Any]] = {}
    for key in (f"{d}/{n}" for d in dials for n in ("off", "discounted", "undiscounted")):
        rows = [fold["arms"][key] for fold in folds if key in fold["arms"]]
        scored = [row["actual_points"] for row in rows if row["actual_points"] is not None]
        summary[key] = {
            "front_loaded": sum(1 for row in rows if row["offset"] == 0),
            "offsets": [row["offset"] for row in rows],
            "mean_actual_points": round(sum(scored) / len(scored), 2) if scored else None,
        }
    excess = sum(
        summary[f"{d}/discounted"]["front_loaded"] - summary[f"{d}/off"]["front_loaded"]
        for d in dials
    )
    removed = sum(
        summary[f"{d}/discounted"]["front_loaded"] - summary[f"{d}/undiscounted"]["front_loaded"]
        for d in dials
    )
    share = removed / excess if excess > 0 else None
    lines = [
        f"{d}: first chip on the first horizon gameweek at "
        f"{summary[f'{d}/off']['front_loaded']}/{len(folds)} with the re-rank off, "
        f"{summary[f'{d}/discounted']['front_loaded']}/{len(folds)} on as shipped, "
        f"{summary[f'{d}/undiscounted']['front_loaded']}/{len(folds)} on without the discount"
        for d in dials
    ]
    if not folds:
        verdict = "No deadline could be replayed, so nothing was measured."
    elif share is None:
        verdict = (
            "The re-rank did not front-load chips in this sample; there is nothing to explain."
        )
    else:
        verdict = (
            f"Removing the discount from the percentile takes away {share:.0%} of the re-rank's "
            "excess front-loading, pooled over the dials."
        )
    return {
        "experiment": "d21_chip_timing",
        "deadlines": len(folds),
        "seconds": round(seconds, 1),
        "arms": summary,
        "discount_share_of_front_loading": None if share is None else round(share, 3),
        "verdict": "; ".join(lines) + ". " + verdict,
        "folds": list(folds),
        "warnings": list(warnings),
    }


def _sampled(
    frame: pd.DataFrame,
    backtest_config: BacktestConfig,
    forecast_config: ForecastConfig,
    warnings: list[str],
) -> Iterator[tuple[str, int, pd.Timestamp, pd.DataFrame]]:
    """Each sampled deadline with its training rows, the walk-forward harness's own (Inv. 5)."""
    sample = sample_deadlines(frame, backtest_config)
    if not sample:
        raise ValueError(
            "no deadline in the history falls inside the configured replay window; widen "
            "backtest.chip_replay.first_gameweek/last_gameweek or supply more seasons"
        )
    wanted = {entry[2] for entry in sample}
    cache: dict[pd.Timestamp, pd.DataFrame] = {}
    for season, gameweek, deadline in deadlines_for(frame):
        cache[deadline] = fold_rows(frame, season, gameweek, deadline, forecast_config)
        if deadline not in wanted:
            continue
        training = training_rows(cache, before=deadline)
        if training.empty:
            warnings.append(f"{season} GW{gameweek}: no training rows before the deadline")
            continue
        yield season, gameweek, deadline, training


Planner = Callable[[DecisionConfig], DecisionPlan]


def _planner(
    history: pd.DataFrame,
    *,
    season: str,
    gameweek: int,
    deadline: pd.Timestamp,
    training: pd.DataFrame,
    rules: GameRules,
    chips: pd.DataFrame,
    forecast_config: ForecastConfig,
    replay: ChipReplayConfig,
    decision: DecisionConfig,
    optimiser: OptimiserConfig,
) -> Planner:
    """Fit once at this deadline; the returned function plans it under any decision config."""
    horizon = tuple(range(gameweek, gameweek + decision.horizon.gameweeks))
    fitted = fit_as_of(history, deadline, forecast_config, rules, training=training, season=season)
    players = fitted.predict(horizon, history=history, season=season)
    state = _squad_at(players, rules, optimiser, replay, gameweek=gameweek)
    calendar = _widened_chip_windows(chips, history, season)
    fixtures = _fixture_frame(history, season, horizon)
    last_gameweek = int(history[history["season"] == season]["gameweek"].max())

    def plan(config: DecisionConfig) -> DecisionPlan:
        return build_plan(
            players=players,
            state=state,
            rules=rules,
            decision=config,
            optimiser=optimiser,
            fixtures=fixtures,
            chips=calendar,
            last_gameweek=last_gameweek,
        )

    return plan


def _arm(
    decision: DecisionConfig, *, simulate: bool, dial: str | None = None, undiscounted: bool = False
) -> DecisionConfig:
    simulation = decision.simulation.model_copy(
        update={"enabled": simulate, "undiscounted_percentile": undiscounted}
    )
    update: dict[str, Any] = {"simulation": simulation}
    if dial is not None:
        update["risk"] = decision.risk.model_copy(update={"dial": dial})
    return decision.model_copy(update=update)


def _replay_one(
    history: pd.DataFrame,
    *,
    season: str,
    gameweek: int,
    deadline: pd.Timestamp,
    training: pd.DataFrame,
    rules: GameRules,
    chips: pd.DataFrame,
    forecast_config: ForecastConfig,
    replay: ChipReplayConfig,
    decision: DecisionConfig,
    optimiser: OptimiserConfig,
) -> ReplayFold:
    started = time.monotonic()
    plan = _planner(
        history,
        season=season,
        gameweek=gameweek,
        deadline=deadline,
        training=training,
        rules=rules,
        chips=chips,
        forecast_config=forecast_config,
        replay=replay,
        decision=decision,
        optimiser=optimiser,
    )
    without = plan(_arm(decision, simulate=False))
    with_rerank = plan(_arm(decision, simulate=True))
    actuals = _actual_points(history, season)

    return ReplayFold(
        season=season,
        gameweek=gameweek,
        deadline=deadline,
        training_rows=len(training),
        with_rerank=with_rerank.chips_recommended,
        without_rerank=without.chips_recommended,
        with_label=with_rerank.recommended.label,
        without_label=without.recommended.label,
        actual_points_with=_scored_chip_week(with_rerank, actuals, rules),
        actual_points_without=_scored_chip_week(without, actuals, rules),
        seconds=time.monotonic() - started,
    )


def _fixture_frame(history: pd.DataFrame, season: str, horizon: Sequence[int]) -> pd.DataFrame:
    """The fixture table the chip enumerator reads, so blanks and doubles are real ones."""
    window = history[(history["season"] == season) & (history["gameweek"].isin(list(horizon)))]
    rows = (
        window.dropna(subset=["team_id", "opponent_team_id", "fixture_id"])
        .groupby(["fixture_id", "gameweek", "team_id", "opponent_team_id", "was_home"])
        .size()
        .reset_index()
    )
    home = rows[rows["was_home"]]
    return pd.DataFrame(
        {
            "fixture_id": home["fixture_id"].astype(int),
            "gameweek": home["gameweek"].astype(int),
            "home_team_id": home["team_id"].astype(int),
            "away_team_id": home["opponent_team_id"].astype(int),
            "home_difficulty": 3,
            "away_difficulty": 3,
            "finished": False,
            "kickoff_time": pd.Timestamp("2000-01-01", tz="UTC"),
        }
    )


def _widened_chip_windows(chips: pd.DataFrame, history: pd.DataFrame, season: str) -> pd.DataFrame:
    """The game's own chip names, over the replayed season's whole gameweek range."""
    played = history[history["season"] == season]["gameweek"].dropna()
    first = as_int(played.min()) if not played.empty else 1
    last = as_int(played.max()) if not played.empty else 38
    kinds = {
        str(row.name_): str(row.chip_type)
        for row in chips.rename(columns={"name": "name_"}).itertuples()
    }
    return pd.DataFrame(
        [
            {
                "chip_id": index + 1,
                "name": name,
                "chip_type": kind,
                "start_event": first,
                "stop_event": last,
            }
            for index, (name, kind) in enumerate(sorted(kinds.items()))
        ]
    )


def _squad_at(
    players: pd.DataFrame,
    rules: GameRules,
    optimiser: OptimiserConfig,
    replay: ChipReplayConfig,
    *,
    gameweek: int,
) -> SquadState:
    """The squad the replay plans from: the best legal one at this deadline."""
    squad, _report = optimise_squad(players, rules, optimiser)
    return SquadState(
        entry_id=None,
        gameweek=gameweek,
        players=tuple(
            HeldPlayer(
                player_id=member.player_id,
                position=member.position,
                team_id=member.team_id,
                current_price=member.price,
                purchase_price=member.price,
            )
            for member in squad.players
        ),
        bank=replay.bank,
        free_transfers=replay.free_transfers,
        chips_used=(),
        provenance=Provenance.DECLARED,
    )


def _actual_points(history: pd.DataFrame, season: str) -> dict[int, dict[int, PlayerPerformance]]:
    """gameweek -> player_code -> what that player actually did. The ground truth."""
    window = history[history["season"] == season]
    return {
        as_int(gameweek): performances(rows, key="player_code")
        for gameweek, rows in window.groupby("gameweek")
    }


def _scored_chip_week(
    plan: DecisionPlan,
    actuals: Mapping[int, Mapping[int, PlayerPerformance]],
    rules: GameRules,
) -> float | None:
    """What the recommended chip week actually scored, with that week's real fielded squad."""
    assignments = plan.chips_recommended
    if not assignments:
        return None
    gameweek, chip = assignments[0]
    week = next((item for item in plan.recommended.plan.weeks if item.gameweek == gameweek), None)
    if week is None:
        return None

    outfield_bench = set(week.bench_order)
    lineup = Lineup(
        starting=week.starting,
        bench_order=week.bench_order,
        bench_gkp=next(
            (i for i in week.fielded if i not in week.starting and i not in outfield_bench), None
        ),
        captain=week.captain_id,
        vice_captain=week.vice_captain_id,
        chip=chip,
    )
    return float(score_lineup(lineup, actuals.get(gameweek, {}), rules).points_before_hits)


__all__ = [
    "ReplayFold",
    "ReplayResult",
    "attach_team_ids",
    "replay_chip_decisions",
    "replay_chip_timing",
    "sample_deadlines",
    "timing_summary",
]
