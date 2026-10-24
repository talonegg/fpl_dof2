"""The Python half of the cross-language lineup conformance test (WEB-04, owner answer Q2).

`squad/selection.py` and `web/src/components/squad/lineup.ts` both pick the XI, the armbands and
the bench order from a fixed fifteen; both read `contracts/conformance/lineup-corpus.json` (DL-39).
The bench is ranked by P(plays) x xP in both, ties by player id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.rules.models import GameRules, Position, SquadRules
from fpl_dof.squad.selection import Candidate, select_team

CONFORMANCE = Path(__file__).resolve().parents[2] / "contracts" / "conformance"
CORPUS: dict[str, Any] = json.loads((CONFORMANCE / "lineup-corpus.json").read_text("utf-8"))
RULESETS: dict[str, Any] = json.loads((CONFORMANCE / "legality-corpus.json").read_text("utf-8"))[
    "rulesets"
]
CASES: list[dict[str, Any]] = CORPUS["cases"]


def test_the_corpus_is_loaded_and_names_every_case_once() -> None:
    names = [case["name"] for case in CASES]
    assert len(names) == len(set(names)) >= 5


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_selection_matches_the_shared_corpus(case: dict[str, Any], game_rules: GameRules) -> None:
    ruleset = {k: v for k, v in RULESETS[case["rules"]].items() if not k.startswith("$")}
    rules = game_rules.model_copy(update={"squad": SquadRules.model_validate(ruleset)})
    candidates = {}
    for key, spec in CORPUS["player_pool"].items():
        player = {**spec, **case["player_overrides"].get(key, {})}
        candidates[int(key)] = Candidate(
            player_id=int(key),
            position=Position(player["position"]),
            expected_points=player["xp_next"],
            start_probability=player["start_probability"],
        )

    selection = select_team(candidates, rules)

    assert {
        "starting": sorted(selection.starting),
        "bench_order": list(selection.bench_order),
        "captain": selection.captain,
        "vice_captain": selection.vice_captain,
        "formation": selection.formation,
    } == case["expected"], case["why"]
