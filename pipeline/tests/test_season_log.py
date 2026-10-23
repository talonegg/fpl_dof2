"""The season log's played row is scored by the one scorer, hits charged (D-30, ORC-04).

The owner's GW4 of 2026/27, from the realised corpus: FPL scored it 83 before a 4-point hit, 79 net.
The played row used to be scored without the hit and showed 83.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fpl_dof.publish.contract import CONTRACT_VERSION
from fpl_dof.publish.season_log import build_log
from fpl_dof.rules.models import GameRules

CORPUS = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "conformance"
    / "realised"
    / "realised-corpus.json"
)


def test_the_owners_gw4_played_row_charges_the_hit(game_rules: GameRules) -> None:
    case = next(
        c
        for c in json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
        if c["name"] == "owner-gw4"
    )
    entry, gameweek = case["entry_id"], case["gameweek"]
    picks = pd.DataFrame(
        [
            {
                "entry_id": entry,
                "gameweek": gameweek,
                "player_id": p["player_id"],
                "slot": slot,
                "multiplier": 0,
                "is_captain": p["player_id"] == case["captain"],
                "is_vice_captain": p["player_id"] == case["vice_captain"],
            }
            for slot, p in enumerate(case["picks"], start=1)
        ]
    )
    scores = pd.DataFrame(
        [
            {
                "entry_id": entry,
                "gameweek": gameweek,
                "points": case["expected"]["points"],
                "total_points": 0,
                "rank": None,
                "overall_rank": None,
                "points_on_bench": 0,
                "transfers": case["transfers"],
                "transfers_cost": case["expected"]["transfers_cost"],
            }
        ]
    )
    performances = pd.DataFrame(
        [
            {
                "season": game_rules.season,
                "gameweek": gameweek,
                "player_id": p["player_id"],
                "position": p["position"],
                "minutes": minutes,
                "total_points": points,
            }
            for p in case["picks"]
            for minutes, points in p["fixtures"]
        ]
    )
    pool = pd.DataFrame(
        [{"player_id": p["player_id"], "position": p["position"]} for p in case["picks"]]
    )

    log = build_log(
        entry_id=entry,
        season=game_rules.season,
        picks=picks,
        entry_gameweeks=scores,
        chips=None,
        advice={},
        contract_version=CONTRACT_VERSION,
        player_gameweek=performances,
        player_pool=pool,
        rules=game_rules,
    )

    rankings = log["gameweeks"][0]["hindsight"]["rankings"]
    played = next(r["score"] for r in rankings if r["model_name"] == "played")
    assert (played["points_before_hits"], played["hit_points"], played["net_points"]) == (83, 4, 79)
