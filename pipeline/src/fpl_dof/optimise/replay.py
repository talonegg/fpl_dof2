"""Replaying real historical deadlines through the decision engine. Repays D-18.

E4-S4a's acceptance criterion is that the simulation re-rank changes at least one chip
recommendation **in the backtest**. What E4 shipped instead was a constructed unit test in which
three Bench Boost timings tie exactly on expected points and the dial's percentile separates them.
That proves the mechanism is not inert. It says nothing about whether real chip decisions are ever
close enough for a percentile to move one.

This module answers that question with the real walk-forward machinery. For a bounded sample of
historical deadlines it:

1. refits the component models on matches that finished strictly before the deadline, through the
   same :func:`~fpl_dof.forecast.backtest.fold_rows` and
   :func:`~fpl_dof.forecast.backtest.training_rows` the walk-forward harness itself uses — a second
   assembly of the training set is a second chance to leak (Invariant 5);
2. forecasts every player for every gameweek of the horizon **against that gameweek's real
   fixture**, so the horizon actually varies rather than repeating one number;
3. solves the best legal squad at the deadline and treats it as the squad being planned from;
4. runs :func:`~fpl_dof.optimise.plan.build_plan` twice — re-rank on, re-rank off — and records
   what each recommended;
5. scores both chip weeks against **what actually happened**, using the real points those exact
   players went on to score.

Four things about it are assumptions rather than history, and they are stated here rather than
buried:

* **The chip windows are widened to the whole replayed season.** The archive publishes no chip
  windows for a past season, and imposing 2026/27's two-set structure on 2024/25 would be an
  anachronism. The chip *names* still come from the game's own chip table, never from a literal
  (Invariant 2); only the window is widened, and widening it can only give the enumerator more
  timings to choose between, which is the conservative direction for this experiment.
* **The squad is solved, not owned.** A replay has no manager. The best legal squad at the deadline
  is the least arbitrary starting point, and both arms of the comparison start from the identical
  squad, so the contrast is unaffected by the choice.
* **The fixture calendar is read back from results.** A real calendar is published weeks ahead and
  is genuinely knowable at the deadline, but the archive only records where each match *ended up*,
  so a fixture postponed after the deadline appears here in the gameweek it was eventually played
  rather than the one it was scheduled for. Both arms of the comparison see the identical calendar,
  so it cannot favour either; it is noted because it is the one input here that a live run would
  know more accurately than the replay does.
* **Club identity is reconstructed.** The archive carries ``opponent_team_id`` but no ``team_id``;
  a fixture has exactly two clubs, so a player's club is the one that is not his opponent. Without
  it there is no club cap, no fixture-varying forecast and no within-match correlation, and the
  experiment would degenerate into the tied case the unit test already covers.

The output is a finding, not an artefact. Nothing in the weekly pipeline reads it.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
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
from fpl_dof.forecast.features import TARGET, build_features
from fpl_dof.forecast.horizon import fixture_index_from_history, horizon_frame
from fpl_dof.forecast.models import ComponentModels, fit_components
from fpl_dof.frames import as_float, as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.optimise.plan import DecisionPlan, build_plan
from fpl_dof.optimise.squad import InfeasibleError, optimise_squad
from fpl_dof.rules.models import GameRules
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
    """What the re-ranked plan's chip week actually scored, from the real results."""

    actual_points_without: float | None
    seconds: float

    @property
    def changed(self) -> bool:
        return self.with_rerank != self.without_rerank

    @property
    def improved(self) -> bool | None:
        """Did the change land on the better week? ``None`` when nothing changed or nothing scored.

        Deliberately three-valued. Collapsing "did not change" and "changed for the worse" into one
        boolean is how a null result gets reported as a negative one.
        """
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
        """The headline, written so a null result reads as a finding rather than a failure."""
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
    """Fill in the club the archive does not carry.

    A fixture has exactly two clubs and every row names its *opponent*, so the pair of distinct
    opponent ids in a fixture is the pair of clubs, and a row's club is whichever of the two is not
    its own opponent. Fixtures that do not resolve to exactly two clubs are left null rather than
    guessed at — a wrong club silently breaks the three-per-club limit and the within-match
    correlation at once.
    """
    frame = history.copy()
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
    frame["team_id"] = pd.array(resolved, dtype="Int64")
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
    schedule = deadlines_for(frame)
    sample = sample_deadlines(frame, backtest_config)
    if not sample:
        raise ValueError(
            "no deadline in the history falls inside the configured replay window; widen "
            "backtest.chip_replay.first_gameweek/last_gameweek or supply more seasons"
        )

    warnings: list[str] = []
    folds: list[ReplayFold] = []
    wanted = {entry[2] for entry in sample}
    cache: dict[pd.Timestamp, pd.DataFrame] = {}

    for season, gameweek, deadline in schedule:
        # Every deadline contributes to the cache; only the sampled ones are planned. Skipping the
        # cache for unsampled deadlines would train the sampled ones on a fraction of the evidence.
        cache[deadline] = fold_rows(frame, season, gameweek, deadline, forecast_config)
        if deadline not in wanted:
            continue

        training = training_rows(cache, before=deadline)
        if training.empty:
            warnings.append(f"{season} GW{gameweek}: no training rows before the deadline")
            continue
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
        except InfeasibleError as exc:
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


# ---------------------------------------------------------------------- one deadline


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
    past = history[(history["season"] == season) & (history["kickoff_time"] < deadline)]
    horizon = tuple(range(gameweek, gameweek + decision.horizon.gameweeks))

    # Team strength is fitted on the raw per-gameweek rows rather than on ``training``: the
    # walk-forward training frame carries features and outcomes but no fixture or club, which is
    # why the harness's own report says opposition there is league-average. Reconstructed club ids
    # (see ``attach_team_ids``) are what make a real fixture-varying horizon possible here. Club
    # ids in the archive are season-local, so this must never reach across seasons.
    models = fit_components(training, _team_matches(past), forecast_config, rules)
    players = _forecast_frame(
        past,
        history,
        season=season,
        deadline=deadline,
        horizon=horizon,
        models=models,
        rules=rules,
        forecast_config=forecast_config,
    )
    state = _squad_at(players, rules, optimiser, replay, gameweek=gameweek)
    calendar = _widened_chip_windows(chips, history, season)
    fixtures = _fixture_frame(history, season, horizon)

    def run(*, simulate: bool) -> DecisionPlan:
        config = decision.model_copy(
            update={"simulation": decision.simulation.model_copy(update={"enabled": simulate})}
        )
        return build_plan(
            players=players,
            state=state,
            rules=rules,
            decision=config,
            optimiser=optimiser,
            fixtures=fixtures,
            chips=calendar,
            last_gameweek=int(history[history["season"] == season]["gameweek"].max()),
        )

    without = run(simulate=False)
    with_rerank = run(simulate=True)
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
        actual_points_with=_scored_chip_week(with_rerank, actuals, decision),
        actual_points_without=_scored_chip_week(without, actuals, decision),
        seconds=time.monotonic() - started,
    )


def _forecast_frame(
    past: pd.DataFrame,
    history: pd.DataFrame,
    *,
    season: str,
    deadline: pd.Timestamp,
    horizon: Sequence[int],
    models: ComponentModels,
    rules: GameRules,
    forecast_config: ForecastConfig,
) -> pd.DataFrame:
    """The player frame E4 reads, forecast against each horizon gameweek's real fixture.

    ``player_id`` is the archive's cross-season ``player_code``. The season-local element id is
    reassigned every year and would attribute one player's plan to whoever inherited his number.

    The scoring itself lives in :mod:`fpl_dof.forecast.horizon`, which the live pipeline also uses.
    It was written here first, for this experiment; keeping a private copy once the live path needed
    the same arithmetic would have been two implementations of one model drifting apart (D-25).
    """
    identity = (
        past.sort_values("kickoff_time")
        .groupby("player_code")
        .last()[["web_name", "position", "team_id", "price"]]
    )
    # A replay has no manager, no news and no ownership, so these are stated once as the assumptions
    # they are rather than smuggled in as data. Both arms of the comparison see them identically.
    identity = identity.assign(
        player_id=identity.index,
        status="a",
        chance_of_playing_next_round=None,
        news="",
        selected_by_percent=0.0,
        start_probability=1.0,
        start_floor=0.0,
        confidence="medium",
    )
    features = build_features(
        past,
        as_of=deadline,
        config=forecast_config.features,
        positions=past[["player_code", "position"]],
    )
    if features.empty:
        raise InfeasibleError(f"no features could be built at {deadline}")

    frame = horizon_frame(
        features,
        identity=identity,
        horizon=horizon,
        fixtures=fixture_index_from_history(history, season, horizon),
        models=models,
        rules=rules,
        config=forecast_config,
    )
    if frame.empty:
        raise InfeasibleError(f"no player could be forecast at {deadline}")
    return frame


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
    """The game's own chip names, over the replayed season's whole gameweek range.

    The names come from the chip table and never from a literal (Invariant 2). Only the window is
    widened, and only because the archive publishes none for a past season — see the module
    docstring.
    """
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
    """The squad the replay plans from: the best legal one at this deadline.

    Both arms of the comparison start from it, so the choice cannot favour either.
    """
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


# ---------------------------------------------------------------------- scoring


def _actual_points(history: pd.DataFrame, season: str) -> dict[tuple[int, int], float]:
    """(gameweek, player_code) -> the points that player actually scored. The ground truth."""
    window = history[history["season"] == season]
    grouped = (
        window.groupby(["gameweek", "player_code"])[TARGET].sum().reset_index(name="actual_points")
    )
    return {
        (as_int(row.gameweek), as_int(row.player_code)): as_float(row.actual_points)
        for row in grouped.itertuples()
    }


def _scored_chip_week(
    plan: DecisionPlan,
    actuals: Mapping[tuple[int, int], float],
    decision: DecisionConfig,
) -> float | None:
    """What the recommended chip week actually scored, with that week's real fielded squad.

    ``None`` when the plan recommends no chip, which is a different answer from zero and must not
    be averaged with one.
    """
    assignments = plan.chips_recommended
    if not assignments:
        return None
    gameweek, chip = assignments[0]
    week = next((item for item in plan.recommended.plan.weeks if item.gameweek == gameweek), None)
    if week is None:
        return None

    multiplier = decision.chips.captain_multiplier_by_chip.get(chip, 2)
    starting = set(week.starting)
    total = 0.0
    for player_id in week.fielded:
        points = actuals.get((gameweek, player_id), 0.0)
        if player_id == week.captain_id:
            total += points * multiplier
        elif player_id in starting or chip == "bboost":
            total += points
    return round(total, 2)


def _team_matches(training: pd.DataFrame) -> pd.DataFrame:
    """Per-team, per-fixture goals, for the strength model. Mirrors the walk-forward harness."""
    needed = {"team_id", "fixture_id", "goals_scored", "goals_conceded", "kickoff_time"}
    if training.empty or not needed <= set(training.columns):
        return pd.DataFrame(
            columns=["team_id", "fixture_id", "goals_for", "goals_against", "kickoff_time"]
        )
    played = training[training["minutes"] > 0]
    if played.empty:
        return pd.DataFrame(
            columns=["team_id", "fixture_id", "goals_for", "goals_against", "kickoff_time"]
        )
    grouped = played.groupby(["team_id", "fixture_id"], dropna=True).agg(
        goals_for=("goals_scored", "sum"),
        goals_against=("goals_conceded", "max"),
        kickoff_time=("kickoff_time", "min"),
    )
    return grouped.reset_index()


__all__ = [
    "ReplayFold",
    "ReplayResult",
    "attach_team_ids",
    "replay_chip_decisions",
    "sample_deadlines",
]
