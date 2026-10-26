"""What starts a pipeline run, and what a run stamps on its advice (ORC-02, ORC-03).

The one home of the vocabulary (DP-14). It imports nothing, so config, the sources, the schedule
guard and the dispatch script all read it without crossing a layer. JSON Schema cannot import it:
``test_dispatch.py`` holds every contract schema's ``trigger`` pattern to :data:`TRIGGER_STAMP`.
"""

from __future__ import annotations

#: The change kind a gameweek in play moves: a matchday done, the gameweek marked finished, the
#: gameweek marked data-checked (LIVE-02). A kick-off, a goal or a score moves nothing.
RESULTS = "results"

#: Everything that starts a pipeline run: a price; a status or news line; a fixture's kick-off or
#: gameweek; a match of the Open gameweek priced for the first time; a result.
CHANGE_KINDS: tuple[str, ...] = ("prices", "status", "fixtures", "odds", RESULTS)

#: What may start a pipeline run, as `pipeline.yml`'s `trigger` input names it. The cron tick sends
#: none. `schedule` is the daily refresh the slow ingest dispatches; `change` carries the change
#: manifest's kinds; `day-before` must publish a fresh contract.
MANUAL, SCHEDULE, CHANGE, DAY_BEFORE = "manual", "schedule", "change", "day-before"
TRIGGERS: tuple[str, ...] = (MANUAL, SCHEDULE, CHANGE, DAY_BEFORE)

_KIND = "|".join(CHANGE_KINDS)
#: What a run stamps on its advice: its trigger, a change as ``change:`` and the kinds that moved.
TRIGGER_STAMP = (
    f"^({'|'.join(t for t in TRIGGERS if t != CHANGE)}|{CHANGE}:({_KIND})(,({_KIND}))*)$"
)

__all__ = [
    "CHANGE",
    "CHANGE_KINDS",
    "DAY_BEFORE",
    "MANUAL",
    "RESULTS",
    "SCHEDULE",
    "TRIGGERS",
    "TRIGGER_STAMP",
]
