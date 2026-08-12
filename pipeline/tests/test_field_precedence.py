"""Per-field source precedence (E5-S5, NFR-15) and the canonical merge it drives.

The requirement is not only that precedence works, but that it is **configuration rather than
code**: the tests below change the answer by changing a config value, never by changing a branch.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_dof.config.models import EntityResolutionConfig, SourcesConfig
from fpl_dof.silver.tables import ADVANCED_METRICS, Table, columns_for, validate
from fpl_dof.sources.enrich import canonicalise
from fpl_dof.sources.precedence import (
    DEFAULT_FIELD_PRECEDENCE,
    effective_precedence,
    merge_by_precedence,
    rank_for,
)

SEASON = "2026/27"


def advanced(*rows: dict[str, object]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in columns_for(Table.PLAYER_ADVANCED):
        if column not in frame.columns:
            frame[column] = None
    return frame[columns_for(Table.PLAYER_ADVANCED)]


# --- the table itself -----------------------------------------------------------------------------


def test_the_game_is_the_only_source_of_its_own_record() -> None:
    """Minutes, prices and points are facts the game publishes about itself."""
    for field in ("minutes", "price", "total_points"):
        assert len(DEFAULT_FIELD_PRECEDENCE[field]) == 1


def test_expected_goals_prefers_one_provider_and_falls_back_to_another() -> None:
    order = DEFAULT_FIELD_PRECEDENCE["expected_goals"]
    assert len(order) >= 2, "a single-source xG chain cannot degrade"
    assert order[0] != order[1]


def test_a_source_outside_a_fields_chain_is_refused_rather_than_ranked_last() -> None:
    order = DEFAULT_FIELD_PRECEDENCE["minutes"]
    assert rank_for("minutes", order[0], DEFAULT_FIELD_PRECEDENCE) == 0
    assert rank_for("minutes", "somebody_else", DEFAULT_FIELD_PRECEDENCE) is None


def test_configuration_overrides_the_declared_default() -> None:
    """DP-01: where two sources supply one field, configuration decides, not an if."""
    order = DEFAULT_FIELD_PRECEDENCE["expected_goals"]
    reversed_order = tuple(reversed(order))
    merged = effective_precedence({"expected_goals": reversed_order})
    assert merged["expected_goals"] == reversed_order
    assert merged["minutes"] == DEFAULT_FIELD_PRECEDENCE["minutes"]


# --- the merge ------------------------------------------------------------------------------------


def frame_for(precedence_field: str = "expected_goals") -> pd.DataFrame:
    first, second = DEFAULT_FIELD_PRECEDENCE[precedence_field][:2]
    return pd.DataFrame(
        [
            {"key": 1, "source": first, "expected_goals": 1.0, "shots": None},
            {"key": 1, "source": second, "expected_goals": 2.0, "shots": 9.0},
        ]
    )


def test_the_higher_precedence_value_wins() -> None:
    merged = merge_by_precedence(
        frame_for(),
        keys=["key"],
        fields=["expected_goals"],
        precedence=DEFAULT_FIELD_PRECEDENCE,
    )
    assert merged.iloc[0]["expected_goals"] == 1.0


def test_a_source_with_nothing_to_say_does_not_out_rank_one_that_has() -> None:
    """Otherwise precedence becomes a way of deleting data, which is the opposite of the point."""
    merged = merge_by_precedence(
        frame_for(),
        keys=["key"],
        fields=["expected_goals", "shots"],
        precedence={
            "expected_goals": DEFAULT_FIELD_PRECEDENCE["expected_goals"],
            "shots": DEFAULT_FIELD_PRECEDENCE["expected_goals"],
        },
    )
    assert merged.iloc[0]["shots"] == 9.0


def test_reversing_the_configured_order_reverses_the_answer() -> None:
    order = DEFAULT_FIELD_PRECEDENCE["expected_goals"]
    merged = merge_by_precedence(
        frame_for(),
        keys=["key"],
        fields=["expected_goals"],
        precedence=effective_precedence({"expected_goals": tuple(reversed(order[:2]))}),
    )
    assert merged.iloc[0]["expected_goals"] == 2.0


def test_the_contributing_sources_are_recorded() -> None:
    """DP-09: a number whose origin cannot be recovered cannot be argued with."""
    merged = merge_by_precedence(
        frame_for(),
        keys=["key"],
        fields=["expected_goals"],
        precedence=DEFAULT_FIELD_PRECEDENCE,
    )
    assert merged.iloc[0]["sources"] == DEFAULT_FIELD_PRECEDENCE["expected_goals"][0]


# --- end to end through canonicalise ------------------------------------------------------------


PLAYERS = pd.DataFrame(
    [
        {
            "player_id": 13,
            "code": 204480,
            "web_name": "Rice",
            "full_name": "Declan Rice",
            "position": "MID",
            "team_id": 1,
        }
    ]
)
TEAMS = pd.DataFrame([{"team_id": 1, "name": "Arsenal", "short_name": "ARS"}])


def tables() -> dict[str, pd.DataFrame]:
    preferred, fallback = DEFAULT_FIELD_PRECEDENCE["expected_goals"][:2]
    refs = pd.DataFrame(
        [
            {
                "season": SEASON,
                "source": source,
                "source_player_id": f"{source}-1",
                "source_name": "Declan Rice",
                "source_team": "Arsenal",
                "source_position": "MID",
            }
            for source in (preferred, fallback)
        ]
    )
    return {
        Table.PLAYER.value: PLAYERS,
        Table.TEAM.value: TEAMS,
        Table.PLAYER_CROSSWALK.value: refs,
        Table.PLAYER_ADVANCED.value: advanced(
            {
                "season": SEASON,
                "source": preferred,
                "source_player_id": f"{preferred}-1",
                "scope": "season",
                "expected_goals": 1.5,
            },
            {
                "season": SEASON,
                "source": fallback,
                "source_player_id": f"{fallback}-1",
                "scope": "season",
                "expected_goals": 1.9,
                "tackles": 11.0,
            },
        ),
    }


def test_resolution_and_precedence_produce_one_canonical_row() -> None:
    produced, report = canonicalise(tables(), season=SEASON, config=SourcesConfig(), overrides={})
    metrics = produced[Table.PLAYER_METRIC.value]
    assert len(metrics) == 1
    row = metrics.iloc[0]
    assert row["player_code"] == 204480
    assert row["expected_goals"] == 1.5
    # Contributed by the lower-precedence source, which the higher one does not measure at all.
    assert row["tackles"] == 11.0
    assert report.unmatched_rate(DEFAULT_FIELD_PRECEDENCE["expected_goals"][0]) == 0.0
    validate(Table.PLAYER_METRIC, metrics)
    validate(Table.PLAYER_CROSSWALK, produced[Table.PLAYER_CROSSWALK.value])


def test_losing_the_preferred_source_falls_through_to_the_next() -> None:
    """The degradation NFR-15 actually asks for: a worse number, not a missing column."""
    preferred = DEFAULT_FIELD_PRECEDENCE["expected_goals"][0]
    without = tables()
    for name in (Table.PLAYER_CROSSWALK.value, Table.PLAYER_ADVANCED.value):
        frame = without[name]
        without[name] = frame[frame["source"] != preferred].reset_index(drop=True)

    produced, _ = canonicalise(without, season=SEASON, config=SourcesConfig(), overrides={})
    row = produced[Table.PLAYER_METRIC.value].iloc[0]
    assert row["expected_goals"] == 1.9


def test_an_unresolved_player_never_reaches_the_canonical_table() -> None:
    """A number attached to a name nobody could identify must not be attached to a footballer."""
    unknown = tables()
    unknown[Table.PLAYER_CROSSWALK.value] = pd.DataFrame(
        [
            {
                "season": SEASON,
                "source": DEFAULT_FIELD_PRECEDENCE["expected_goals"][0],
                "source_player_id": f"{DEFAULT_FIELD_PRECEDENCE['expected_goals'][0]}-1",
                "source_name": "Nobody Whatsoever",
                "source_team": "Arsenal",
                "source_position": "MID",
            }
        ]
    )
    unknown[Table.PLAYER_ADVANCED.value] = unknown[Table.PLAYER_ADVANCED.value].head(1)
    produced, report = canonicalise(unknown, season=SEASON, config=SourcesConfig(), overrides={})
    assert Table.PLAYER_METRIC.value not in produced
    assert produced[Table.PLAYER_ADVANCED.value]["player_code"].isna().all()
    assert report.unmatched_rate(DEFAULT_FIELD_PRECEDENCE["expected_goals"][0]) == 1.0


def test_resolution_configuration_reaches_canonicalise() -> None:
    config = SourcesConfig(resolution=EntityResolutionConfig(fuzzy_threshold=1.0))
    produced, _ = canonicalise(tables(), season=SEASON, config=config, overrides={})
    assert not produced[Table.PLAYER_CROSSWALK.value].empty


def test_every_declared_metric_is_mergeable() -> None:
    """A metric a source can fill in but precedence has no opinion about would be unreachable."""
    missing = [name for name in ADVANCED_METRICS if name not in DEFAULT_FIELD_PRECEDENCE]
    assert not missing, f"no precedence declared for {missing}"


@pytest.mark.parametrize("field", sorted(DEFAULT_FIELD_PRECEDENCE))
def test_no_field_lists_a_source_twice(field: str) -> None:
    order = DEFAULT_FIELD_PRECEDENCE[field]
    assert len(set(order)) == len(order)
