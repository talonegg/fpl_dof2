"""Turning what several sources said into one canonical answer.

Two things have to happen after every source has conformed its own data and before anything is
validated and written:

1. **Identity.** Each source's players are matched onto canonical ones (:mod:`.resolve`). Until that
   has happened, an advanced statistic is attached to a name on somebody else's website.
2. **Precedence.** Where two sources supply the same field, one of them wins, per field, by
   configuration (:mod:`.precedence`).

Both live in this package because both need to know that sources have names, and nothing outside it
may (Invariant 1). The transform stage calls one function and stays free of source names.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from fpl_dof.config.models import SourcesConfig
from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import ADVANCED_METRICS, Table, columns_for
from fpl_dof.sources.precedence import effective_precedence, merge_by_precedence
from fpl_dof.sources.resolve import ResolutionReport, load_overrides, resolve, resolve_teams

log = get_logger(__name__)


def canonicalise(
    tables: Mapping[str, pd.DataFrame],
    *,
    season: str,
    config: SourcesConfig,
    overrides: Mapping[str, Mapping[str, int]] | None = None,
    as_of_gameweek: int | None = None,
) -> tuple[dict[str, pd.DataFrame], ResolutionReport]:
    """Resolve identities and apply field precedence, returning the tables that changed.

    Returns only what it produced or rewrote, so the caller can update its collection without this
    function needing to know how the rest of the silver layer is assembled.
    """
    produced: dict[str, pd.DataFrame] = {}
    report = ResolutionReport()

    players = tables.get(Table.PLAYER.value)
    teams = tables.get(Table.TEAM.value)
    refs = tables.get(Table.PLAYER_CROSSWALK.value)

    if refs is not None and not refs.empty:
        if players is None or teams is None:
            report.warnings.append(
                "source references arrived with no canonical player list to match them against; "
                "they are dropped rather than written as half-resolved identities"
            )
            produced[Table.PLAYER_CROSSWALK.value] = pd.DataFrame(
                columns=columns_for(Table.PLAYER_CROSSWALK)
            )
        else:
            crosswalk, report = resolve(
                refs[list(refs.columns)],
                players,
                teams,
                season=season,
                config=config.resolution,
                overrides=overrides if overrides is not None else load_overrides(),
            )
            produced[Table.PLAYER_CROSSWALK.value] = crosswalk

    resolved = produced.get(Table.PLAYER_CROSSWALK.value)
    advanced = tables.get(Table.PLAYER_ADVANCED.value)
    if advanced is not None and not advanced.empty and resolved is not None:
        adv = advanced.copy()
        if "as_of_gameweek" not in adv.columns:
            adv["as_of_gameweek"] = None
        if as_of_gameweek is not None:
            current_mask = (adv["season"] == season) & adv["as_of_gameweek"].isna()
            adv.loc[current_mask, "as_of_gameweek"] = as_of_gameweek
            past_mask = (adv["season"] != season) & adv["as_of_gameweek"].isna()
            adv.loc[past_mask, "as_of_gameweek"] = 38
        identified = _attach_identities(adv, resolved)
        produced[Table.PLAYER_ADVANCED.value] = identified
        metrics = _merge_metrics(identified, config)
        if not metrics.empty:
            produced[Table.PLAYER_METRIC.value] = metrics

    expectations = tables.get(Table.TEAM_MATCH_EXPECTATION.value)
    if expectations is not None and not expectations.empty and teams is not None:
        produced[Table.TEAM_MATCH_EXPECTATION.value] = _attach_team_ids(expectations, teams, season)

    return produced, report


def _attach_identities(advanced: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Replace the placeholder identity columns with the resolved ones.

    A left join, so a row whose player could not be resolved survives with null identity rather than
    disappearing. It contributes nothing downstream, but it is countable, and an uncounted loss is
    the failure this whole path is designed to make visible.
    """
    keys = ["season", "source", "source_player_id"]
    resolved = crosswalk[[*keys, "player_id", "player_code"]]
    merged = advanced.drop(columns=["player_id", "player_code"]).merge(
        resolved, on=keys, how="left"
    )
    return merged[columns_for(Table.PLAYER_ADVANCED)]


def _merge_metrics(advanced: pd.DataFrame, config: SourcesConfig) -> pd.DataFrame:
    """Collapse the per-source ledger into one canonical row per player and scope."""
    known = advanced[advanced["player_code"].notna()]
    if known.empty:
        return pd.DataFrame(columns=columns_for(Table.PLAYER_METRIC))

    keys = ["season", "as_of_gameweek", "player_code", "player_id", "scope", "gameweek"]
    merged = merge_by_precedence(
        known,
        keys=keys,
        fields=list(ADVANCED_METRICS),
        precedence=effective_precedence(config.field_precedence),
    )
    # A merged row is knowable once its latest contributor is (DL-83).
    observed = known.groupby(keys, dropna=False, sort=False)["observed_at"].max().reset_index()
    merged = merged.merge(observed, on=keys, how="left")
    return merged[columns_for(Table.PLAYER_METRIC)]


def _attach_team_ids(expectations: pd.DataFrame, teams: pd.DataFrame, season: str) -> pd.DataFrame:
    """Map the current season's club names onto its team ids, leaving unknown ones null.

    Only the current season's rows: ``teams`` holds this season's clubs and ids, and another
    season's rows already carry the permanent club code their adapter gave them (D-26).
    """
    frame = expectations.copy()
    current = frame["season"] == season
    names = pd.concat(
        [frame.loc[current, "home_team"], frame.loc[current, "away_team"]], ignore_index=True
    )
    lookup = resolve_teams(names, teams)
    unknown = sorted({str(name) for name in names.dropna().unique()} - set(lookup))
    if unknown:
        log.warning("enrich.unmapped_clubs", extra={"clubs": unknown[:10]})
    frame.loc[current, "home_team_id"] = frame.loc[current, "home_team"].map(lookup)
    frame.loc[current, "away_team_id"] = frame.loc[current, "away_team"].map(lookup)
    return frame


__all__ = ["canonicalise"]
