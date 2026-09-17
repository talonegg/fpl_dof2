"""The season log: what was played, what it scored, and what was advised, per gameweek (DL-69).

E8 §3 calls this "the single most valuable dataset the project produces about itself" — the record
that eventually answers whether the model or the owner's judgement is better, with evidence rather
than impression. Three sources, deliberately kept apart:

- **played** comes from ``entry_pick``, the game's own record of the submitted squad;
- **scored** comes from ``entry_gameweek``, the game's own points and ranks;
- **advised** comes from the ledger, the pipeline's own record written *before* the deadline.

A gameweek with picks and no ledger entry is published with ``advised: null`` and says so. The
owner decided GW1 to GW4 of 2026/27 without the tool; that is a fact about the season, and nothing
here reconstructs advice after the event, because advice reconstructed with hindsight is not
advice (DP-11, DP-13).

Pure (DP-03): frames and mappings in, one payload out.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.week.reconcile import reconcile


def build_log(
    *,
    entry_id: int,
    season: str,
    picks: pd.DataFrame,
    entry_gameweeks: pd.DataFrame | None,
    chips: pd.DataFrame | None,
    advice: Mapping[int, Mapping[str, Any]],
    contract_version: int,
) -> dict[str, Any]:
    """The whole ``log.json`` payload. One row per gameweek the game has recorded picks for."""
    scored = _scores_by_gameweek(entry_gameweeks)
    chip_by_gameweek = _chips_by_gameweek(chips)

    rows: list[dict[str, Any]] = []
    for gameweek in sorted(int(g) for g in picks["gameweek"].unique()):
        for_gameweek = picks[picks["gameweek"] == gameweek].sort_values("slot")
        recorded = advice.get(gameweek)
        rows.append(
            {
                "gameweek": gameweek,
                "played": _played(for_gameweek),
                "score": scored.get(gameweek),
                "chip": chip_by_gameweek.get(gameweek),
                "advised": _advised(recorded),
                "reconciliation": _reconciliation(gameweek, entry_id, recorded, picks),
            }
        )

    advised_count = sum(1 for row in rows if row["advised"] is not None)
    followed = sum(
        1
        for row in rows
        if row["reconciliation"] is not None and bool(row["reconciliation"]["followed"])
    )
    return {
        "contract_version": contract_version,
        "season": season,
        "entry_id": entry_id,
        "summary": {
            "gameweeks_played": len(rows),
            "gameweeks_advised": advised_count,
            "advice_followed": followed,
            "advice_overridden": advised_count - followed,
            "total_points": max((int(s["total_points"]) for s in scored.values()), default=0),
        },
        "gameweeks": rows,
    }


def _played(for_gameweek: pd.DataFrame) -> dict[str, Any]:
    starting = [as_int(r.player_id) for r in for_gameweek.itertuples() if as_int(r.slot) <= 11]
    bench = [as_int(r.player_id) for r in for_gameweek.itertuples() if as_int(r.slot) > 11]
    captain = next(
        (as_int(r.player_id) for r in for_gameweek.itertuples() if bool(r.is_captain)), None
    )
    vice = next(
        (as_int(r.player_id) for r in for_gameweek.itertuples() if bool(r.is_vice_captain)), None
    )
    return {
        "squad": [as_int(v) for v in for_gameweek["player_id"]],
        "starting": starting,
        "bench_order": bench,
        "captain": captain,
        "vice_captain": vice,
    }


def _scores_by_gameweek(entry_gameweeks: pd.DataFrame | None) -> dict[int, dict[str, Any]]:
    if entry_gameweeks is None or entry_gameweeks.empty:
        return {}
    scores: dict[int, dict[str, Any]] = {}
    for row in entry_gameweeks.itertuples():
        scores[as_int(row.gameweek)] = {
            "points": as_int(row.points),
            "total_points": as_int(row.total_points),
            "rank": _optional_int(row.rank),
            "overall_rank": _optional_int(row.overall_rank),
            "points_on_bench": as_int(row.points_on_bench),
            "transfers": as_int(row.transfers),
            "transfers_cost": as_int(row.transfers_cost),
        }
    return scores


def _chips_by_gameweek(chips: pd.DataFrame | None) -> dict[int, str]:
    if chips is None or chips.empty:
        return {}
    return {as_int(row.gameweek): str(row.name) for row in chips.itertuples()}


def _advised(recorded: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if recorded is None:
        return None
    advised = recorded.get("advised")
    if not isinstance(advised, Mapping):
        return None
    recommendation = recorded.get("recommendation")
    moves: list[dict[str, Any]] = []
    transfers = 0
    hit_points = 0
    if isinstance(recommendation, Mapping):
        transfers = int(recommendation.get("transfers") or 0)
        hit_points = int(recommendation.get("hit_points") or 0)
        for move in recommendation.get("moves") or []:
            if isinstance(move, Mapping):
                moves.append(
                    {
                        "out": _optional_int(move.get("out", {}).get("player_id")),
                        "in": _optional_int(move.get("in", {}).get("player_id")),
                    }
                )
    return {
        "run_id": str(recorded.get("run_id") or ""),
        "recorded_at": str(recorded.get("recorded_at") or ""),
        "squad": [as_int(v) for v in advised.get("squad") or []],
        "starting": [as_int(v) for v in advised.get("starting") or []],
        "captain": _optional_int(advised.get("captain")),
        "vice_captain": _optional_int(advised.get("vice_captain")),
        "expected_points": float(advised.get("expected_points") or 0.0),
        "transfers": transfers,
        "hit_points": hit_points,
        "moves": moves,
    }


def _reconciliation(
    gameweek: int,
    entry_id: int,
    recorded: Mapping[str, Any] | None,
    picks: pd.DataFrame,
) -> dict[str, Any] | None:
    if recorded is None or not isinstance(recorded.get("advised"), Mapping):
        return None
    try:
        result = reconcile(
            gameweek=gameweek, entry_id=entry_id, advised=recorded["advised"], picks=picks
        )
    except ValueError, TypeError:
        return None
    return {
        "followed": result.followed,
        "divergences": [d.as_dict() for d in result.divergences],
    }


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, int | float | str):
        return int(value)
    if isinstance(value, np.integer | np.floating):
        return None if np.isnan(value) else int(value)
    return None
