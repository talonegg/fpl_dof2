"""Module boundaries (MOD-01, DL-87): contracts hold; a new forbidden import fails."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]


def _lint(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "from importlinter.cli import lint_imports_command as m; m()"],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        # import-linter prints non-ASCII; a Windows console code page would make the child crash.
        env={**os.environ, "PYTHONUTF8": "1"},
        check=False,
    )


def test_real_config_passes() -> None:
    result = _lint(PIPELINE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_forbidden_import_fails(tmp_path: Path) -> None:
    # A copy of the package sits in the working directory, which shadows the installed one.
    shutil.copytree(
        PIPELINE / "src" / "fpl_dof",
        tmp_path / "fpl_dof",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(PIPELINE / "pyproject.toml", tmp_path)
    with (tmp_path / "fpl_dof" / "rules" / "__init__.py").open("a", encoding="utf8") as f:
        f.write("\nimport fpl_dof.sources  # deliberate: core must not import the data platform\n")
    result = _lint(tmp_path)
    assert result.returncode != 0
    assert "fpl_dof.rules -> fpl_dof.sources" in result.stdout
