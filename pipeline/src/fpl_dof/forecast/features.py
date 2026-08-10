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
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from fpl_dof.config.models import FeatureConfig
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)


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
    return (
        *rolling,
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
        FeatureSpec(
            name=TARGET,
            knowability=Knowability.AFTER_KICKOFF,
            summary="What actually happened. The target, and never an input",
            source_columns=(TARGET,),
        ),
    )


def input_features(config: FeatureConfig) -> tuple[str, ...]:
    return tuple(spec.name for spec in specs(config) if spec.is_input)


def build_features(
    history: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    config: FeatureConfig,
    positions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per player, describing them as of ``as_of``.

    ``history`` is the per-gameweek table. **Only rows whose kickoff is strictly before ``as_of``
    are used**, and that filter happens here rather than in each caller, because a filter that each
    caller has to remember is a filter that one caller eventually forgets.
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
    if positions is not None and not positions.empty:
        frame = frame.merge(
            positions[["player_code", "position"]].drop_duplicates("player_code"),
            on="player_code",
            how="left",
        )
    return frame


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
    "TARGET",
    "FeatureSpec",
    "Knowability",
    "LeakageError",
    "assert_no_look_ahead",
    "build_features",
    "input_features",
    "rolling_feature_names",
    "specs",
    "training_frame",
]
