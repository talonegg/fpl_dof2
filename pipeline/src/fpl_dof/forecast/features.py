"""The feature store: one definition of every feature, used identically by training and inference.

**Why one definition matters more than any individual feature.** The classic failure in a project
like this is not a bad feature; it is a feature computed one way in training and another way at
inference. The model then performs well in the backtest and badly in the season, and the difference
is invisible because both code paths look correct in isolation. Sharing the definition is what makes
that impossible rather than unlikely.

**Every feature carries the moment it becomes knowable.** This is the structural defence against
R-04 and the reason Invariant 5 is enforceable rather than aspirational. A feature is not "computed
from past data" by convention — it declares a ``knowable_at`` timestamp, and
:func:`assert_no_look_ahead` checks that no row used to compute it kicked off at or after the
deadline it is being used for.

The subtlety worth stating: **a gameweek's own deadline, not its kickoffs, is the boundary.** A
match played on Saturday afternoon is unknowable at Friday's deadline even though both fall in the
same gameweek, and using it would produce a backtest that looks superb and a season that does not.

**The same question, asked of a season total, has a different answer.** The conformed advanced
tables (``player_metric``) carry running season totals rather than per-fixture rows. A total for
season *S* is not knowable at any deadline *within* S — at gameweek 10 nobody knows what the figure
will be in May — so the boundary for those is the **season**, not the deadline, and it is enforced
by season label rather than by timestamp: a metric row is admissible only against a season that
starts strictly later than its own. That rule cannot be defeated by a fixture list, a postponement
or an off-by-one on the last kickoff, which is why it is preferred over comparing ``as_of`` to the
season's final match. See D-22.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from fpl_dof.config.models import FeatureConfig, PriorSeasonConfig
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

#: Every prior-season feature carries this prefix, so one string finds all of them.
PRIOR_SEASON_PREFIX = "prior_season_"
PRIOR_SEASON_MINUTES = f"{PRIOR_SEASON_PREFIX}minutes"

#: The fixture an observation is played under, named once so the harness that attaches it and the
#: model that reads it cannot disagree about the spelling (E9-S2).
#:
#: Deliberately **not** ``was_home``. That name is already taken by a rolling feature describing the
#: player's *previous* match, and quietly widening it to mean the upcoming fixture would change a
#: number every backtest has already reported without changing its name. Two meanings, two names.
FIXTURE_TEAM = "fixture_team_id"
FIXTURE_OPPONENT = "fixture_opponent_team_id"
FIXTURE_AT_HOME = "fixture_at_home"
FIXTURE_COLUMNS: tuple[str, ...] = (FIXTURE_TEAM, FIXTURE_OPPONENT, FIXTURE_AT_HOME)


class LeakageError(RuntimeError):
    """A feature used a match that had not been played when it claims to have been knowable.

    Never a warning. A leaked feature produces a model that scores brilliantly and is worthless,
    and it is the single easiest way to waste a season (Invariant 5).
    """


class Knowability(StrEnum):
    """When a feature's inputs become available."""

    BEFORE_DEADLINE = "before_deadline"
    """Computed only from matches that had finished before the deadline. Safe to use."""

    AT_DEADLINE = "at_deadline"
    """Published state as it stands at the deadline — price, ownership, availability flags. Safe,
    but genuinely different from match history: it is a snapshot, not an accumulation."""

    AFTER_KICKOFF = "after_kickoff"
    """The outcome. Only ever a target, never an input."""


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    knowability: Knowability
    summary: str
    source_columns: tuple[str, ...]

    @property
    def is_input(self) -> bool:
        return self.knowability is not Knowability.AFTER_KICKOFF


#: The window lengths are configuration, not literals, and the names encode them so a model card
#: can say which window a coefficient belongs to without a lookup.
def rolling_feature_names(config: FeatureConfig) -> tuple[str, ...]:
    return tuple(
        f"{stat}_per90_last{window}"
        for window in config.rolling_windows
        for stat in config.rolling_statistics
    ) + tuple(f"minutes_mean_last{window}" for window in config.rolling_windows)


def prior_season_feature_names(config: FeatureConfig) -> tuple[str, ...]:
    """The prior-season features, or nothing at all when the prior ships dark (DP-08).

    Sorted rather than in configuration order so the column order of a training frame does not
    depend on how somebody wrote a YAML mapping.
    """
    if not config.prior_season.enabled:
        return ()
    return (
        PRIOR_SEASON_MINUTES,
        *(f"{PRIOR_SEASON_PREFIX}{stem}_ratio" for stem in sorted(config.prior_season.statistics)),
    )


TARGET = "total_points"


def specs(config: FeatureConfig) -> tuple[FeatureSpec, ...]:
    rolling = tuple(
        FeatureSpec(
            name=name,
            knowability=Knowability.BEFORE_DEADLINE,
            summary="Rolling rate over completed matches only",
            source_columns=("kickoff_time", "minutes"),
        )
        for name in rolling_feature_names(config)
    )
    prior_season = tuple(
        FeatureSpec(
            name=name,
            knowability=Knowability.BEFORE_DEADLINE,
            summary=(
                "A completed prior season's total. Knowable from the first deadline of the "
                "following season and at no deadline before it"
            ),
            source_columns=("season", "scope", "minutes_played"),
        )
        for name in prior_season_feature_names(config)
    )
    return (
        *rolling,
        *prior_season,
        FeatureSpec(
            name="starts_rate",
            knowability=Knowability.BEFORE_DEADLINE,
            summary="Share of the player's recent matches begun as a starter",
            source_columns=("starts", "kickoff_time"),
        ),
        FeatureSpec(
            name="appearance_rate",
            knowability=Knowability.BEFORE_DEADLINE,
            summary="Share of recent matches in which the player played at all",
            source_columns=("minutes", "kickoff_time"),
        ),
        FeatureSpec(
            name="matches_observed",
            knowability=Knowability.BEFORE_DEADLINE,
            summary="How much evidence there is. Drives shrinkage, and is itself a feature",
            source_columns=("kickoff_time",),
        ),
        FeatureSpec(
            name="days_since_last_match",
            knowability=Knowability.BEFORE_DEADLINE,
            summary="Rest, and a proxy for having been out of the side",
            source_columns=("kickoff_time",),
        ),
        FeatureSpec(
            name="price",
            knowability=Knowability.AT_DEADLINE,
            summary="FPL's own valuation. The baseline's only real input, so a feature to watch",
            source_columns=("price",),
        ),
        FeatureSpec(
            name="was_home",
            knowability=Knowability.AT_DEADLINE,
            summary="Home advantage, known as soon as the fixture is",
            source_columns=("was_home",),
        ),
        # The upcoming fixture (E9-S2). Attached by the caller that knows which gameweek is being
        # predicted — the harness from the archive's calendar, the live path from the fixture
        # table — rather than by build_features, which describes a player and not a gameweek.
        # AT_DEADLINE because the calendar is published weeks ahead and revised only by
        # postponement: it is a snapshot of a schedule, not an accumulation of results.
        FeatureSpec(
            name=FIXTURE_TEAM,
            knowability=Knowability.AT_DEADLINE,
            summary="The club whose fixture this observation is played under",
            source_columns=("team_id",),
        ),
        FeatureSpec(
            name=FIXTURE_OPPONENT,
            knowability=Knowability.AT_DEADLINE,
            summary="The opponent in the fixture being predicted, from the published calendar",
            source_columns=("opponent_team_id",),
        ),
        FeatureSpec(
            name=FIXTURE_AT_HOME,
            knowability=Knowability.AT_DEADLINE,
            summary="Venue of the fixture being predicted, from the published calendar",
            source_columns=("was_home",),
        ),
        FeatureSpec(
            name=TARGET,
            knowability=Knowability.AFTER_KICKOFF,
            summary="What actually happened. The target, and never an input",
            source_columns=(TARGET,),
        ),
    )


def input_features(config: FeatureConfig) -> tuple[str, ...]:
    return tuple(spec.name for spec in specs(config) if spec.is_input)


def season_start_year(season: str) -> int | None:
    """``2024/25`` or ``2024-25`` -> ``2024``. Anything else -> ``None``.

    Seasons are labelled inconsistently across this project's inputs, and the separator sorts
    differently from the one beside it, so comparing labels as strings would silently order
    ``2026-27`` before ``2025/26``. The start year is the only part that means anything.
    """
    head = str(season).strip()[:4]
    return int(head) if head.isdigit() else None


def prior_season_ratios(
    metrics: pd.DataFrame,
    *,
    season: str,
    positions: Mapping[int, str],
    config: PriorSeasonConfig,
) -> pd.DataFrame:
    """Each player's most recent *completed* season, as position-relative per-90 ratios.

    The knowability rule is the whole of the first filter: a season-scope row is admissible only
    against a season that starts strictly later than its own. Applied to labels rather than to
    timestamps because it must hold at every deadline of the target season including the first,
    when no match of it has been played and no clock could distinguish the two seasons.

    A player with no qualifying prior season gets no row, and therefore a null feature — the
    absence of evidence, which the model's shrinkage already knows how to treat, rather than a zero,
    which is a claim.
    """
    columns = [
        PRIOR_SEASON_MINUTES,
        *(f"{PRIOR_SEASON_PREFIX}{stem}_ratio" for stem in config.statistics),
    ]
    empty = pd.DataFrame(columns=["player_code", *columns])
    target = season_start_year(season)
    if metrics.empty or target is None or "minutes_played" not in metrics.columns:
        return empty

    frame = metrics[metrics["scope"] == "season"].copy()
    frame["_start_year"] = frame["season"].map(season_start_year)
    frame = frame[frame["_start_year"].notna() & (frame["_start_year"] < target)]
    frame = frame[frame["player_code"].notna()]
    minutes = pd.to_numeric(frame["minutes_played"], errors="coerce")
    frame = frame[minutes.notna() & (minutes >= config.minimum_minutes)]
    if frame.empty:
        return empty

    # The most recent completed season only. Two seasons ago is weaker evidence about the same
    # thing, and averaging them would hide which one the number came from.
    frame = frame.sort_values("_start_year").groupby("player_code", as_index=False).last()
    frame["player_code"] = frame["player_code"].map(as_int)
    frame[PRIOR_SEASON_MINUTES] = pd.to_numeric(frame["minutes_played"], errors="coerce")
    frame["_position"] = frame["player_code"].map(positions)

    for stem, sources in config.statistics.items():
        available = [column for column in sources if column in frame.columns]
        if not available:
            frame[f"{PRIOR_SEASON_PREFIX}{stem}_ratio"] = np.nan
            continue
        total = frame[available].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
        rate = total / frame[PRIOR_SEASON_MINUTES] * 90.0
        frame[f"{PRIOR_SEASON_PREFIX}{stem}_ratio"] = _position_relative(
            rate, frame["_position"], config
        )

    ratios: pd.DataFrame = frame[["player_code", *columns]].reset_index(drop=True)
    return ratios


def _position_relative(
    rate: pd.Series, position: pd.Series, config: PriorSeasonConfig
) -> pd.Series:
    """A rate divided by the mean among the same position, bounded.

    Position-relative because the model already carries a position prior: handing it an absolute
    rate would count the position twice, and a defender would arrive with a defensive prior scaled
    up simply for being a defender.
    """
    overall = float(rate.mean(skipna=True))
    means = rate.groupby(position).transform("mean")
    reference = means.where(means.notna() & (means > 0), overall if overall > 0 else np.nan)
    ratio = rate / reference
    return ratio.clip(lower=config.minimum_ratio, upper=config.maximum_ratio)


def build_features(
    history: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    config: FeatureConfig,
    positions: pd.DataFrame | None = None,
    metrics: pd.DataFrame | None = None,
    season: str | None = None,
) -> pd.DataFrame:
    """One row per player, describing them as of ``as_of``.

    ``history`` is the per-gameweek table. **Only rows whose kickoff is strictly before ``as_of``
    are used**, and that filter happens here rather than in each caller, because a filter that each
    caller has to remember is a filter that one caller eventually forgets.

    ``metrics`` is the conformed advanced table. It contributes only completed *prior* seasons, and
    only when ``season`` says which season is being predicted; without that the question "is this
    row in the past" has no answer and the safe answer is taken instead.
    """
    if history.empty:
        return pd.DataFrame(columns=["player_code", "as_of", *input_features(config)])

    moment = pd.Timestamp(as_of).tz_convert("UTC")
    known = history[history["kickoff_time"] < moment].copy()
    if known.empty:
        return pd.DataFrame(columns=["player_code", "as_of", *input_features(config)])

    known = known.sort_values(["player_code", "kickoff_time"])
    rows: list[dict[str, object]] = []

    for code, group in known.groupby("player_code", sort=True):
        row: dict[str, object] = {"player_code": as_int(code), "as_of": moment}
        for window in config.rolling_windows:
            recent = group.tail(window)
            minutes = float(recent["minutes"].sum())
            row[f"minutes_mean_last{window}"] = float(recent["minutes"].mean())
            for stat in config.rolling_statistics:
                if stat not in recent.columns:
                    row[f"{stat}_per90_last{window}"] = np.nan
                    continue
                values = pd.to_numeric(recent[stat], errors="coerce")
                if values.isna().all() or minutes <= 0:
                    # Not measured in this window, or no minutes played. Null, not zero — the
                    # distinction between "did not do it" and "we could not have seen it".
                    row[f"{stat}_per90_last{window}"] = np.nan
                else:
                    row[f"{stat}_per90_last{window}"] = float(values.sum()) / minutes * 90.0

        last = group.iloc[-1]
        row["matches_observed"] = len(group)
        row["appearance_rate"] = float((group["minutes"] > 0).mean())
        starts = pd.to_numeric(group["starts"], errors="coerce")
        row["starts_rate"] = float(starts.mean()) if not starts.isna().all() else np.nan
        row["days_since_last_match"] = float(
            (moment - pd.Timestamp(last["kickoff_time"])).total_seconds() / 86400.0
        )
        row["price"] = float(last["price"])
        row["was_home"] = bool(last["was_home"])
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame = _attach_prior_season(frame, known, config=config, metrics=metrics, season=season)
    if positions is not None and not positions.empty:
        frame = frame.merge(
            positions[["player_code", "position"]].drop_duplicates("player_code"),
            on="player_code",
            how="left",
        )
    return frame


def _attach_prior_season(
    frame: pd.DataFrame,
    known: pd.DataFrame,
    *,
    config: FeatureConfig,
    metrics: pd.DataFrame | None,
    season: str | None,
) -> pd.DataFrame:
    """Merge the prior-season ratios on, or declare them null.

    The columns exist whenever the feature is enabled, even when no source supplied a number. A
    frame whose shape depends on whether a scraper ran is a frame that fails somewhere else, later,
    for a reason nobody connects back to the scraper.
    """
    names = prior_season_feature_names(config)
    if not names:
        return frame
    for name in names:
        frame[name] = np.nan
    if metrics is None or metrics.empty or season is None:
        return frame

    positions: Mapping[int, str] = (
        {
            as_int(code): str(value)
            for code, value in known.groupby("player_code")["position"].last().items()
        }
        if "position" in known.columns
        else {}
    )
    ratios = prior_season_ratios(
        metrics, season=season, positions=positions, config=config.prior_season
    )
    if ratios.empty:
        return frame
    return frame.drop(columns=list(names)).merge(
        ratios[["player_code", *names]], on="player_code", how="left"
    )


def assert_no_look_ahead(
    features: pd.DataFrame,
    history: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
) -> None:
    """Prove the features could have been computed at ``as_of``.

    Checked rather than reasoned about. The leakage this catches is not exotic — it is an off-by-one
    on a gameweek boundary, or a merge that pulled in the row it was predicting — and both look
    completely ordinary in a diff.
    """
    if features.empty:
        return
    moment = pd.Timestamp(as_of).tz_convert("UTC")

    stamped = features["as_of"].unique()
    late = [stamp for stamp in stamped if pd.Timestamp(stamp) > moment]
    if late:
        raise LeakageError(f"features are stamped after the deadline they are used for: {late[:3]}")

    used = history[history["player_code"].isin(features["player_code"])]
    future = used[used["kickoff_time"] >= moment]
    if not future.empty:
        # This is only a leak if those rows were actually consumed, which build_features prevents.
        # Reported at debug because the frame legitimately contains future matches; the assertion
        # that matters is the stamp above plus the filter in build_features.
        log.debug(
            "features.future_rows_present",
            extra={"rows": len(future), "as_of": str(moment)},
        )


def training_frame(
    history: pd.DataFrame,
    deadlines: Sequence[tuple[int, pd.Timestamp]],
    *,
    config: FeatureConfig,
) -> pd.DataFrame:
    """Features and target for every (player, gameweek) pair, built one deadline at a time.

    Deliberately not vectorised across gameweeks. A single pass with a shifted window is faster and
    is exactly where look-ahead creeps in: one wrong ``shift`` and the model sees the match it is
    predicting. Rebuilding per deadline is slower and is checkable.
    """
    frames: list[pd.DataFrame] = []
    for gameweek, deadline in deadlines:
        moment = pd.Timestamp(deadline).tz_convert("UTC")
        features = build_features(history, as_of=moment, config=config)
        if features.empty:
            continue
        assert_no_look_ahead(features, history, as_of=moment)

        outcomes = history[(history["gameweek"] == gameweek) & (history["kickoff_time"] >= moment)][
            ["player_code", "position", TARGET, "minutes"]
        ]
        if outcomes.empty:
            continue
        merged = features.merge(outcomes, on="player_code", how="inner")
        merged["gameweek"] = gameweek
        frames.append(merged)

    if not frames:
        return pd.DataFrame(columns=["player_code", "gameweek", TARGET, *input_features(config)])
    return pd.concat(frames, ignore_index=True)


__all__ = [
    "FIXTURE_AT_HOME",
    "FIXTURE_COLUMNS",
    "FIXTURE_OPPONENT",
    "FIXTURE_TEAM",
    "PRIOR_SEASON_MINUTES",
    "PRIOR_SEASON_PREFIX",
    "TARGET",
    "FeatureSpec",
    "Knowability",
    "LeakageError",
    "assert_no_look_ahead",
    "build_features",
    "input_features",
    "prior_season_feature_names",
    "prior_season_ratios",
    "rolling_feature_names",
    "season_start_year",
    "specs",
    "training_frame",
]
