"""Per-field source precedence, and the merge that applies it (NFR-15, DP-01).

Where two sources supply the same field, something has to decide. That decision is data, not an
``if`` chain: the default table below is the source layer's own declaration — the only place
allowed to name a provider (Invariant 1) — and ``sources.field_precedence`` in configuration
overrides any entry of it without a code change.

**Why the defaults are what they are.** Minutes, prices and points are the game's own record of
itself; no third party can be more right about them than the game, so the official source is the
only entry. Expected goals are a *model output*, and the two providers publish different models —
Understat first because its shot model is the one FPL's own expected-goals columns are closest to,
FBref second so that losing one leaves the field populated rather than empty. Defensive counts
prefer the official feed because Defensive Contribution is scored from it, and take FBref's
component counts only where the official feed has none.

A source that is missing simply does not appear in any row's precedence chain, which is what makes
losing one degrade a field's quality rather than remove the field (DP-15).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from fpl_dof.obs.logging import get_logger

log = get_logger(__name__)

#: Canonical field name -> source names to try, in order. Overridable per field by configuration.
DEFAULT_FIELD_PRECEDENCE: dict[str, tuple[str, ...]] = {
    # The game's own record of itself. One entry, on purpose.
    "minutes": ("fpl",),
    "price": ("fpl",),
    "total_points": ("fpl",),
    "bps": ("fpl",),
    "defensive_contribution": ("fpl",),
    # Modelled quantities, where a specialist provider beats the game's own summary.
    "expected_goals": ("understat", "fbref", "fpl"),
    "non_penalty_expected_goals": ("understat", "fbref"),
    "expected_assists": ("understat", "fbref", "fpl"),
    "shots": ("understat", "fbref"),
    "shots_on_target": ("fbref", "understat"),
    "key_passes": ("understat", "fbref"),
    "minutes_played": ("fpl", "understat", "fbref"),
    "matches": ("fpl", "understat", "fbref"),
    # Only one source measures these at all today. Named anyway, so that adding a second is a
    # configuration question rather than a discovery.
    "shot_creating_actions": ("fbref",),
    "goal_creating_actions": ("fbref",),
    "progressive_carries": ("fbref",),
    "progressive_passes": ("fbref",),
    "touches_attacking_penalty_area": ("fbref",),
    "tackles": ("fpl", "fbref"),
    "interceptions": ("fbref",),
    "blocks": ("fbref",),
    "clearances": ("fbref",),
    "recoveries": ("fpl", "fbref"),
}


def effective_precedence(
    overrides: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """The default table with configured overrides applied, per field."""
    merged = dict(DEFAULT_FIELD_PRECEDENCE)
    for field, order in (overrides or {}).items():
        merged[field] = tuple(order)
    return merged


def rank_for(field: str, source: str, precedence: Mapping[str, Sequence[str]]) -> int | None:
    """Where a source sits for a field, or ``None`` when it may not supply it at all.

    ``None`` rather than a large number: a source that is not in a field's chain is not merely last,
    it is not permitted, and silently admitting it in last place is how a precedence table stops
    meaning anything.
    """
    order = precedence.get(field)
    if order is None:
        return 0
    return order.index(source) if source in order else None


def merge_by_precedence(
    frame: pd.DataFrame,
    *,
    keys: Sequence[str],
    fields: Sequence[str],
    precedence: Mapping[str, Sequence[str]],
    source_column: str = "source",
) -> pd.DataFrame:
    """Collapse per-source rows into one canonical row per key, field by field.

    For each field, the value is taken from the highest-precedence source that actually has one.
    "Actually has one" means non-null: a source that reports nothing must not out-rank a source
    that reports something, or precedence would quietly become a way of deleting data.

    The contributing source names are recorded in ``sources`` so the result can still be argued
    with (DP-09).
    """
    if frame.empty:
        return frame.assign(sources=pd.Series(dtype="object")).drop(columns=[source_column])

    key_list = list(keys)
    grouped = frame.groupby(key_list, dropna=False, sort=True)
    rows: list[dict[str, object]] = []

    for key_values, group in grouped:
        values = key_values if isinstance(key_values, tuple) else (key_values,)
        row: dict[str, object] = dict(zip(key_list, values, strict=True))
        contributors: list[str] = []
        for field in fields:
            chosen_source: str | None = None
            chosen_rank: int | None = None
            chosen_value: object = None
            for record in group.itertuples():
                source = str(getattr(record, source_column))
                value = getattr(record, field, None)
                if value is None or pd.isna(value):
                    continue
                rank = rank_for(field, source, precedence)
                if rank is None:
                    continue
                if chosen_rank is None or rank < chosen_rank:
                    chosen_rank, chosen_source, chosen_value = rank, source, value
            row[field] = chosen_value
            if chosen_source is not None and chosen_source not in contributors:
                contributors.append(chosen_source)
        row["sources"] = ",".join(sorted(contributors))
        rows.append(row)

    return pd.DataFrame(rows, columns=[*key_list, *fields, "sources"])


__all__ = [
    "DEFAULT_FIELD_PRECEDENCE",
    "effective_precedence",
    "merge_by_precedence",
    "rank_for",
]
