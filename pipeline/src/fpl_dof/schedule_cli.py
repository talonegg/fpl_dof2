"""``fpl-dof-schedule`` — the guard the scheduled workflows ask before doing anything.

The effectful edge of :mod:`fpl_dof.week.schedule` (DP-03): load config, read one silver table,
work out how far away the next deadline is, and print the decision. It writes nothing, fetches
nothing, and never fails on missing data — a guard that errors out is a guard that stops the season.

A separate console script rather than a ``fpl-dof`` subcommand, on purpose. ``fpl-dof`` is a stage
runner: every invocation opens a run, allocates a run id and writes a manifest, all of which are
right for a stage and wrong for a read-only question asked ninety-six times a day. Keeping this off
that path also leaves the E0 code path CI exercises untouched (D-10).

Usage::

    fpl-dof-schedule                    # the full decision for both workflows, as JSON
    fpl-dof-schedule --decide fast      # prints `true` or `false`, for a workflow `if:`
    fpl-dof-schedule --decide pipeline

Nothing here knows it is running in CI. The workflow captures stdout and turns it into a step
output itself, so there is no CI-only branch anywhere in the pipeline source (NFR-09).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Sequence

import pandas as pd

from fpl_dof.config import Config, ConfigError, layout_for, load_config
from fpl_dof.paths import DataLayout
from fpl_dof.silver.store import read_table_optional
from fpl_dof.silver.tables import Table
from fpl_dof.week.deadline import NoDeadlineError, next_deadline
from fpl_dof.week.schedule import (
    MINUTES_PER_HOUR,
    fast_ingest_decision,
    pipeline_decision,
)

EXIT_OK = 0
EXIT_CONFIG_ERROR = 3

#: What ``--decide`` prints. Lower case because that is what a GitHub Actions ``if:`` expression
#: compares a string against, and a boolean rendered two ways is a bug waiting to happen.
TRUE = "true"
FALSE = "false"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpl-dof-schedule",
        description=(
            "Should the scheduled workflows do work at this moment? Reads the ingested gameweek "
            "table; writes nothing."
        ),
    )
    parser.add_argument(
        "--decide",
        choices=["fast", "pipeline"],
        help="Print only `true` or `false` for one workflow, rather than the full JSON.",
    )
    parser.add_argument(
        "--now",
        help="Override the clock, as an ISO-8601 instant. UTC is assumed if no offset is given.",
    )
    parser.add_argument(
        "--data-dir",
        help="Override the data root, matching `fpl-dof --data-dir`.",
    )
    return parser


def parse_now(raw: str | None) -> dt.datetime:
    """The moment to reason about, always as UTC. Overridable so the guard is testable."""
    if raw is None:
        return dt.datetime.now(dt.UTC)
    moment = dt.datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC)


def time_to_deadline(
    config: Config, layout: DataLayout, now: dt.datetime
) -> tuple[float | None, int | None, str | None]:
    """Minutes to the next deadline, the gameweek it belongs to, and why not, if not.

    Every failure is reported as "unknown" rather than raised. Both callers read unknown as "keep
    the fixed cadence and stand down from the deadline-relative behaviour", which degrades to the
    schedule this project had before it was deadline-aware rather than breaking it (DP-15).
    """
    try:
        gameweeks: pd.DataFrame | None = read_table_optional(
            layout.silver, config.rules.season, Table.GAMEWEEK
        )
    except Exception as exc:
        # Deliberately broad. Anything at all wrong with the silver tier — absent, half-written,
        # failing its schema — means the deadline is unknown, and unknown is a case both callers
        # already handle safely. It must never be the reason a workflow reports failure.
        return None, None, f"the gameweek table could not be read: {type(exc).__name__}: {exc}"
    if gameweeks is None or gameweeks.empty:
        return None, None, "the gameweek table has not been ingested yet"
    try:
        view = next_deadline(
            gameweeks,
            now=now,
            local_zone=config.runtime.timezone,
            decide_by_hours=config.alerts.decide_by_hours_before_deadline,
        )
    except NoDeadlineError as exc:
        return None, None, str(exc)
    return view.time_remaining.total_seconds() / 60, view.gameweek, None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = parse_now(args.now)

    environ = dict(os.environ)
    if args.data_dir:
        environ["FPL_DOF_DATA_DIR"] = args.data_dir

    try:
        config, _ = load_config(environ=environ)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    minutes, gameweek, unknown_reason = time_to_deadline(config, layout_for(config), now)

    fast = fast_ingest_decision(
        now=now,
        minutes_to_deadline=minutes,
        gameweek=gameweek,
        config=config.schedule,
    )
    pipeline = pipeline_decision(
        minutes_to_deadline=minutes,
        gameweek=gameweek,
        config=config.schedule,
    )

    if args.decide == "fast":
        print(TRUE if fast.should_run else FALSE)
        return EXIT_OK
    if args.decide == "pipeline":
        print(TRUE if pipeline.should_run else FALSE)
        return EXIT_OK

    print(
        json.dumps(
            {
                "now_utc": now.isoformat().replace("+00:00", "Z"),
                "gameweek": gameweek,
                "minutes_to_deadline": None if minutes is None else round(minutes, 2),
                "hours_to_deadline": (
                    None if minutes is None else round(minutes / MINUTES_PER_HOUR, 3)
                ),
                "deadline_unknown_reason": unknown_reason,
                "fast_ingest": fast.as_dict(),
                "pipeline": pipeline.as_dict(),
            },
            indent=2,
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
