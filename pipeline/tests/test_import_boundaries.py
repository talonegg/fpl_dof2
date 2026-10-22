"""Module boundaries (MOD-01, DL-87): contracts hold; a new forbidden import fails."""

import ast
import os
import re
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


SRC = PIPELINE / "src" / "fpl_dof"
CORE = ("rules", "squad", "optimise", "decision")
#: Attribute / call names that touch the filesystem or the environment.
IO_NAMES = {
    "open", "read_text", "write_text", "read_bytes", "write_bytes", "mkdir", "unlink",
    "read_parquet", "read_csv", "read_json", "to_parquet", "to_csv", "to_json",
    "environ", "getenv", "safe_load", "load", "dump",
}  # fmt: skip


def test_core_does_no_file_io_and_reads_no_environment() -> None:
    """Core (DP-03) is pure: files and environment belong to the edge."""
    found = []
    for pkg in CORE:
        for path in sorted((SRC / pkg).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                name = (
                    node.attr
                    if isinstance(node, ast.Attribute)
                    else node.id
                    if isinstance(node, ast.Name)
                    else None
                )
                if name in IO_NAMES:
                    found.append(f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)} {name}")
    assert not found, "core touches the filesystem or environment: " + ", ".join(found)


def test_stages_and_publish_build_no_gold_path_by_hand() -> None:
    """Gold directories and artefact file names live in fpl_dof.paths / fpl_dof.artefacts."""
    pattern = re.compile(r"[\"']season=|.parquet\"|\"(squad|captain_line|quality).json\"")
    found = [
        f"{p.relative_to(SRC)}:{i}"
        for pkg in ("stages", "publish")
        for p in sorted((SRC / pkg).rglob("*.py"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and not line.lstrip().startswith(("#", '"""'))
    ]
    assert not found, "hand-built gold paths or file names: " + ", ".join(found)
