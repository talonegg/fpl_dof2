"""Invariant 1, enforced.

No module outside ``fpl_dof.sources`` may import a source module, name a source, or reference a
source's endpoints. This test is the enforcement; the docstring in ``sources/__init__.py`` is only
the explanation.

It is deliberately a plain text scan rather than an import graph analysis: it also catches a source
name appearing in a comment, a log message or a config key default, which is where the abstraction
usually starts leaking before it properly breaks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import fpl_dof
from fpl_dof.sources import known

SRC = Path(fpl_dof.__file__).parent
SOURCES_PKG = SRC / "sources"
PIPELINE_ROOT = SRC.parents[1]
SCRIPTS_DIR = PIPELINE_ROOT / "scripts"

#: Names and strings that only ``sources/`` is allowed to contain.
#: Source names are bounded by (?<![\w-]) / (?![\w-]) rather than \b, because \b would match
#: "understat" inside the ordinary English word "understates" — which it duly did.
FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"fantasy\.premierleague\.com",
    r"bootstrap-static",
    r"element-summary",
    r"(?<![\w-])understat(?![\w-])",
    r"(?<![\w-])fbref(?![\w-])",
    r"the-odds-api",
    r"football-data\.co\.uk",
    r"(?<![\w-])fdcouk(?![\w-])",
    r"\bfrom fpl_dof\.sources\.\w+ import",
    r"\bimport fpl_dof\.sources\.\w+",
)

#: This test file itself, and the package docstring, necessarily name sources.
EXEMPT = {Path(__file__).resolve()}


def _modules_outside_sources() -> list[Path]:
    modules = [
        path
        for path in SRC.rglob("*.py")
        if SOURCES_PKG not in path.parents and path.resolve() not in EXEMPT
    ]
    if SCRIPTS_DIR.is_dir():
        modules.extend(path for path in SCRIPTS_DIR.rglob("*.py") if path.resolve() not in EXEMPT)
    return modules


def test_there_is_something_to_check() -> None:
    assert _modules_outside_sources(), "the scan found no modules; the path resolution is wrong"


@pytest.mark.parametrize("pattern", FORBIDDEN_PATTERNS)
def test_no_module_outside_sources_names_a_source(pattern: str) -> None:
    compiled = re.compile(pattern, re.IGNORECASE)
    offenders: list[str] = []
    for path in _modules_outside_sources():
        rel = path.relative_to(PIPELINE_ROOT)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if compiled.search(line):
                offenders.append(f"{rel}:{number}")
    assert not offenders, (
        f"Invariant 1 breach — {pattern!r} appears outside sources/: {', '.join(offenders)}"
    )


def test_registered_source_names_do_not_appear_outside_sources() -> None:
    """Catches sources added later without anyone updating FORBIDDEN_PATTERNS."""
    offenders: list[str] = []
    for name in known():
        # Not \b: the project is itself called fpl-dof, and "fpl" inside "fpl-dof" or "fpl_dof"
        # is the package name, not a source reference.
        compiled = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")
        for path in _modules_outside_sources():
            rel = path.relative_to(PIPELINE_ROOT)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if compiled.search(line):
                    offenders.append(f"{name} in {rel}:{number}")
    assert not offenders, f"Invariant 1 breach: {', '.join(offenders)}"


def test_the_sources_root_exports_nothing_from_inside_an_adapter() -> None:
    """REM-06: re-exporting an adapter's internals from the root would pass every text check above
    while handing its file format or market maths to code outside ``sources/``."""
    import fpl_dof.sources as sources

    adapters = tuple(f"fpl_dof.sources.{name}" for name in known())
    leaked = [
        name
        for name in sources.__all__
        if getattr(getattr(sources, name), "__module__", "").startswith(adapters)
    ]
    assert not leaked, f"Invariant 1 breach: fpl_dof.sources re-exports adapter internals {leaked}"
