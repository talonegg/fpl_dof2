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

from fpl_dof.config.models import OptimiserConfig, TransferConfig
from fpl_dof.factory.registry import champion, resolve_alias
from fpl_dof.frames import as_int
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.squad.state import HeldPlayer, Provenance, SquadState
from fpl_dof.week.diagnose import diagnose_oracle_gap
from fpl_dof.week.oracle import solve_hindsight_optimal
from fpl_dof.week.reconcile import reconcile
from fpl_dof.week.score_advice import (
    AdvisedLineup,
    lineup_from_advice,
    performances,
    recorded_free_transfers,
    score_model_recommendations,
)


def build_log(
    *,
    entry_id: int,
    season: str,
    picks: pd.DataFrame,
    entry_gameweeks: pd.DataFrame | None,
    chips: pd.DataFrame | None,
    advice: Mapping[int, Mapping[str, Any]],
    contract_version: int,
    player_gameweek: pd.DataFrame | None = None,
    player_pool: pd.DataFrame | None = None,
    rules: GameRules | None = None,
    transfer_config: TransferConfig | None = None,
    optimiser_config: OptimiserConfig | None = None,
) -> dict[str, Any]:
    """The whole ``log.json`` payload. One row per gameweek the game has recorded picks for."""
    if player_gameweek is not None and not player_gameweek.empty:
        # The silver table also holds backfilled seasons, whose gameweek numbers repeat this one's.
        player_gameweek = player_gameweek[player_gameweek["season"] == season]
    scored = _scores_by_gameweek(entry_gameweeks)
    chip_by_gameweek = _chips_by_gameweek(chips)

    rows: list[dict[str, Any]] = []
    for gameweek in sorted(int(g) for g in picks["gameweek"].unique()):
        for_gameweek = picks[picks["gameweek"] == gameweek].sort_values("slot")
        recorded = advice.get(gameweek)
        played_gw = _played(for_gameweek)
        prior_picks = (
            picks[picks["gameweek"] == gameweek - 1]
            if gameweek > 1 and not picks[picks["gameweek"] == gameweek - 1].empty
            else for_gameweek
        )
        hindsight = _hindsight(
            gameweek=gameweek,
            recorded=recorded,
            played=played_gw,
            player_gameweek=player_gameweek,
            player_pool=player_pool,
            rules=rules,
            transfer_config=transfer_config,
            optimiser_config=optimiser_config,
            prior_picks=prior_picks,
        )
        rows.append(
            {
                "gameweek": gameweek,
                "played": played_gw,
                "score": scored.get(gameweek),
                "chip": chip_by_gameweek.get(gameweek),
                "advised": _advised(recorded),
                "reconciliation": _reconciliation(gameweek, entry_id, recorded, picks),
                "hindsight": hindsight,
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


def _hindsight(
    gameweek: int,
    recorded: Mapping[str, Any] | None,
    played: dict[str, Any],
    player_gameweek: pd.DataFrame | None,
    player_pool: pd.DataFrame | None,
    rules: GameRules | None,
    transfer_config: TransferConfig | None,
    optimiser_config: OptimiserConfig | None,
    prior_picks: pd.DataFrame | None,
) -> dict[str, Any] | None:
    if rules is None or player_gameweek is None or player_gameweek.empty:
        return None
    gw_perf = player_gameweek[player_gameweek["gameweek"] == gameweek]
    if gw_perf.empty:
        return None

    perfs = performances(gw_perf)
    player_actuals = {pid: perf.points for pid, perf in perfs.items()}

    lineups: dict[str, AdvisedLineup] = {}
    models_xp: dict[str, dict[int, float]] = {}
    models_captains: dict[str, int] = {}
    champ_id = champion().id

    played_starting = tuple(played.get("starting", ()))
    played_bench = tuple(played.get("bench_order", ()))
    played_cap = played.get("captain") or (played_starting[0] if played_starting else 1)
    played_vice = played.get("vice_captain") or played_cap
    if played_starting:
        lineups["played"] = AdvisedLineup(
            starting=played_starting,
            bench_order=played_bench[1:] if len(played_bench) > 1 else (),
            bench_gkp=played_bench[0] if played_bench else None,
            captain=played_cap,
            vice_captain=played_vice,
            transfers_made=0,
            free_transfers=None,
            expected_points=0.0,
        )
        models_captains["played"] = played_cap

    if recorded is not None and isinstance(recorded.get("advised"), Mapping):
        adv = recorded["advised"]
        rec = recorded.get("recommendation")
        adv_transfers = int(rec.get("transfers") or 0) if isinstance(rec, Mapping) else 0
        adv_free = recorded_free_transfers(recorded)
        lineup = lineup_from_advice(
            adv,
            transfers_made=adv_transfers,
            free_transfers=adv_free,
            recommendation=rec if isinstance(rec, Mapping) else None,
        )
        if lineup is not None:
            lineups[champ_id] = lineup
            models_captains[champ_id] = lineup.captain
            models_xp[champ_id] = {lineup.captain: lineup.expected_points / 2.0}

    if recorded is not None and isinstance(recorded.get("models"), Mapping):
        for m_name, m_data in recorded["models"].items():
            if not isinstance(m_data, Mapping) or m_data.get("role") == "champion":
                continue  # the champion's advice is the top-level record, scored above
            adv_val = m_data.get("advised")
            m_adv: Mapping[str, Any] = adv_val if isinstance(adv_val, Mapping) else m_data
            m_name = resolve_alias(m_name) or m_name  # legacy keys in recorded advice
            lineup = lineup_from_advice(
                m_adv,
                transfers_made=int(m_data.get("transfers", 0)),
                free_transfers=recorded_free_transfers(recorded),
                recommendation=m_data.get("recommendation"),
            )
            if lineup is not None:
                lineups[m_name] = lineup
                models_captains[m_name] = lineup.captain
                models_xp[m_name] = {lineup.captain: lineup.expected_points / 2.0}

    rankings = score_model_recommendations(lineups, perfs, rules)

    if player_pool is not None and not player_pool.empty:
        pool_df = player_pool.copy()
        if "now_cost" not in pool_df.columns and "price" in pool_df.columns:
            pool_df["now_cost"] = pool_df["price"]
    else:
        pool_df = pd.DataFrame(
            [
                {
                    "player_id": r.player_id,
                    "web_name": getattr(r, "web_name", f"Player {r.player_id}"),
                    "position": getattr(r, "position", "MID"),
                    "team_id": getattr(r, "team_id", 1) or 1,
                    "now_cost": float(getattr(r, "start_cost", 5.0) or 5.0),
                }
                for r in gw_perf.itertuples()
            ]
        )

    pool_df["xp_next"] = pool_df["player_id"].map(player_actuals).fillna(0.0)
    pool_df["xp_horizon"] = pool_df["xp_next"]
    pool_df["start_probability"] = 1.0

    held_players: list[HeldPlayer] = []
    source_picks = (
        prior_picks
        if (prior_picks is not None and not prior_picks.empty)
        else pd.DataFrame([{"player_id": pid} for pid in played.get("squad", ())])
    )

    for r in source_picks.itertuples():
        pid = as_int(r.player_id)
        pos = perfs[pid].position if pid in perfs else Position.MID
        held_players.append(
            HeldPlayer(
                player_id=pid,
                position=pos,
                team_id=1,
                current_price=5.0,
                purchase_price=5.0,
            )
        )

    state_rec = recorded.get("squad_state") if recorded is not None else None
    state_rec = state_rec if isinstance(state_rec, Mapping) else {}
    if len(held_players) != 15 or None in (
        state_rec.get("bank"),
        state_rec.get("free_transfers"),
    ):
        # The rankings need neither a squad nor its bank; only the optimal does. Never invent them.
        return {
            "rankings": [r.as_dict() for r in rankings],
            "optimal": None,
            "optimal_unavailable_reason": (
                "the squad, bank or free transfers were not recorded for this gameweek"
            ),
            "diagnostics": [],
        }
    bank = float(state_rec["bank"])
    free_transfers = int(state_rec["free_transfers"])

    state = SquadState(
        entry_id=None,
        gameweek=gameweek,
        players=tuple(held_players),
        bank=bank,
        free_transfers=free_transfers,
        chips_used=(),
        provenance=Provenance.RECONSTRUCTED,
    )

    try:
        optimal_res = solve_hindsight_optimal(
            gameweek=gameweek,
            state=state,
            pool=pool_df,
            rules=rules,
        )
        diagnostics = diagnose_oracle_gap(
            optimal=optimal_res.optimal_overall,
            player_actuals=player_actuals,
            models_xp=models_xp,
            models_captains=models_captains,
        )
        return {
            "rankings": [r.as_dict() for r in rankings],
            "optimal": optimal_res.as_dict(),
            "diagnostics": [d.as_dict() for d in diagnostics],
        }
    except Exception:
        return None
