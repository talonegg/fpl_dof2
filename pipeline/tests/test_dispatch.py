"""Typed dispatch (ORC-02, DL-94 item 4): an ingest with a material change starts one pipeline run
with valid inputs, one without starts none, the guard covers every trigger, freeze included, and no
workflow chains to another by name, title or cron string."""

from __future__ import annotations

import datetime as dt
import importlib.util
import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from fpl_dof.config.models import RuntimeConfig, ScheduleConfig
from fpl_dof.gameweek import GameweekState, Phase
from fpl_dof.schedule_cli import EXIT_USAGE
from fpl_dof.schedule_cli import main as schedule_main
from fpl_dof.sources import CHANGE_KINDS
from fpl_dof.week.schedule import CHANGE, TRIGGER_STAMP, TRIGGERS, dispatch_decision

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
CONFIG = ScheduleConfig()
NOW = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.UTC)


def _script() -> Any:
    path = REPO / "pipeline" / "scripts" / "dispatch_pipeline.py"
    spec = importlib.util.spec_from_file_location("dispatch_pipeline", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _open(minutes: float, gameweek: int = 3) -> GameweekState:
    return GameweekState(gameweek, Phase.OPEN, NOW + dt.timedelta(minutes=minutes), None)


def _decide(state: GameweekState | None, **inputs: Any) -> bool:
    fields: dict[str, Any] = {"trigger": "change", "kinds": ["prices"], "gameweek": 3, **inputs}
    return dispatch_decision(now=NOW, state=state, config=CONFIG, **fields).should_run


# --- the guard ----------------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", TRIGGERS)
def test_no_trigger_runs_inside_the_freeze(trigger: str) -> None:
    kinds = ["odds"] if trigger == "change" else []
    for minutes in (1, 30, CONFIG.deadline_freeze_minutes - 1):
        assert not _decide(_open(minutes), trigger=trigger, kinds=kinds), (trigger, minutes)
    assert _decide(_open(CONFIG.deadline_freeze_minutes + 1), trigger=trigger, kinds=kinds)


def test_a_run_queued_across_a_deadline_is_refused() -> None:
    assert _decide(_open(600), gameweek=3)
    assert not _decide(_open(600, gameweek=4), gameweek=3)
    assert _decide(_open(600, gameweek=4), gameweek=None)


def test_a_change_needs_an_open_gameweek_and_a_manual_run_does_not() -> None:
    assert not _decide(None, gameweek=None)
    assert _decide(None, trigger="manual", kinds=[], gameweek=None)


def test_the_tick_reads_the_pre_deadline_windows() -> None:
    assert _decide(_open(180), trigger="", kinds=[], gameweek=None)  # T-3h
    assert not _decide(_open(300), trigger="", kinds=[], gameweek=None)  # in no window


@pytest.mark.parametrize(
    ("trigger", "kinds"),
    [("nightly", []), ("change", []), ("change", ["weather"]), ("manual", ["prices"])],
)
def test_unknown_inputs_are_refused_loudly(trigger: str, kinds: list[str]) -> None:
    with pytest.raises(ValueError):
        _decide(_open(600), trigger=trigger, kinds=kinds)


def test_the_guard_cli_fails_on_an_unknown_trigger(tmp_path: Path) -> None:
    argv = ["--data-dir", str(tmp_path), "--decide", "pipeline", "--trigger", "nightly"]
    assert schedule_main(argv) == EXIT_USAGE


# --- the dispatch -------------------------------------------------------------------------------


def test_a_material_change_dispatches_one_run_with_valid_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _script()
    calls: list[list[str]] = []
    monkeypatch.setattr(script.subprocess, "run", lambda argv, **_: calls.append(argv))
    manifest = tmp_path / "changes.json"
    manifest.write_text(json.dumps({"gameweek": 3, "kinds": ["prices", "odds"]}), encoding="utf-8")

    assert script.main(["--manifest", str(manifest)]) == 0
    [argv] = calls
    assert argv[:4] == ["gh", "workflow", "run", "pipeline.yml"]
    sent = dict(field.split("=", 1) for field in argv[5::2])
    assert sent == {
        "trigger": "change",
        "kinds": "prices,odds",
        "gameweek": "3",
        "must_publish": "false",
    }
    # ...and the guard accepts exactly what was sent.
    assert _decide(_open(600), trigger=sent["trigger"], kinds=sent["kinds"].split(","))

    manifest.write_text(json.dumps({"gameweek": 3, "kinds": []}), encoding="utf-8")
    assert script.main(["--manifest", str(manifest)]) == 0
    assert len(calls) == 1, "no change, no run"


def test_the_slow_ingest_dispatches_its_daily_refresh_and_the_day_before() -> None:
    inputs = _script().inputs
    still = {"gameweek": 3, "kinds": []}
    assert inputs(still, daily=False, day_before=False) is None
    assert inputs(still, daily=True, day_before=False)["trigger"] == "schedule"
    day_before = inputs({"gameweek": 3, "kinds": ["prices"]}, daily=True, day_before=True)
    assert day_before == {
        "trigger": "day-before",
        "kinds": "",
        "gameweek": "3",
        "must_publish": "true",
    }
    for sent in (inputs(still, daily=True, day_before=False), day_before):
        assert sent is not None
        assert sent["trigger"] in TRIGGERS and _decide(
            _open(600), trigger=sent["trigger"], kinds=[]
        )


def test_the_kinds_the_manifest_writes_are_the_kinds_the_guard_accepts() -> None:
    assert _decide(_open(600), kinds=list(CHANGE_KINDS))


def _trigger_patterns(node: object) -> list[str]:
    """Every `trigger` property's pattern in a JSON Schema, however deep."""
    if isinstance(node, list):
        return [p for item in node for p in _trigger_patterns(item)]
    if not isinstance(node, dict):
        return []
    own = (
        [node["properties"]["trigger"]["pattern"]]
        if "trigger" in node.get("properties", {})
        else []
    )
    return own + [p for value in node.values() for p in _trigger_patterns(value)]


def test_every_trigger_pattern_accepts_exactly_the_vocabulary() -> None:
    """DP-14: TRIGGERS and CHANGE_KINDS are the one home. JSON Schema cannot import them, so each
    schema's `trigger` pattern is held to them here; config validates with the same pattern."""
    stamps = [t for t in TRIGGERS if t != CHANGE] + [
        f"{CHANGE}:{','.join(kinds)}"
        for n in range(1, len(CHANGE_KINDS) + 1)
        for kinds in itertools.permutations(CHANGE_KINDS, n)
    ]
    refused = ["", CHANGE, f"{CHANGE}:", "change:weather", "change:prices,", "change:prices,,odds"]
    refused += ["nightly", "Manual", "manual ", "schedule:prices", "change:prices,weather"]
    schemas = (REPO / "contracts" / "v1").glob("*.schema.json")
    patterns = [
        p for path in schemas for p in _trigger_patterns(json.loads(path.read_text("utf-8")))
    ]
    assert len(patterns) == 5  # meta, models (run and per strategy), plan, week
    for pattern in [*patterns, TRIGGER_STAMP]:
        assert pattern == TRIGGER_STAMP
        assert all(re.search(pattern, s) for s in stamps)
        assert not any(re.search(pattern, s) for s in refused)
    for stamp in stamps:
        assert RuntimeConfig(trigger=stamp).trigger == stamp
    for bad in refused:
        with pytest.raises(ValidationError):
            RuntimeConfig(trigger=bad)


# --- the wiring ---------------------------------------------------------------------------------

#: Ways one workflow can follow another by its name, a run's title or a cron string (ORC-02).
CHAINING = (r"workflow_run", r"github\.event\.schedule", r"display_?title", r"title_contains")


def _code(text: str) -> str:
    """Everything but comments: a comment may explain what the wiring no longer does."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_no_workflow_chains_by_name_title_or_cron_string() -> None:
    files = [*WORKFLOWS.glob("*.yml"), *(REPO / "pipeline" / "scripts").glob("*.py")]
    files += [*(REPO / "pipeline" / "src" / "fpl_dof" / "week").glob("*.py")]
    offenders = [
        f"{path.name}: {pattern}"
        for path in files
        for pattern in CHAINING
        if re.search(pattern, _code(path.read_text(encoding="utf-8")), re.IGNORECASE)
    ]
    assert not offenders
    for path in WORKFLOWS.glob("*.yml"):
        assert "workflow_run" not in yaml.safe_load(path.read_text(encoding="utf-8"))[True]


def _workflow(name: str) -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return loaded


def _step(job: dict[str, Any], name: str) -> tuple[int, dict[str, Any]]:
    return next((i, s) for i, s in enumerate(job["steps"]) if s.get("name") == name)


def test_the_pipeline_has_one_tick_and_typed_inputs() -> None:
    pipeline = _workflow("pipeline.yml")
    on = pipeline[True]
    assert [entry["cron"] for entry in on["schedule"]] == ["7,23,41,53 * * * *"]
    inputs = on["workflow_dispatch"]["inputs"]
    assert sorted(inputs["trigger"]["options"]) == sorted(TRIGGERS)
    assert inputs["must_publish"]["type"] == "boolean"
    assert {"kinds", "gameweek"} <= set(inputs)
    _, decide = _step(pipeline["jobs"]["guard"], "Decide whether to run")
    assert "--trigger" in decide["run"] and "change:$KINDS" in decide["run"]
    run = pipeline["jobs"]["run"]
    env = _step(run, "Run the pipeline (transform through publish)")[1]["env"]
    assert env["FPL_DOF_TRIGGER"] == "${{ needs.guard.outputs.trigger }}"


@pytest.mark.parametrize("workflow", ["ingest-fast.yml", "ingest-slow.yml"])
def test_each_ingest_dispatches_after_it_pushed_data_with_actions_write(workflow: str) -> None:
    loaded = _workflow(workflow)
    job = loaded["jobs"]["ingest"]
    assert (job.get("permissions") or loaded["permissions"])["actions"] == "write"
    index = next(
        i for i, s in enumerate(job["steps"]) if "dispatch_pipeline.py" in s.get("run", "")
    )
    assert index > _step(job, "Rebuild the rolling `data` branch")[0]
    assert "GH_TOKEN" in job["steps"][index]["env"]


def test_the_day_before_path_is_typed_and_still_fails_closed() -> None:
    gate = _workflow("day-before.yml")["jobs"]["refresh"]
    assert "-f must_publish=true" in gate["steps"][0]["run"]
    slow = _workflow("ingest-slow.yml")["jobs"]["ingest"]
    index, start = _step(slow, "Start the pipeline")
    # A failed ingest stops the job before this step, so nothing follows a failed day-before ingest.
    assert index > _step(slow, "Full ingest (element-summary + external sources)")[0]
    assert "if" not in start and "continue-on-error" not in start
    assert "inputs.must_publish && '--day-before'" in start["run"]
    deploy = _workflow("pipeline.yml")["jobs"]["deploy"]
    assert deploy["with"]["must_publish"] == "${{ inputs.must_publish == true }}"


def test_only_the_run_job_queues_so_a_tick_with_nothing_to_do_supersedes_nothing() -> None:
    """DL-94 item 4: among runs with work the newest pending one wins; a tick whose guard says no
    never joins the queue. A run that waited is asked again, so the freeze still binds (R-09)."""
    pipeline = _workflow("pipeline.yml")
    assert "concurrency" not in pipeline and "concurrency" not in pipeline["jobs"]["guard"]
    run = pipeline["jobs"]["run"]
    assert run["concurrency"] == {"group": "pipeline", "cancel-in-progress": False}
    # Deploys serialise in their own group, shared with deploy.yml's push and dispatch runs.
    assert _workflow("deploy.yml")["concurrency"] == {
        "group": "deploy",
        "cancel-in-progress": False,
    }

    index, still = _step(run, "Still outside the freeze now this run holds the queue")
    assert "fpl-dof-schedule --decide pipeline" in still["run"]
    assert still["env"]["TRIGGER"] == "${{ inputs.trigger || 'schedule' }}"
    restore_ledger = "Restore the advice ledger and experiments from the `ledger` branch"
    work = [s for s in run["steps"][index + 1 :] if s.get("name") != restore_ledger]
    assert work and all(s["if"] == "steps.still.outputs.run == 'true'" for s in work)
    # Asked as a dispatched run, a tick that waited out of its window still runs; the freeze holds.
    assert not _decide(_open(300), trigger="", kinds=[], gameweek=None)
    assert _decide(_open(300), trigger="schedule", kinds=[], gameweek=None)
    assert not _decide(_open(CONFIG.deadline_freeze_minutes - 1), trigger="schedule", kinds=[])
