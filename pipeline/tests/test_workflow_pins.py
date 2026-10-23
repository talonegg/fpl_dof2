"""Workflows must install the pipeline against the committed lock (DP-11)."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_pipeline_installs_use_the_lock() -> None:
    installs = [
        (f.name, line)
        for f in WORKFLOWS.glob("*.yml")
        for line in f.read_text(encoding="utf-8").splitlines()
        if "pip install" in line and "pipeline" in line
    ]
    assert installs
    for name, line in installs:
        assert "-c pipeline/requirements.lock" in line, f"{name}: {line.strip()}"
