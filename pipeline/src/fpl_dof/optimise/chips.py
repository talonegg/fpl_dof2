"""E4-S3 — chips, by enumeration rather than decision variables.

Chip timing interacts with transfers, so it cannot be decided by a heuristic sitting to one side of
the optimiser. It does **not** follow that chips have to be MILP variables. Per
[DL-15](../../../../docs/planning/00-decision-log.md) and Design §6.3, the primary approach is
enumeration: list the plausible ``(chip, gameweek)`` assignments in the horizon, solve the ordinary
transfer MILP conditional on each, take the best and keep the runners-up.

Three reasons, and the third is the one that matters most:

* **Tractable** — Free Hit stops needing a parallel squad variable set inside one monolithic model.
* **Parallel** — the scenarios are independent, which suits CI.
* **Explainable** — "Free Hit in GW18 beats GW17 by 4.1 points and beats not playing it by 9.3" is a
  sentence you can argue with. A chip binary flipping inside a solver is not, and chip timing is the
  recommendation most likely to be challenged.

**Expiry is read, never assumed.** "Set one expires at GW19" is true this season and is exactly the
kind of fact that quietly stops being true (Invariant 2), so the windows come from the chip table,
which comes from the game's own published chip windows.

This module **supersedes** the blunt E2-S7 expiry tracker in :mod:`fpl_dof.week.alerts`; it does not
replace it. That tracker exists precisely so that a dated, irreversible loss never depends on this
epic landing on time, and it keeps running.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from fpl_dof.config.models import ChipConfig
from fpl_dof.frames import as_int

#: Chips that change how a gameweek is *scored*, as opposed to how it is transferred.
SCORING_CHIPS = frozenset({"bboost", "3xc"})
#: Chips that change the transfer rules for a gameweek.
TRANSFER_CHIPS = frozenset({"wildcard", "freehit"})

CHIP_LABELS = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
}


def chip_label(name: str) -> str:
    return CHIP_LABELS.get(name, name)


@dataclass(frozen=True, slots=True)
class ChipWindow:
    """One chip and the gameweeks it may be played in, as the game publishes them."""

    name: str
    start_gameweek: int
    stop_gameweek: int

    def covers(self, gameweek: int) -> bool:
        return self.start_gameweek <= gameweek <= self.stop_gameweek


@dataclass(frozen=True, slots=True)
class ChipScenario:
    """One ``(chip, gameweek)`` assignment to solve the transfer MILP against.

    At most one chip per gameweek, and — deliberately — at most one chip **per scenario**. Over a
    5-8 gameweek horizon, plans that play two chips in the same window are rare, dominated by the
    single-chip plans they contain, and multiply the enumeration by the square of its size. The
    empty assignment (play nothing) is always enumerated and is always a first-class candidate.
    """

    assignments: tuple[tuple[int, str], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.assignments

    def chip_in(self, gameweek: int) -> str | None:
        for week, name in self.assignments:
            if week == gameweek:
                return name
        return None

    @property
    def label(self) -> str:
        if self.is_empty:
            return "no chip"
        return ", ".join(f"{chip_label(name)} in GW{week}" for week, name in self.assignments)

    @property
    def chips(self) -> tuple[str, ...]:
        return tuple(name for _, name in self.assignments)


@dataclass(frozen=True, slots=True)
class GameweekShape:
    """How many fixtures each club has in a gameweek. The thing chips are actually timed against."""

    gameweek: int
    fixtures_by_team: Mapping[int, int]

    @property
    def is_double(self) -> bool:
        return any(count >= 2 for count in self.fixtures_by_team.values())

    @property
    def is_blank(self) -> bool:
        return any(count == 0 for count in self.fixtures_by_team.values())

    @property
    def teams_doubling(self) -> tuple[int, ...]:
        return tuple(sorted(t for t, n in self.fixtures_by_team.items() if n >= 2))

    @property
    def teams_blanking(self) -> tuple[int, ...]:
        return tuple(sorted(t for t, n in self.fixtures_by_team.items() if n == 0))

    def mean_fixtures(self, team_ids: Iterable[int]) -> float:
        teams = list(team_ids)
        if not teams:
            return 0.0
        return sum(self.fixtures_by_team.get(int(t), 0) for t in teams) / len(teams)


@dataclass(frozen=True, slots=True)
class ChipCalendarEntry:
    """One chip, one gameweek, and why that gameweek is or is not a window."""

    chip: str
    gameweek: int
    is_double: bool
    is_blank: bool
    teams_doubling: tuple[int, ...]
    teams_blanking: tuple[int, ...]
    expires_gameweek: int
    gameweeks_until_expiry: int
    note: str

    def as_dict(self) -> dict[str, object]:
        return {
            "chip": self.chip,
            "chip_label": chip_label(self.chip),
            "gameweek": self.gameweek,
            "is_double": self.is_double,
            "is_blank": self.is_blank,
            "teams_doubling": list(self.teams_doubling),
            "teams_blanking": list(self.teams_blanking),
            "expires_gameweek": self.expires_gameweek,
            "gameweeks_until_expiry": self.gameweeks_until_expiry,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ChipCalendar:
    """The long-range view: which windows exist, and how long is left to use them."""

    from_gameweek: int
    entries: tuple[ChipCalendarEntry, ...] = ()
    expiring: tuple[tuple[str, int], ...] = ()
    """Unused chips and the gameweek each expires at. Read from the chip table, never assumed."""

    unavailable: tuple[str, ...] = field(default=())
    """Chips already played, or with no remaining window."""

    def for_chip(self, chip: str) -> tuple[ChipCalendarEntry, ...]:
        return tuple(entry for entry in self.entries if entry.chip == chip)

    def as_dict(self) -> dict[str, object]:
        return {
            "from_gameweek": self.from_gameweek,
            "entries": [entry.as_dict() for entry in self.entries],
            "expiring": [
                {"chip": chip, "chip_label": chip_label(chip), "expires_gameweek": gameweek}
                for chip, gameweek in self.expiring
            ],
            "unavailable": list(self.unavailable),
        }


def gameweek_shapes(fixtures: pd.DataFrame, team_ids: Iterable[int]) -> dict[int, GameweekShape]:
    """Fixtures per club per gameweek — the raw material for double and blank detection.

    Built from the fixture table rather than from a published "is this a double" flag, because no
    such flag exists: a double gameweek *is* two rows for the same club, and a blank *is* the
    absence of a row. Clubs with no fixture are filled in explicitly, since an absent row is exactly
    the signal that would otherwise be invisible.
    """
    teams = sorted({int(t) for t in team_ids})
    shapes: dict[int, dict[int, int]] = {}
    if fixtures.empty:
        return {}

    scheduled = fixtures[fixtures["gameweek"].notna()]
    for row in scheduled.itertuples():
        gameweek = as_int(row.gameweek)
        counts = shapes.setdefault(gameweek, dict.fromkeys(teams, 0))
        for team in (as_int(row.home_team_id), as_int(row.away_team_id)):
            if team in counts:
                counts[team] = counts[team] + 1

    return {
        gameweek: GameweekShape(gameweek=gameweek, fixtures_by_team=counts)
        for gameweek, counts in sorted(shapes.items())
    }


def chip_windows(chips: pd.DataFrame | None) -> tuple[ChipWindow, ...]:
    """Every chip window the game publishes, as data."""
    if chips is None or chips.empty:
        return ()
    windows = [
        ChipWindow(
            name=str(row.name_),
            start_gameweek=as_int(row.start_event),
            stop_gameweek=as_int(row.stop_event),
        )
        for row in chips.rename(columns={"name": "name_"}).itertuples()
    ]
    return tuple(sorted(windows, key=lambda w: (w.start_gameweek, w.name)))


def available_chips(
    windows: Sequence[ChipWindow],
    *,
    chips_used: Iterable[str],
    gameweek: int,
) -> dict[str, ChipWindow]:
    """Chips that can still be played at or after ``gameweek``, and the window each falls in.

    A chip already used is gone. A chip whose window has closed is gone — **this is where the GW19
    expiry of set 1 is enforced rather than advised**: once ``gameweek`` passes a set-1 window's
    ``stop_event``, that window stops being returned and no scenario can be built on it.
    """
    used = list(chips_used)
    remaining: dict[str, ChipWindow] = {}
    for window in windows:
        if window.stop_gameweek < gameweek:
            continue
        if used.count(window.name) > _windows_before(windows, window):
            continue
        if window.name in remaining:
            continue
        remaining[window.name] = window
    return remaining


def _windows_before(windows: Sequence[ChipWindow], window: ChipWindow) -> int:
    """How many earlier windows the same chip had — i.e. how many uses this one is the (n+1)th of.

    Chips come in sets: the same name appears once per set with a different window. A manager who
    has played ``wildcard`` once has used the first set's; the second set's is still available, and
    the count is what tells the two apart without hardcoding "there are two sets".
    """
    return sum(
        1
        for other in windows
        if other.name == window.name and other.start_gameweek < window.start_gameweek
    )


def enumerate_scenarios(
    *,
    horizon: Sequence[int],
    windows: Sequence[ChipWindow],
    chips_used: Iterable[str],
    shapes: Mapping[int, GameweekShape],
    squad_team_ids: Iterable[int],
    config: ChipConfig,
) -> tuple[ChipScenario, ...]:
    """The ``(chip, gameweek)`` assignments worth solving, always including "play nothing".

    Pruned before it is solved, because most of the grid is not a candidate:

    * a Bench Boost in a gameweek where the squad's clubs average under one fixture is not a bet,
      it is a forfeit;
    * a chip outside its published window cannot be played at all;
    * an override may force a chip into a gameweek, or forbid it from one (E4-S5).
    """
    if not horizon:
        return (ChipScenario(),)

    first = int(horizon[0])
    remaining = available_chips(windows, chips_used=chips_used, gameweek=first)
    teams = list(squad_team_ids)

    scenarios: list[ChipScenario] = [ChipScenario()]
    forced = {str(k): int(v) for k, v in config.force_chip_gameweek.items()}
    forbidden = {
        str(k): {int(v) for v in weeks} for k, weeks in config.forbid_chip_gameweeks.items()
    }

    for chip, window in sorted(remaining.items()):
        for gameweek in horizon:
            gameweek = int(gameweek)
            if not window.covers(gameweek):
                continue
            if gameweek in forbidden.get(chip, set()):
                continue
            if chip in forced and forced[chip] != gameweek:
                continue
            shape = shapes.get(gameweek)
            if (
                chip == "bboost"
                and shape is not None
                and shape.mean_fixtures(teams) < config.bench_boost_minimum_fixtures
            ):
                continue
            scenarios.append(ChipScenario(assignments=((gameweek, chip),)))

    # A forced chip is an instruction, not a preference: once one is forced, the do-nothing
    # scenario is no longer a legal answer and must not be allowed to win by default.
    forced_in_horizon = {chip for chip, week in forced.items() if week in {int(w) for w in horizon}}
    if forced_in_horizon:
        scenarios = [
            scenario for scenario in scenarios if forced_in_horizon.issubset(set(scenario.chips))
        ] or [ChipScenario()]

    return tuple(scenarios[: config.max_scenarios])


def build_calendar(
    *,
    from_gameweek: int,
    windows: Sequence[ChipWindow],
    chips_used: Iterable[str],
    shapes: Mapping[int, GameweekShape],
    config: ChipConfig,
) -> ChipCalendar:
    """Project likely chip windows across the rest of the season (FR-20).

    The rolling horizon decides *now*; this stops *now* from ruining *later*. It is deliberately
    coarse — fixture structure only, no forecast — because a projection twenty gameweeks out that
    leans on an expected-points model is a projection with a false precision, and DL-21 has already
    said what this project's forecast is worth at the head of a ranking.
    """
    used = list(chips_used)
    remaining = available_chips(windows, chips_used=used, gameweek=from_gameweek)
    entries: list[ChipCalendarEntry] = []
    last = from_gameweek + config.calendar_gameweeks

    for chip, window in sorted(remaining.items()):
        first = max(from_gameweek, window.start_gameweek)
        for gameweek in range(first, min(last, window.stop_gameweek) + 1):
            shape = shapes.get(gameweek)
            if shape is None:
                continue
            if not _is_window(chip, shape):
                continue
            entries.append(
                ChipCalendarEntry(
                    chip=chip,
                    gameweek=gameweek,
                    is_double=shape.is_double,
                    is_blank=shape.is_blank,
                    teams_doubling=shape.teams_doubling,
                    teams_blanking=shape.teams_blanking,
                    expires_gameweek=window.stop_gameweek,
                    gameweeks_until_expiry=window.stop_gameweek - from_gameweek,
                    note=_calendar_note(chip, shape, window, from_gameweek),
                )
            )

    expiring = tuple(sorted((chip, window.stop_gameweek) for chip, window in remaining.items()))
    unavailable = tuple(sorted({window.name for window in windows} - set(remaining)))
    return ChipCalendar(
        from_gameweek=from_gameweek,
        entries=tuple(entries),
        expiring=expiring,
        unavailable=unavailable,
    )


def _is_window(chip: str, shape: GameweekShape) -> bool:
    """Whether a gameweek's fixture structure makes it interesting for this chip.

    Doubles favour the chips that multiply what you own — Bench Boost and Triple Captain — and
    blanks favour the chips that let you field a different squad. A gameweek that is neither is not
    a *window*; it is just a week, and listing every week would make the calendar unreadable, which
    is the same as not having one.
    """
    if chip in SCORING_CHIPS:
        return shape.is_double
    return shape.is_blank or shape.is_double


def _calendar_note(chip: str, shape: GameweekShape, window: ChipWindow, from_gameweek: int) -> str:
    parts: list[str] = []
    if shape.is_double:
        parts.append(f"{len(shape.teams_doubling)} club(s) play twice")
    if shape.is_blank:
        parts.append(f"{len(shape.teams_blanking)} club(s) have no fixture")
    left = window.stop_gameweek - from_gameweek
    parts.append(
        f"{chip_label(chip)} expires at the GW{window.stop_gameweek} deadline "
        f"({left} gameweek(s) away)"
    )
    return "; ".join(parts)


__all__ = [
    "CHIP_LABELS",
    "SCORING_CHIPS",
    "TRANSFER_CHIPS",
    "ChipCalendar",
    "ChipCalendarEntry",
    "ChipScenario",
    "ChipWindow",
    "GameweekShape",
    "available_chips",
    "build_calendar",
    "chip_label",
    "chip_windows",
    "enumerate_scenarios",
    "gameweek_shapes",
]
