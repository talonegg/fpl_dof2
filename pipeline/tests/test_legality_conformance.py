"""The Python half of the cross-language legality conformance test.

Squad legality is implemented twice — here, and in `web/src/components/squad/legality.ts` — because
the optimiser must not publish an illegal squad and a reader editing one in the browser must be told
what is wrong with it before they submit it. Two implementations of one rule set drift, and *this*
drift is invisible: the page looks entirely normal while blessing a squad the game will reject.

So both read the same file. `contracts/conformance/legality-corpus.json` holds the rulesets, the
squads and the exact ordered list of `(code, detail)` pairs each squad must produce; this module and
`legality.conformance.test.ts` assert against it independently. Nothing here restates a case, which
is the whole point — a corpus copied into two test directories catches nothing.

`message` is deliberately not asserted. It is prose for a reader and each language phrases it for
its own audience; the machine-readable contract is the code and the detail keys.

This module is the *authority* side of that pair (Invariant 2/9). If the two ever disagree, the
TypeScript mirror is what changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.rules.legality import Squad, SquadPlayer, ViolationCode, validate_squad
from fpl_dof.rules.models import GameRules, Position, SquadRules

CORPUS_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "conformance" / "legality-corpus.json"
)
CORPUS: dict[str, Any] = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _rules_for(case: dict[str, Any], game_rules: GameRules) -> GameRules:
    """The named ruleset, validated into the real model rather than duck-typed.

    Going through `SquadRules` means an internally inconsistent ruleset — a composition that does
    not sum to the squad size, formation maxima the squad cannot supply — fails the test rather than
    quietly testing nothing. Only the squad rules vary: scoring and transfers are irrelevant to
    legality, so they come from the real published fixture.
    """
    ruleset = {k: v for k, v in CORPUS["rulesets"][case["rules"]].items() if not k.startswith("$")}
    return game_rules.model_copy(update={"squad": SquadRules.model_validate(ruleset)})


def _build_squad(case: dict[str, Any]) -> Squad:
    """A member is the pool entry, then `player_defaults`, then `player_overrides`, in that order.

    The same three lines exist in the TypeScript reader. It is the only logic the two share, and it
    is small enough to be obviously the same on both sides.
    """
    spec = case["squad"]
    pool = CORPUS["player_pool"]
    defaults = spec.get("player_defaults", {})
    overrides = spec.get("player_overrides", {})

    players: list[SquadPlayer] = []
    for player_id in spec["players"]:
        attributes = dict(pool[str(player_id)])
        attributes.update(defaults)
        attributes.update(overrides.get(str(player_id), {}))
        players.append(
            SquadPlayer(
                player_id=player_id,
                position=Position(attributes["position"]),
                team_id=attributes["team_id"],
                price=attributes["price"],
            )
        )

    return Squad(
        players=tuple(players),
        starting=tuple(spec.get("starting", ())),
        captain=spec.get("captain"),
        vice_captain=spec.get("vice_captain"),
        bench_order=tuple(spec.get("bench_order", ())),
    )


CASES: list[dict[str, Any]] = CORPUS["cases"]


def test_the_corpus_is_loaded_and_names_every_case_once() -> None:
    """A corpus that silently failed to load would make every case below vacuously pass."""
    names = [case["name"] for case in CASES]
    assert len(names) == len(set(names))
    assert len(names) >= 20


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_legality_matches_the_shared_corpus(case: dict[str, Any], game_rules: GameRules) -> None:
    rules = _rules_for(case, game_rules)
    squad = _build_squad(case)

    violations = validate_squad(squad, rules, budget=case.get("budget"))
    actual = [{"code": str(violation.code), "detail": violation.detail} for violation in violations]

    assert actual == case["expected"], case["why"]


def test_the_corpus_exercises_every_violation_code() -> None:
    """A corpus that covered eleven of the twelve codes would be silently incomplete.

    Asserting against the enum rather than a written-out list means a *new* code fails this test
    until the corpus covers it, which is the only way the coverage claim stays true.
    """
    covered = {violation["code"] for case in CASES for violation in case["expected"]}
    assert covered == {code.value for code in ViolationCode}


def test_the_corpus_includes_squads_that_are_entirely_legal() -> None:
    """Conformance on rejection is half the contract; agreeing on acceptance is the other half."""
    legal = [case for case in CASES if not case["expected"]]
    assert len(legal) >= 3
