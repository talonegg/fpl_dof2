"""What a lineup actually scored: the one realised-points scorer (ORC-04).

Every realised score in the repository comes from :func:`score_lineup` — the season log, the models
comparison and the chip replay — so the game's substitution, armband, chip and hit rules are written
once. It is pinned against FPL's own published scores by the corpus in
``contracts/conformance/realised/`` (DL-39), which is the test that the rules below are the game's.

- **Auto-substitutions**: a starter who did not play (no minutes in any fixture, which includes a
  player whose club had no fixture) is replaced by the reserve goalkeeper if he is the goalkeeper,
  otherwise by the first outfield substitute, in bench order, who played and whose arrival keeps
  the XI within the formation bounds.
- **Double gameweeks**: a performance is the player's whole gameweek, every fixture summed.
- **The armband** multiplies the captain, or the vice-captain if the captain did not play.
- **Chips**: one that lets the bench score fields all fifteen and makes no substitutions; one that
  sets the armband's multiplier overrides it; one that makes transfers free charges no hit.
- **Hits**: the recorded hit if there is one, else the transfers beyond the free ones at the
  configured cost.

Pure (DP-03). No value is a literal: every number and every chip's effect comes from
:class:`~fpl_dof.rules.models.GameRules` (Invariant 2).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from fpl_dof.frames import as_int
from fpl_dof.rules.models import GameRules, Position


@dataclass(frozen=True, slots=True)
class PlayerPerformance:
    """One player's whole gameweek: minutes and points over every fixture he had."""

    player_id: int
    position: Position
    minutes: int
    points: int


@dataclass(frozen=True, slots=True)
class Lineup:
    """A submitted (or advised) team for one gameweek, in FPL's pick order."""

    starting: tuple[int, ...]
    bench_order: tuple[int, ...]
    """The outfield substitutes, first choice first. The reserve goalkeeper is ``bench_gkp``."""

    bench_gkp: int | None
    captain: int
    vice_captain: int
    chip: str | None = None
    transfers_made: int = 0
    free_transfers: int | None = None  # None: not recorded, so no hit is invented
    hit_points: int | None = None  # the hit actually recorded; preferred over recomputing it
    expected_points: float = 0.0


@dataclass(frozen=True, slots=True)
class ScoredLineup:
    final_starting: tuple[int, ...]
    points_before_hits: int
    hit_points: int
    net_points: int
    captain_id: int
    vice_used: bool
    armband_points: int
    autosubs_in: tuple[int, ...]
    autosubs_out: tuple[int, ...]
    expected_points: float
    prediction_delta: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_starting": list(self.final_starting),
            "points_before_hits": self.points_before_hits,
            "hit_points": self.hit_points,
            "net_points": self.net_points,
            "captain_id": self.captain_id,
            "vice_used": self.vice_used,
            "armband_points": self.armband_points,
            "autosubs_in": list(self.autosubs_in),
            "autosubs_out": list(self.autosubs_out),
            "expected_points": self.expected_points,
            "prediction_delta": self.prediction_delta,
        }


def score_lineup(
    lineup: Lineup,
    perfs: Mapping[int, PlayerPerformance],
    rules: GameRules,
) -> ScoredLineup:
    """Score one lineup against the gameweek's performances. A player absent from ``perfs`` did
    not play; build ``perfs`` with :func:`performances` and its ``positions`` so his position is
    still known to the formation check."""
    chips = rules.chips

    def played(pid: int) -> bool:
        perf = perfs.get(pid)
        return perf is not None and perf.minutes > 0

    starting = list(lineup.starting)
    subs_in: list[int] = []
    subs_out: list[int] = []
    if lineup.chip in chips.bench_scores_with:
        fielded = [
            *starting,
            *([lineup.bench_gkp] if lineup.bench_gkp is not None else []),
            *lineup.bench_order,
        ]
    else:
        gkp = lineup.bench_gkp
        for i, pid in enumerate(starting):
            if played(pid):
                continue
            perf = perfs.get(pid)
            if perf is not None and perf.position == Position.GKP:
                if gkp is not None and played(gkp):
                    starting[i] = gkp
                    subs_out.append(pid)
                    subs_in.append(gkp)
                continue
            for sub in lineup.bench_order:
                if sub in subs_in or not played(sub):
                    continue
                trial = [*starting[:i], sub, *starting[i + 1 :]]
                if _formation_ok(trial, perfs, rules):
                    starting[i] = sub
                    subs_out.append(pid)
                    subs_in.append(sub)
                    break
        fielded = starting

    multiplier = chips.armband(lineup.chip)
    vice_used = False
    captain_id = lineup.captain
    if not played(lineup.captain) and played(lineup.vice_captain):
        captain_id, vice_used = lineup.vice_captain, True
    captain_points = perfs[captain_id].points if played(captain_id) else 0

    base = sum(perfs[pid].points for pid in fielded if pid in perfs)
    points_before_hits = base + captain_points * (multiplier - 1)
    hit_points = _hit(lineup, rules)
    net_points = points_before_hits - hit_points
    return ScoredLineup(
        final_starting=tuple(starting),
        points_before_hits=points_before_hits,
        hit_points=hit_points,
        net_points=net_points,
        captain_id=captain_id,
        vice_used=vice_used,
        armband_points=captain_points * multiplier,
        autosubs_in=tuple(subs_in),
        autosubs_out=tuple(subs_out),
        expected_points=lineup.expected_points,
        prediction_delta=round(net_points - lineup.expected_points, 2),
    )


def _formation_ok(
    xi: Iterable[int], perfs: Mapping[int, PlayerPerformance], rules: GameRules
) -> bool:
    counts = Counter(perfs[p].position for p in xi if p in perfs)
    squad = rules.squad
    return all(
        squad.formation_min[pos] <= counts.get(pos, 0) <= squad.formation_max[pos]
        for pos in Position
    )


def _hit(lineup: Lineup, rules: GameRules) -> int:
    if lineup.hit_points is not None:
        return lineup.hit_points
    if lineup.chip in rules.chips.transfers_free_with or lineup.free_transfers is None:
        return 0
    extra = max(0, lineup.transfers_made - lineup.free_transfers)
    return extra * abs(rules.transfers.extra_transfer_cost)


def performances(
    gameweek_rows: pd.DataFrame,
    *,
    key: str = "player_id",
    positions: Mapping[int, Position] | None = None,
) -> dict[int, PlayerPerformance]:
    """One gameweek's ``player_gameweek`` rows as per-player performances, keyed by ``key``.

    The table has one row per fixture, so a double gameweek's points and minutes are summed. A
    player in ``positions`` with no row had no fixture: he is entered with no minutes, so the
    formation check still knows his position.
    """
    perfs: dict[int, PlayerPerformance] = {
        pid: PlayerPerformance(pid, position, 0, 0) for pid, position in (positions or {}).items()
    }
    seen: set[int] = set()
    for r in gameweek_rows.itertuples():
        pid = as_int(getattr(r, key))
        raw = getattr(r, "position", None)
        try:
            position = Position(str(raw))
        except ValueError:
            # A guessed position would decide auto-substitutions silently: a data fault, said.
            raise ValueError(f"player {pid} has no position the rules know: {raw!r}") from None
        minutes = as_int(getattr(r, "minutes", 0))
        points = as_int(getattr(r, "total_points", 0))
        if pid in seen:
            minutes += perfs[pid].minutes
            points += perfs[pid].points
        seen.add(pid)
        perfs[pid] = PlayerPerformance(pid, position, minutes, points)
    return perfs
