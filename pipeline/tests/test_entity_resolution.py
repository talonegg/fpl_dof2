"""Entity resolution — the highest-risk code in the epic, tested hardest (E5-S1, DP-13).

A mismatch here is invisible: it produces a full, valid, confidently wrong dataset. So the tests
assert not only that the right players match, but that the *wrong* ones do not, and that both
guardrails actually fire.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_dof.config.models import EntityResolutionConfig
from fpl_dof.sources.names import normalise, team_key, token_set_ratio
from fpl_dof.sources.resolve import (
    REF_COLUMNS,
    ResolutionConflictError,
    load_overrides,
    resolve,
    resolve_teams,
)

SEASON = "2026/27"

PLAYERS = pd.DataFrame(
    [
        {
            "player_id": 13,
            "code": 204480,
            "web_name": "Rice",
            "full_name": "Declan Rice",
            "position": "MID",
            "team_id": 1,
        },
        {
            "player_id": 19,
            "code": 481655,
            "web_name": "Zubimendi",
            "full_name": "Martín Zubimendi Ibáñez",
            "position": "MID",
            "team_id": 1,
        },
        {
            "player_id": 31,
            "code": 199798,
            "web_name": "Konsa",
            "full_name": "Ezri Konsa Ngoyo",
            "position": "DEF",
            "team_id": 2,
        },
        {
            "player_id": 32,
            "code": 199796,
            "web_name": "Cash",
            "full_name": "Matty Cash",
            "position": "DEF",
            "team_id": 2,
        },
    ]
)

TEAMS = pd.DataFrame(
    [
        {"team_id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"team_id": 2, "name": "Aston Villa", "short_name": "AVL"},
    ]
)


def refs(*rows: tuple[str, str, str, str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": SEASON,
                "source": source,
                "source_player_id": source_id,
                "source_name": name,
                "source_team": team,
                "source_position": position,
            }
            for source, source_id, name, team, position in rows
        ],
        columns=list(REF_COLUMNS),
    )


def run(frame: pd.DataFrame, **kwargs: object) -> pd.DataFrame:
    config = EntityResolutionConfig(**kwargs)
    resolved, _report = resolve(frame, PLAYERS, TEAMS, season=SEASON, config=config, overrides={})
    return resolved


# --- normalisation ------------------------------------------------------------------------------


def test_normalisation_survives_accents_and_punctuation() -> None:
    assert normalise("Đorđe Petrović") == normalise("Dorde Petrovic")
    assert normalise("N'Golo Kanté") == "n golo kante"
    assert normalise("Vinícius Júnior") == "vinicius"


def test_normalisation_never_drops_a_name_part() -> None:
    """ "Rodrigo" and "Rodri" are two footballers. Nothing here may make them one."""
    assert normalise("Rodrigo") != normalise("Rodri")


def test_similarity_treats_a_shorter_name_as_the_same_person() -> None:
    assert token_set_ratio("Ezri Konsa", "Ezri Konsa Ngoyo") == 1.0
    assert token_set_ratio("Declan Rice", "Matty Cash") == 0.0


def test_club_names_reduce_to_something_two_sources_can_agree_on() -> None:
    assert team_key("Wolverhampton Wanderers") == team_key("Wolverhampton")
    assert team_key("Arsenal FC") == team_key("Arsenal")
    assert team_key("Arsenal") != team_key("Aston Villa")


# --- tier 1: deterministic ----------------------------------------------------------------------


def test_exact_name_club_and_position_matches_deterministically() -> None:
    resolved = run(refs(("understat", "1001", "Declan Rice", "Arsenal", "MID")))
    row = resolved.iloc[0]
    assert row["match_method"] == "deterministic"
    assert row["player_id"] == 13
    assert row["player_code"] == 204480
    assert row["confidence"] == 1.0
    assert not row["verified"]


def test_the_web_name_is_a_deterministic_key_too() -> None:
    """Sources disagree about whether a player's name is the legal one or the printed one."""
    resolved = run(refs(("fbref", "aa1", "Konsa", "Aston Villa", "DEF")))
    assert resolved.iloc[0]["match_method"] == "deterministic"
    assert resolved.iloc[0]["player_id"] == 31


def test_the_right_club_is_required() -> None:
    resolved = run(refs(("understat", "1001", "Declan Rice", "Aston Villa", "MID")))
    assert resolved.iloc[0]["match_method"] == "unmatched"


# --- tier 2: fuzzy ------------------------------------------------------------------------------


def test_a_shortened_name_within_the_club_matches_fuzzily() -> None:
    resolved = run(refs(("understat", "1002", "Ezri Konsa", "Aston Villa", "DEF")))
    row = resolved.iloc[0]
    assert row["match_method"] == "fuzzy"
    assert row["player_id"] == 31
    assert row["confidence"] >= 0.9


def test_an_ambiguous_fuzzy_match_is_refused_rather_than_guessed() -> None:
    """Two players in one club who both score highly resolve to nobody.

    The single most important assertion in this file. An unmatched player is a visible gap on the
    data-health page; a coin-flipped one is a season of quietly wrong expected goals (R-10).
    """
    doubles = pd.DataFrame(
        [
            {
                "player_id": 90,
                "code": 900,
                "web_name": "G.Magalhaes",
                "full_name": "Gabriel Magalhaes",
                "position": "DEF",
                "team_id": 1,
            },
            {
                "player_id": 91,
                "code": 901,
                "web_name": "G.Jesus",
                "full_name": "Gabriel Jesus",
                "position": "DEF",
                "team_id": 1,
            },
        ]
    )
    resolved, _ = resolve(
        refs(("understat", "1", "Gabriel", "Arsenal", "DEF")),
        doubles,
        TEAMS,
        season=SEASON,
        config=EntityResolutionConfig(),
        overrides={},
    )
    assert resolved.iloc[0]["match_method"] == "unmatched"


def test_a_low_similarity_name_stays_unmatched() -> None:
    resolved = run(refs(("understat", "9999", "Fictional Trialist", "Arsenal", "FWD")))
    assert resolved.iloc[0]["match_method"] == "unmatched"
    assert pd.isna(resolved.iloc[0]["player_id"])


def test_the_threshold_is_configuration_and_actually_changes_the_answer() -> None:
    """DP-06: the knobs are real, and loosening them really does admit a worse match.

    The margin is the guardrail against ambiguity, so this also documents what turning it off
    costs: the ambiguous Gabriel above stops being refused and becomes a guess.
    """
    doubles = pd.DataFrame(
        [
            {
                "player_id": 90,
                "code": 900,
                "web_name": "G.Magalhaes",
                "full_name": "Gabriel Magalhaes",
                "position": "DEF",
                "team_id": 1,
            },
            {
                "player_id": 91,
                "code": 901,
                "web_name": "G.Jesus",
                "full_name": "Gabriel Jesus",
                "position": "DEF",
                "team_id": 1,
            },
        ]
    )
    ambiguous = refs(("understat", "1", "Gabriel", "Arsenal", "DEF"))
    permissive, _ = resolve(
        ambiguous,
        doubles,
        TEAMS,
        season=SEASON,
        config=EntityResolutionConfig(fuzzy_margin=0.0),
        overrides={},
    )
    assert permissive.iloc[0]["match_method"] == "fuzzy"


# --- tier 3: overrides --------------------------------------------------------------------------


def test_an_override_wins_and_is_the_only_verified_tier() -> None:
    resolved, _ = resolve(
        refs(("understat", "abc", "Somebody Unrecognisable", "Arsenal", "MID")),
        PLAYERS,
        TEAMS,
        season=SEASON,
        config=EntityResolutionConfig(),
        overrides={"understat": {"abc": 481655}},
    )
    row = resolved.iloc[0]
    assert row["match_method"] == "override"
    assert row["player_id"] == 19
    assert bool(row["verified"]) is True


def test_a_stale_override_is_reported_rather_than_obeyed() -> None:
    resolved, report = resolve(
        refs(("understat", "abc", "Declan Rice", "Arsenal", "MID")),
        PLAYERS,
        TEAMS,
        season=SEASON,
        config=EntityResolutionConfig(),
        overrides={"understat": {"abc": 111111}},
    )
    assert resolved.iloc[0]["match_method"] == "deterministic"
    assert any("stale" in warning for warning in report.warnings)


def test_the_committed_override_file_loads() -> None:
    """It is empty, and it must stay loadable — a broken override file breaks every source."""
    assert load_overrides() == {}


# --- guardrails ---------------------------------------------------------------------------------


def test_two_source_players_claiming_one_footballer_fails_immediately() -> None:
    with pytest.raises(ResolutionConflictError, match="both resolved to canonical"):
        run(
            refs(
                ("understat", "1", "Declan Rice", "Arsenal", "MID"),
                ("understat", "2", "Declan Rice", "Arsenal", "MID"),
            )
        )


def test_two_different_sources_may_of_course_claim_the_same_footballer() -> None:
    resolved = run(
        refs(
            ("understat", "1", "Declan Rice", "Arsenal", "MID"),
            ("fbref", "aa1", "Declan Rice", "Arsenal", "MID"),
        )
    )
    assert set(resolved["player_id"]) == {13}
    assert len(resolved) == 2


def test_resolution_is_stamped_with_the_season_it_was_run_for() -> None:
    """Transfers invalidate club-based matching, so a crosswalk is only true for one season."""
    resolved = run(refs(("understat", "1", "Declan Rice", "Arsenal", "MID")))
    assert set(resolved["season"]) == {SEASON}


def test_the_unmatched_rate_is_reported_per_source() -> None:
    _resolved, report = resolve(
        refs(
            ("understat", "1", "Declan Rice", "Arsenal", "MID"),
            ("understat", "2", "Nobody At All", "Arsenal", "MID"),
            ("fbref", "aa1", "Declan Rice", "Arsenal", "MID"),
        ),
        PLAYERS,
        TEAMS,
        season=SEASON,
        config=EntityResolutionConfig(),
        overrides={},
    )
    assert report.unmatched_rate("understat") == 0.5
    assert report.unmatched_rate("fbref") == 0.0


def test_no_references_is_not_an_error() -> None:
    resolved, report = resolve(
        refs(),
        PLAYERS,
        TEAMS,
        season=SEASON,
        config=EntityResolutionConfig(),
        overrides={},
    )
    assert resolved.empty
    assert report.counts == {}


# --- teams --------------------------------------------------------------------------------------


def test_clubs_resolve_by_full_name_and_by_abbreviation() -> None:
    mapping = resolve_teams(pd.Series(["Arsenal", "AVL", "Nowhere United"]), TEAMS)
    assert mapping == {"Arsenal": 1, "AVL": 2}
