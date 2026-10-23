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


#: What importing the schedule decision needs, and so what every job that installs a named set
#: rather than the package must install (ORC-09): `fpl_dof.week` reaches `sources` and `silver`.
MINIMAL = {"pandas", "pandera", "pyarrow", "pydantic", "pyyaml", "httpx"}


def test_every_minimal_install_is_the_schedule_decisions_set() -> None:
    lock = "-c pipeline/requirements.lock"
    named = [
        (f.name, line.split(lock, 1)[1].split())
        for f in WORKFLOWS.glob("*.yml")
        for line in f.read_text(encoding="utf-8").splitlines()
        if "pip install" in line and lock in line and "-e" not in line.split(lock, 1)[1]
    ]
    assert named
    for name, packages in named:
        assert set(packages) == MINIMAL, f"{name}: {' '.join(packages)}"
