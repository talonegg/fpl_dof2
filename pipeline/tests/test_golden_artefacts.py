"""MOD-01 acceptance: `fpl-dof run` publishes byte-identical artefacts before and after a change.

Runs the whole pipeline offline on the recorded fixtures and compares every published
`web/v1/*.json` with the committed copy in `tests/golden/`, after masking the fields that
legitimately differ between runs (`MASKED`). A failure means published output changed: if that is
intended, re-baseline with `FPL_DOF_UPDATE_GOLDEN=1 pytest tests/test_golden_artefacts.py`;
review and commit the golden diff with the change.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from fpl_dof.cli import EXIT_OK, main

pytestmark = pytest.mark.usefixtures("recorded_fpl_api")

GOLDEN = Path(__file__).parent / "golden"
#: Keys whose values are run ids, wall-clock durations, times or a hash of source code.
MASKED = {
    "run_id",
    "generated_at",
    "digest",
    "duration_seconds",
    "solve_seconds",
    "git_sha",
    "git_dirty",
}
_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]+")
# The snapshot is fetched at wall-clock time but the run is pinned to FPL_DOF_AS_OF: its age drifts.
_AGE = re.compile(r"-?\d+(\.\d+)?h old")


def normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "<masked>" if k in MASKED else normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v) for v in value]
    if isinstance(value, str) and _RUN_ID.fullmatch(value):
        return "<masked>"
    if isinstance(value, str):
        return _AGE.sub("<age> old", value)
    return value


def test_published_artefacts_match_the_golden_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_env: dict[str, str]
) -> None:
    monkeypatch.setenv("FPL_DOF_CONFIG_FILE", isolated_env["FPL_DOF_CONFIG_FILE"])
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "run"]) == EXIT_OK
    published = sorted((data_dir / "web" / "v1").glob("*.json"))
    assert published
    actual = {
        p.name: json.dumps(normalise(json.loads(p.read_text("utf-8"))), indent=1, sort_keys=True)
        + "\n"
        for p in published
    }
    if os.environ.get("FPL_DOF_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        for stale in GOLDEN.glob("*.json"):
            stale.unlink()
        for name, text in actual.items():
            (GOLDEN / name).write_text(text, encoding="utf-8", newline="\n")
        pytest.skip("golden files re-baselined")
    assert sorted(actual) == sorted(p.name for p in GOLDEN.glob("*.json"))
    for name, text in actual.items():
        assert text == (GOLDEN / name).read_text("utf-8"), f"{name} differs from tests/golden"
