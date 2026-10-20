"""The 2026-10-14 A+odds harness fix and CI decision timing.

- the re-freeze changed only the harness (``live_frame.py``): every model's config hash and model
  files are the original frozen ones;
- the bundled live join resolves 2026/27's promoted sides (Coventry, Hull, Ipswich);
- CI decides at the first run inside 14 h with odds for every fixture, else at the last run.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib
import json
import sys
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.prospective.bundle import manifest_body_ok, verify_bundle
from fpl_dof.prospective.timing import (
    ALIASES,
    DECIDE_WINDOW,
    LAST_RUN_LEAD,
    decide_timing,
    odds_coverage,
)
from fpl_dof.sources import resolve_team

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "prospective" / "bundle" / "frozen-2026-10-13.tar.gz"
MANIFEST = REPO / "prospective" / "bundle" / "manifest.json"

#: The frozen-2026-10-13 values. A harness fix must leave every one of these untouched.
FROZEN_CONFIG_SHA256 = {
    "engine": "69f2e8d5e0ffe0204752e883c0ebfaa4bebaca9e0849296aa9c12b6fde565ed1",
    "C3": "56fde78e9a2916f38b7c65ed8a0934467ae8ab0c59613374bf4614c5b8eb304f",
    "C1": "778e156aabc71247835fe3dde21304f540c830455e47829a9b5c45ebed4589d1",
    "A": "5fe443d48d17f71ce1e12d637edebc1049b23b9d9baa4b3bbda9a0a55d7b4a80",
    "A_odds": "5f648c7145a2d8b2a9d42cf96f97822f207100eb03fe0421e9d9b1149c46f8f5",
}
ORIGINAL_MANIFEST_BODY = "25952fc2864c95d5102afd132ae7dfb5539a0bf0c02a8ccc5a2525036de7c2e8"
REFROZEN_MANIFEST_BODY = "edc07c0ed2ab60edc41a5872e1502c2b189f07435f22c59585f76232049829fa"
#: Second harness-only re-freeze (xP accuracy: decide.py hashes + keeps the xP files).
XP_REFROZEN_MANIFEST_BODY = "312f2b0db78ccb2238945e6578bbce164c581b1348e5ac01519a7299a29cbcdd"
OLD_DECIDE = "d85949d15ae370d3ae14e2d31c5ee228c71eeaf31892cddb65496ad706418f37"
NEW_DECIDE = "a3b18858c92416624cb83d4f3d9d98522ddafdffd0fbfb2af09b3c76505496de"
OLD_LIVE_FRAME = "fac8584647ad8d64f67010cd3b425be09a6c638126cbf3afa38836b42c7631f9"
NEW_LIVE_FRAME = "cf432ea97b0b21d9b71fd8097d312bc79de88adb36ce440b1c9f3facb52d1a3e"

TEAMS = [
    {"id": i + 1, "code": 100 + i, "name": n}
    for i, n in enumerate(
        [
            "Arsenal",
            "Coventry City",
            "Hull City",
            "Ipswich Town",
            "Man City",
            "Man Utd",
            "Spurs",
            "Newcastle",
            "Everton",
            "Fulham",
        ]
    )
]


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return dict(json.loads(MANIFEST.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def extracted(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("bundle")
    with tarfile.open(BUNDLE, "r:gz") as tar:
        tar.extractall(root, filter="data")
    return root


# --- the re-freeze ------------------------------------------------------------------------------


def test_refreeze_keeps_every_model_config_hash(manifest: dict[str, Any]) -> None:
    assert {k: v["config_sha256"] for k, v in manifest["models"].items()} == FROZEN_CONFIG_SHA256


def test_refreeze_is_recorded_and_the_manifest_is_self_consistent(manifest: dict[str, Any]) -> None:
    assert manifest_body_ok(manifest)
    assert manifest["manifest_body_sha256"] == XP_REFROZEN_MANIFEST_BODY
    assert manifest["frozen_tag"] == "frozen-2026-10-13"
    entry, xp_entry = manifest["refreezes"]
    assert xp_entry["manifest_body_sha256"]["old"] == REFROZEN_MANIFEST_BODY
    assert xp_entry["harness_files"] == {"decide.py": {"old": OLD_DECIDE, "new": NEW_DECIDE}}
    assert manifest["harness_files_sha256"]["decide.py"] == NEW_DECIDE
    assert entry["manifest_body_sha256"]["old"] == ORIGINAL_MANIFEST_BODY
    assert entry["harness_files"] == {
        "prospective/live_frame.py": {"old": OLD_LIVE_FRAME, "new": NEW_LIVE_FRAME}
    }
    assert manifest["harness_files_sha256"]["prospective/live_frame.py"] == NEW_LIVE_FRAME
    assert set(entry["source_sha256"]) == set(FROZEN_CONFIG_SHA256)


def test_refrozen_bundle_verifies(manifest: dict[str, Any], extracted: Path) -> None:
    report = verify_bundle(extracted / "frozen", extracted / "harness", manifest)
    assert report.shared_ok, (report.common_mismatches, report.harness_mismatches)
    for name in ("engine", "C3", "C1", "A"):
        assert report.model_ok(name), report.model_problems


# --- the bundled live join ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_frame(extracted: Path) -> Iterator[Any]:
    paths = [str(extracted / "harness" / "prospective"), str(extracted / "frozen" / "backtest")]
    sys.path[:0] = paths
    try:
        yield importlib.import_module("live_frame")
    finally:
        for p in paths:
            sys.path.remove(p)
        for mod in ("live_frame", "common", "odds_team", "ds_features"):
            sys.modules.pop(mod, None)


def _fixtures_csv(rows: list[tuple[str, str]]) -> bytes:
    head = "Div,Date,Time,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5\n"
    body = "".join(f"E0,17/10/2026,15:00,{h},{a},2.10,3.40,3.60,1.90,1.95\n" for h, a in rows)
    return (head + body).encode("latin-1")


def test_bundled_join_keeps_promoted_sides(live_frame: Any) -> None:
    import pandas as pd

    pairs = [
        ("Coventry", "Hull"),
        ("Ipswich", "Man United"),
        ("Tottenham", "Arsenal"),
        ("Man City", "Newcastle"),
    ]
    by_name = {t["name"]: t["id"] for t in TEAMS}
    full = {
        "Coventry": "Coventry City",
        "Hull": "Hull City",
        "Ipswich": "Ipswich Town",
        "Man United": "Man Utd",
        "Tottenham": "Spurs",
    }
    fixtures = [
        {
            "id": 900 + i,
            "event": 7,
            "team_h": by_name[full.get(h, h)],
            "team_a": by_name[full.get(a, a)],
            "kickoff_time": "2026-10-17T14:00:00Z",
        }
        for i, (h, a) in enumerate(pairs)
    ]
    deadline = pd.Timestamp("2026-10-17T10:00:00Z")
    out = live_frame.live_odds(
        _fixtures_csv(pairs),
        deadline - pd.Timedelta(hours=3),
        7,
        deadline,
        {"teams": TEAMS},
        fixtures,
    )
    assert sorted(out["fixture_id"]) == [900, 901, 902, 903]
    assert out["kept"].all()


def test_ci_aliases_mirror_the_bundled_harness(extracted: Path) -> None:
    """timing.ALIASES (used by the plan step) == frozen ALIAS + harness EXTRA_ALIAS."""

    def literal(path: Path, name: str) -> dict[str, str]:
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
                return dict(ast.literal_eval(node.value))
        raise AssertionError(name)

    frozen = literal(extracted / "frozen" / "backtest" / "ds_features.py", "ALIAS")
    extra = literal(extracted / "harness" / "prospective" / "live_frame.py", "EXTRA_ALIAS")
    assert {**frozen, **extra} == ALIASES


# --- CI decision timing ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "team"),
    [
        ("Coventry", 2),
        ("Hull", 3),
        ("Ipswich", 4),
        ("Man United", 6),
        ("Man City", 5),
        ("Tottenham", 7),
        ("Arsenal", 1),
        ("Liverpool", None),
        ("Man", None),
    ],
)
def test_resolve_team(name: str, team: int | None) -> None:
    assert resolve_team(name, TEAMS) == team


def test_odds_coverage_counts_only_this_gameweeks_e0_rows() -> None:
    fixtures = [
        {"event": 7, "team_h": 2, "team_a": 3},
        {"event": 7, "team_h": 4, "team_a": 6},
        {"event": 8, "team_h": 1, "team_a": 5},
    ]
    csv = (
        _fixtures_csv([("Coventry", "Hull"), ("Arsenal", "Man City")])
        + b"E1,x,x,Ipswich,Man United\n"
    )
    assert odds_coverage(csv, 7, TEAMS, fixtures) == (1, 2)
    assert odds_coverage(b"", 7, TEAMS, fixtures) == (0, 2)
    assert odds_coverage(
        "\ufeff".encode() + _fixtures_csv([("Coventry", "Hull"), ("Ipswich", "Man United")]),
        7,
        TEAMS,
        fixtures,
    ) == (2, 2)


DL = dt.datetime(2026, 10, 17, 10, 0, tzinfo=dt.UTC)


def _t(hours_before: float, joined: int = 10, total: int = 10, decided: bool = False):  # type: ignore[no-untyped-def]
    return decide_timing(
        now=DL - dt.timedelta(hours=hours_before),
        deadline=DL,
        already_decided=decided,
        joined=joined,
        total=total,
    )


def test_window_and_last_run_follow_the_schedule() -> None:
    assert dt.timedelta(hours=14) == DECIDE_WINDOW
    assert dt.timedelta(minutes=65) == LAST_RUN_LEAD  # T-45m window [T-65m, T-45m]


def test_decides_at_first_run_in_window_with_full_odds() -> None:
    assert not _t(14.5).decide  # nightly run the day before: outside the window
    assert _t(9).decide and "odds ready" in _t(9).reason


def test_waits_while_odds_are_missing_or_partial() -> None:
    assert not _t(9, joined=0).decide
    assert not _t(3, joined=7).decide
    assert "waiting" in _t(3, joined=7).reason


def test_falls_back_at_the_last_scheduled_run() -> None:
    for h in (65 / 60, 0.9, 0.75):
        t = _t(h, joined=0)
        assert t.decide and t.reason.startswith("fallback")


def test_write_once_and_past_deadline() -> None:
    assert not _t(9, decided=True).decide
    assert not _t(-0.1).decide
    assert not _t(0.75, joined=0, decided=True).decide


def test_at_least_two_scheduled_runs_fall_inside_the_window() -> None:
    """Deadline-relative runs (T-3h, T-45m) are always inside 14 h, whatever the deadline."""
    from fpl_dof.config.models import ScheduleConfig

    s = ScheduleConfig()
    inside = [
        o for o in s.pipeline_offsets_minutes if o + s.pipeline_window_tolerance_minutes < 14 * 60
    ]
    assert len(inside) >= 2
    assert min(s.pipeline_offsets_minutes) >= s.deadline_freeze_minutes


# --- the plan step end to end (network stubbed) -------------------------------------------------


def _ci_module() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "prospective_ci_timing", REPO / "pipeline" / "scripts" / "prospective_ci.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("hours_before", "csv_rows", "decide", "reason"),
    [
        (9.0, [("Coventry", "Hull"), ("Ipswich", "Man United")], True, "odds ready (2/2"),
        (9.0, [], False, "waiting for odds (0/2"),
        (0.8, [], True, "fallback"),
        (20.0, [("Coventry", "Hull"), ("Ipswich", "Man United")], False, "outside"),
    ],
)
def test_plan_writes_the_decision_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hours_before: float,
    csv_rows: list[tuple[str, str]],
    decide: bool,
    reason: str,
) -> None:
    ci = _ci_module()
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(ci, "PREP", tmp_path / "ci")
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "bundle.json").write_text('{"shared_ok": true}')
    bootstrap = {
        "teams": TEAMS,
        "events": [
            {
                "id": 7,
                "is_next": True,
                "deadline_time": "2026-10-17T10:00:00Z",
                "finished": False,
                "data_checked": False,
            }
        ],
    }
    fixtures = [{"event": 7, "team_h": 2, "team_a": 3}, {"event": 7, "team_h": 4, "team_a": 6}]
    monkeypatch.setattr(ci, "_bootstrap", lambda: bootstrap)
    monkeypatch.setattr(ci, "_now", lambda: DL - dt.timedelta(hours=hours_before))
    monkeypatch.setattr(
        ci,
        "_get",
        lambda url: json.dumps(fixtures).encode(),
    )
    monkeypatch.setattr(ci, "latest_fixtures_csv", lambda data_dir=None: _fixtures_csv(csv_rows))
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    ci.plan()
    plan = json.loads((tmp_path / "ci" / "plan.json").read_text())
    assert plan["decide"] is decide and plan["decide_reason"].startswith(reason)
    assert f"decide={str(decide).lower()}" in out.read_text()
