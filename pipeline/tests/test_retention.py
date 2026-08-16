from __future__ import annotations

import datetime as dt

import pytest

from fpl_dof.retention import UndatedSnapshotError, plan_retention, snapshot_date


def test_snapshot_date_finds_the_date_directory_at_any_depth() -> None:
    assert snapshot_date(
        "bronze/fpl/bootstrap-static/2026-08-10/all__20260810T041530Z.json.gz"
    ) == dt.date(2026, 8, 10)
    assert snapshot_date(
        "bronze/fpl/element-summary/nested/2026-01-01/x__20260101T000000Z.json.gz"
    ) == dt.date(2026, 1, 1)


def test_snapshot_date_raises_when_no_date_directory_is_present() -> None:
    with pytest.raises(UndatedSnapshotError):
        snapshot_date("bronze/fpl/bootstrap-static/all__20260810T041530Z.json.gz")


def test_plan_retention_keeps_the_window_and_prunes_the_rest() -> None:
    today = dt.date(2026, 8, 31)
    paths = [
        "bronze/fpl/bootstrap-static/2026-08-31/all__x.json.gz",  # today, kept
        "bronze/fpl/bootstrap-static/2026-08-02/all__x.json.gz",  # 29 days ago, kept
        "bronze/fpl/bootstrap-static/2026-08-01/all__x.json.gz",  # exactly the cutoff, pruned
        "bronze/fpl/bootstrap-static/2025-01-01/all__x.json.gz",  # ancient, pruned
    ]

    plan = plan_retention(paths, today=today, window_days=30)

    assert plan.retain == (paths[0], paths[1])
    assert plan.prune == (paths[2], paths[3])
    assert plan.undated == ()


def test_plan_retention_never_prunes_an_undated_path() -> None:
    paths = ["bronze/fpl/bootstrap-static/all__no_date_dir.json.gz"]

    plan = plan_retention(paths, today=dt.date(2026, 8, 31), window_days=30)

    assert plan.retain == ()
    assert plan.prune == ()
    assert plan.undated == tuple(paths)


def test_plan_retention_rejects_a_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_days"):
        plan_retention([], today=dt.date(2026, 8, 31), window_days=0)


def test_plan_retention_is_stable_across_a_simulated_month_of_daily_runs() -> None:
    """The E7 DoD acceptance test in miniature: a month of daily churn must not grow the retained
    set past the window, which is the property that keeps a rebuilt `data` branch bounded."""
    start = dt.date(2026, 1, 1)
    retained_counts: list[int] = []

    for day_offset in range(60):
        today = start + dt.timedelta(days=day_offset)
        # One new snapshot per day since the start, simulating an ever-growing bronze store.
        paths = [
            f"bronze/fpl/bootstrap-static/{(start + dt.timedelta(days=i)).isoformat()}"
            "/all__x.json.gz"
            for i in range(day_offset + 1)
        ]
        plan = plan_retention(paths, today=today, window_days=30)
        retained_counts.append(len(plan.retain))

    # Bounded at the window size once the simulated history exceeds it — never grows past 30.
    assert max(retained_counts) <= 30
    assert retained_counts[-1] == 30
