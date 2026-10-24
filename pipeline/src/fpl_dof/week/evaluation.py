"""The evaluation step: every Finished gameweek judged once, and kept (ORC-05).

For a Finished gameweek this judges every strategy that has a record: how far its forecast was from
what happened (xP accuracy, from ORC-08's predictions), and what its advice scored by the one scorer
(ORC-04), the XI, captain and moves net of hits, with the same XI on underlying expected points
(ORC-12, ``rules/underlying.py``) so its miss splits into forecast error and luck. Beside them it
keeps the season log's row for the owner: what was played and scored, the advice of record and its
reconciliation, and the hindsight optimum, solved on the owner's real squad, selling prices, clubs
and bank as of the deadline (D-31).

The result is ``ledger:evaluation/entry-<id>/gwNN.json``, stamped with :data:`EVALUATION_VERSION`. A
gameweek is Evaluated for an entry once that entry's file carries the current version (ORC-01), so
it is computed once and recomputed only when the version changes; another entry's evaluation never
counts. The season log, ``models.json``'s live gameweeks and the live xP
accuracy are built from these files, not from the advice on every publish.

:func:`build_evaluation` is pure (DP-03); the week stage reads silver and the ledger, and writes the
result with :func:`record_evaluation`.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from fpl_dof.config.models import EntryConfig
from fpl_dof.factory.registry import champion, resolve_alias
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.paths import DataLayout
from fpl_dof.quality.rules import lagging_players
from fpl_dof.rules.models import GameRules, Position
from fpl_dof.rules.realised import Lineup, PlayerPerformance, performances
from fpl_dof.rules.underlying import underlying_points, underlying_team_points
from fpl_dof.squad.state import SquadStateError, gameweek_price_index, load_squad_state
from fpl_dof.week.diagnose import diagnose_oracle_gap
from fpl_dof.week.oracle import solve_hindsight_optimal
from fpl_dof.week.reconcile import reconcile
from fpl_dof.week.score_advice import (
    ModelRankScore,
    lineup_from_advice,
    recorded_free_transfers,
    score_model_recommendations,
)

log = get_logger(__name__)

EVALUATION_DIRECTORY = "evaluation"
PLAYED = "played"
#: Stamped on every stored evaluation (ORC-05). Bump it with any change to how a gameweek is
#: judged, the realised-points scorer (``rules/realised.py``) included: every Finished gameweek is
#: then evaluated again. 4: underlying xP and each strategy's per-player xP (ORC-12, D-37); 3: per
#: entry, deadline prices, the rules' armband; 2: D-36.
EVALUATION_VERSION = "4"
__all__ = ["EVALUATION_VERSION", "Evidence", "build_evaluation", "evaluated", "unready"]


@dataclass(frozen=True, slots=True)
class Evidence:
    """What the game recorded, from silver. The entry tables hold the owner's rows only."""

    season: str
    player_gameweek: pd.DataFrame | None
    players: pd.DataFrame | None
    fixtures: pd.DataFrame | None = None
    picks: pd.DataFrame | None = None
    entry_gameweeks: pd.DataFrame | None = None
    chips: pd.DataFrame | None = None
    transfers: pd.DataFrame | None = None
    gameweeks: pd.DataFrame | None = None
    price_history: pd.DataFrame | None = None

    def season_rows(self) -> pd.DataFrame:
        """This season's ``player_gameweek``: the table also holds backfilled seasons, whose
        gameweek numbers and player ids repeat this one's."""
        frame = self.player_gameweek
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["season", "gameweek", "player_id"])
        return frame[frame["season"] == self.season]

    def positions(self) -> dict[int, Position] | None:
        if self.players is None or "position" not in self.players.columns:
            return None
        return {as_int(r.player_id): Position(str(r.position)) for r in self.players.itertuples()}


def evaluation_path(layout: DataLayout, gameweek: int, entry_id: int | None) -> Path:
    """``<data>/ledger/evaluation/entry-4529900/gw05.json``: per entry, since the season log's row
    is that entry's, and named as the advice is. ``entry-none`` when no team is configured."""
    return layout.ledger / EVALUATION_DIRECTORY / f"entry-{entry_id}" / f"gw{gameweek:02d}.json"


def read_evaluations(layout: DataLayout, entry_id: int | None) -> dict[int, dict[str, Any]]:
    """Every evaluation made for ``entry_id`` stamped with :data:`EVALUATION_VERSION`, by gameweek.

    Another entry's never counts: it is in another directory, and a file whose own ``entry_id``
    is not this one is skipped. An unreadable file counts as not evaluated, logged: the step runs
    again rather than the gameweek being judged on nothing (DP-15).
    """
    directory = evaluation_path(layout, 0, entry_id).parent
    done: dict[int, dict[str, Any]] = {}
    for path in sorted(directory.glob("gw*.json")) if directory.is_dir() else ():
        try:
            gameweek = int(path.stem.removeprefix("gw"))
            body = json.loads(path.read_text(encoding="utf-8"))
            stamp = body.get("evaluation_version"), body.get("entry_id")
        except (ValueError, OSError, AttributeError) as exc:
            log.warning("evaluation.unreadable", extra={"path": str(path), "detail": str(exc)})
            continue
        if stamp == (EVALUATION_VERSION, entry_id):
            done[gameweek] = body
    return done


def evaluated(layout: DataLayout, entry_id: int | None) -> frozenset[int]:
    """The gameweeks evaluated for ``entry_id`` and stamped with :data:`EVALUATION_VERSION`."""
    return frozenset(read_evaluations(layout, entry_id))


def record_evaluation(layout: DataLayout, evaluation: Mapping[str, Any]) -> Path:
    path = evaluation_path(layout, int(evaluation["gameweek"]), evaluation["entry_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    log.info("evaluation.recorded", extra={"gameweek": evaluation["gameweek"], "path": str(path)})
    return path


def unready(
    gameweek: int, evidence: Evidence, *, entry_id: int | None, lagging_share: float
) -> str | None:
    """Why ``gameweek`` cannot be judged yet, or ``None`` when it can.

    An evaluation is kept, so it waits for complete evidence rather than judging once on a partial
    table: every player whose club played has his row (the ``player_gameweek_current`` gate's test,
    at ``quality.maximum_lagging_player_share``), and, with a team configured, the game has scored
    the owner's gameweek and silver holds his picks for it, so a degraded entry ingest never stores
    ``log: null`` for good. Only an entry the game shows starting later (history for a later
    gameweek, none for this one) is judged without them.
    """
    rows = evidence.season_rows()
    if rows.empty or not (rows["gameweek"] == gameweek).any():
        return f"no player_gameweek rows for GW{gameweek} yet"
    if evidence.fixtures is not None:
        lagging, expected, _ = lagging_players(rows, evidence.fixtures, gameweek)
        if expected and lagging / expected > lagging_share:
            return f"{lagging} of {expected} players have no GW{gameweek} row yet"
    if entry_id is None:
        return None
    history = evidence.entry_gameweeks
    started_later = (
        history is not None
        and not history.empty
        and bool(((history["entry_id"] == entry_id) & (history["gameweek"] > gameweek)).any())
    )
    if _owner_rows(history, entry_id, gameweek).empty:
        return None if started_later else f"the game has not scored the owner's GW{gameweek} yet"
    if _owner_rows(evidence.picks, entry_id, gameweek).empty:
        return f"silver holds no picks for the owner's GW{gameweek} yet"
    return None


def build_evaluation(
    gameweek: int,
    *,
    evidence: Evidence,
    advice: Mapping[str, Any] | None,
    predictions: Mapping[str, pd.DataFrame],
    rules: GameRules,
    entry_id: int | None,
    as_of: dt.datetime,
    run_id: str,
) -> dict[str, Any]:
    """The evaluation of one Finished gameweek: each strategy's xP accuracy and realised points, and
    the season log's row for the owner (``None`` without picks for this gameweek)."""
    rows = evidence.season_rows()
    this_week = rows[rows["gameweek"] == gameweek]
    perfs = performances(this_week, positions=evidence.positions())
    underlying = underlying_points(this_week, rules)
    lineups = _strategy_lineups(advice)
    picks = _owner_rows(evidence.picks, entry_id, gameweek)
    played = _played(picks.sort_values("slot")) if not picks.empty else None
    if played is not None and played["starting"]:
        lineups = {PLAYED: _played_lineup(played, gameweek, evidence, entry_id), **lineups}
    rankings = score_model_recommendations(lineups, perfs, rules) if perfs and lineups else []

    accuracy = _xp_accuracy(predictions, perfs)
    actual = {
        r.model_name: _actual(
            r, underlying_team_points(lineups[r.model_name], r.score, underlying, rules)
        )
        for r in rankings
        if r.model_name != PLAYED
    }
    strategies = {
        sid: {"actual": actual.get(sid), "xp_accuracy": accuracy.get(sid)}
        for sid in sorted(set(actual) | set(accuracy))
    }
    row = None
    if played is not None and entry_id is not None:
        row = {
            "gameweek": gameweek,
            "played": played,
            "score": _scores_by_gameweek(evidence.entry_gameweeks).get(gameweek),
            "chip": _chips_by_gameweek(evidence.chips).get(gameweek),
            "advised": _advised(advice),
            "reconciliation": _reconciliation(gameweek, entry_id, advice, evidence.picks),
            "hindsight": _hindsight(
                gameweek,
                lineups,
                perfs,
                rankings,
                evidence,
                rules,
                entry_id,
                predictions,
                underlying,
            )
            if perfs
            else None,
        }
    return {
        "gameweek": gameweek,
        "season": evidence.season,
        "evaluation_version": EVALUATION_VERSION,
        "evaluated_at": as_of.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "entry_id": entry_id,
        "log": row,
        "strategies": strategies,
    }


def _owner_rows(frame: pd.DataFrame | None, entry_id: int | None, gameweek: int) -> pd.DataFrame:
    if frame is None or frame.empty or entry_id is None:
        return pd.DataFrame(columns=["gameweek", "slot", "player_id"])
    return frame[(frame["entry_id"] == entry_id) & (frame["gameweek"] == gameweek)]


def _actual(ranked: ModelRankScore, underlying: float) -> dict[str, Any]:
    """A strategy's realised points, in ``models.json``'s ``actual`` shape, with its XI's underlying
    points before hits (ORC-12): its forecast error is its xP less them, its luck its points less
    them, so xP less points is the forecast error less the luck."""
    score = ranked.score
    return {
        "points": float(score.net_points),
        "points_before_hits": float(score.points_before_hits),
        "hit_points": float(score.hit_points),
        "n_autosubs": len(score.autosubs_in),
        "vice_used": score.vice_used,
        "armband_points": float(score.armband_points),
        "underlying_points": round(underlying, 2),
        "forecast_error": round(score.expected_points - underlying, 2),
        "luck": round(score.points_before_hits - underlying, 2),
    }


def _xp_accuracy(
    predictions: Mapping[str, pd.DataFrame], perfs: Mapping[int, PlayerPerformance]
) -> dict[str, dict[str, Any]]:
    """Each strategy's all-player MAE of its recorded xP against the points scored.

    The population is every player all the recorded strategies priced, so the strategies are
    compared on the same players; one with no fixture or no minutes scored nothing, and stays in.
    """
    if not predictions or not perfs:
        return {}
    common = set.intersection(*(set(f["player_id"].astype(int)) for f in predictions.values()))
    accuracy: dict[str, dict[str, Any]] = {}
    for key, frame in predictions.items():
        sid = resolve_alias(key) or key
        rows = frame[frame["player_id"].astype(int).isin(common)]
        points = rows["player_id"].astype(int).map(lambda p: perfs[p].points if p in perfs else 0)
        error = rows["xp_next"].astype(float) - points
        accuracy[sid] = {
            "mae": round(float(error.abs().mean()), 4) if len(rows) else None,
            "bias": round(float(error.mean()), 4) if len(rows) else None,
            "players": len(rows),
        }
    return accuracy


def _strategy_lineups(advice: Mapping[str, Any] | None) -> dict[str, Lineup]:
    """Every strategy's advice of record as a scorable lineup: the champion's is the top-level
    record, every other strategy's its entry under ``models``."""
    if advice is None:
        return {}
    lineups: dict[str, Lineup] = {}
    free = recorded_free_transfers(advice)
    advised = advice.get("advised")
    if isinstance(advised, Mapping):
        rec = advice.get("recommendation")
        rec = rec if isinstance(rec, Mapping) else None
        lineup = lineup_from_advice(
            advised,
            transfers_made=int((rec or {}).get("transfers") or 0),
            free_transfers=free,
            recommendation=rec,
        )
        if lineup is not None:
            lineups[champion().id] = lineup
    models = advice.get("models")
    for key, entry in (models if isinstance(models, Mapping) else {}).items():
        if not isinstance(entry, Mapping) or (
            entry.get("role") == "champion" and champion().id in lineups
        ):
            continue  # the champion's advice is the top-level record, scored above
        own = entry.get("advised")
        if not isinstance(own, Mapping):
            continue
        lineup = lineup_from_advice(
            own,
            transfers_made=int(entry.get("transfers") or 0),
            free_transfers=free,
            recommendation=entry.get("recommendation"),
        )
        if lineup is not None:
            lineups[resolve_alias(key) or key] = lineup  # legacy keys in recorded advice
    return lineups


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


def _played_lineup(
    played: Mapping[str, Any], gameweek: int, evidence: Evidence, entry_id: int | None
) -> Lineup:
    """The owner's team as the game recorded it: its chip and its hit (D-30).

    The game records both armbands for every submitted team, so picks without one are incomplete
    and the gameweek is not judged on them; the evaluation fails, said, and is tried again.
    """
    starting = tuple(played["starting"])
    bench = tuple(played["bench_order"])
    if played["captain"] is None or played["vice_captain"] is None:
        raise ValueError(f"the owner's GW{gameweek} picks name no captain or no vice-captain")
    score = _scores_by_gameweek(_owner_rows(evidence.entry_gameweeks, entry_id, gameweek))
    return Lineup(
        starting=starting,
        bench_order=bench[1:],
        bench_gkp=bench[0] if bench else None,
        captain=played["captain"],
        vice_captain=played["vice_captain"],
        chip=_chips_by_gameweek(evidence.chips).get(gameweek),
        hit_points=(score.get(gameweek) or {}).get("transfers_cost"),
    )


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
    picks: pd.DataFrame | None,
) -> dict[str, Any] | None:
    if recorded is None or picks is None or not isinstance(recorded.get("advised"), Mapping):
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


def _at_deadline(evidence: Evidence, gameweek: int) -> pd.DataFrame:
    """Every player as he stood at ``gameweek``'s deadline: his club that gameweek, and his price
    as of the deadline (D-31).

    The price is the last ``price_history`` observation at or before the deadline (PIPE-06). A
    player it has none for falls back, with a warning, to the price FPL recorded for the
    gameweek's fixture, which a change between the deadline and kick-off can have moved by a step.
    A player with no row at all (his club blanked, or he was not yet registered) keeps the current
    table's club and price, and only enters the pool if he was held.
    """
    rows = evidence.season_rows()
    rows = rows[rows["gameweek"] == gameweek]
    if "kickoff_time" in rows.columns:
        rows = rows.sort_values("kickoff_time")
    then = rows.drop_duplicates("player_id").set_index("player_id")
    players = (evidence.players if evidence.players is not None else pd.DataFrame()).copy()
    for column in ("team_id", "price"):
        if column in then.columns:
            known = players["player_id"].map(then[column])
            players[column] = known.where(known.notna(), players[column])
    players["has_row"] = players["player_id"].isin(then.index)

    observed = _prices_at(evidence, gameweek)
    at_deadline = players["player_id"].map(observed)
    fallback = players["has_row"] & at_deadline.isna()
    if fallback.any():
        log.warning(
            "evaluation.price_not_observed_at_deadline",
            extra={"gameweek": gameweek, "players": int(fallback.sum())},
        )
    players["price"] = at_deadline.where(at_deadline.notna(), players["price"])
    return players


def _prices_at(evidence: Evidence, gameweek: int) -> pd.Series:
    """Player id -> the last price ``price_history`` observed at or before ``gameweek``'s deadline;
    empty without the history or the deadline."""
    history, gameweeks = evidence.price_history, evidence.gameweeks
    if history is None or history.empty or gameweeks is None or gameweeks.empty:
        return pd.Series(dtype=float)
    deadline = gameweeks.loc[gameweeks["gameweek"] == gameweek, "deadline_time"]
    if deadline.empty:
        return pd.Series(dtype=float)
    seen = history[history["observed_at"] <= deadline.iloc[0]].sort_values("observed_at")
    prices: pd.Series = seen.drop_duplicates("player_id", keep="last").set_index("player_id")[
        "price"
    ]
    return prices


def _hindsight(
    gameweek: int,
    lineups: Mapping[str, Lineup],
    perfs: Mapping[int, PlayerPerformance],
    rankings: list[ModelRankScore],
    evidence: Evidence,
    rules: GameRules,
    entry_id: int | None,
    predictions: Mapping[str, pd.DataFrame],
    underlying: Mapping[int, float],
) -> dict[str, Any]:
    """The rankings, and the best the owner could have done from the squad he held at the deadline,
    on that gameweek's real points, prices, clubs and bank (D-31)."""
    ranked = [r.as_dict() for r in rankings]
    picks = evidence.picks
    before = (
        picks[(picks["entry_id"] == entry_id) & (picks["gameweek"] < gameweek)]
        if picks is not None and not picks.empty
        else pd.DataFrame()
    )
    if before.empty:
        return _no_optimal(ranked, "no squad was held before this gameweek")
    players = _at_deadline(evidence, gameweek)
    bank = _owner_rows(evidence.entry_gameweeks, entry_id, gameweek - 1)
    earlier = {
        name: None if frame is None else frame[frame["gameweek"] < gameweek]
        for name, frame in (("transfers", evidence.transfers), ("chips", evidence.chips))
    }
    try:
        state = load_squad_state(
            entry_config=EntryConfig(team_id=entry_id),
            rules=rules,
            players=players,
            next_gameweek=gameweek,
            picks=before,
            transfers=earlier["transfers"],
            entry=bank[["bank"]] if "bank" in bank.columns else None,
            chips=earlier["chips"],
            gameweek_prices=gameweek_price_index(evidence.player_gameweek, evidence.season),
        )
    except SquadStateError as exc:
        return _no_optimal(ranked, str(exc))

    actuals = {pid: perf.points for pid, perf in perfs.items()}
    pool = players[players["has_row"] | players["player_id"].isin(state.player_ids())].copy()
    pool["now_cost"] = pool["price"]
    pool["xp_next"] = pool["player_id"].map(actuals).fillna(0.0)
    pool["xp_horizon"] = pool["xp_next"]
    pool["start_probability"] = 1.0

    # Each strategy's own pre-deadline xP for every player it priced (D-37).
    models_xp = {
        resolve_alias(key) or key: dict(
            zip(frame["player_id"].astype(int), frame["xp_next"].astype(float), strict=True)
        )
        for key, frame in predictions.items()
    }
    models_captains = {name: lineup.captain for name, lineup in lineups.items()}
    try:
        optimal = solve_hindsight_optimal(gameweek=gameweek, state=state, pool=pool, rules=rules)
        diagnostics = diagnose_oracle_gap(
            optimal=optimal.optimal_overall,
            player_actuals=actuals,
            models_xp=models_xp,
            models_captains=models_captains,
            player_underlying=underlying,
        )
    except Exception as exc:
        reason = f"the hindsight optimum could not be solved: {type(exc).__name__}: {exc}"
        log.warning("evaluation.no_optimum", extra={"gameweek": gameweek, "reason": reason})
        return _no_optimal(ranked, reason)
    return {
        "rankings": ranked,
        "optimal": optimal.as_dict(),
        "diagnostics": [d.as_dict() for d in diagnostics],
    }


def _no_optimal(ranked: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """The rankings need no squad; only the optimum does, and it is never invented."""
    return {
        "rankings": ranked,
        "optimal": None,
        "optimal_unavailable_reason": reason,
        "diagnostics": [],
    }
