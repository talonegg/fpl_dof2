"""Documentation checks (DL-74): the decision index is current and every link and citation resolves.

    python scripts/docs.py index   rewrite the index table in docs/decisions/README.md
    python scripts/docs.py check   fail on a stale index, a broken link, or an unknown DL-nn

Standard library only, so CI runs it before anything is installed.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "docs" / "decisions"
README = DECISIONS / "README.md"
START, END = "<!-- index:start -->", "<!-- index:end -->"
LINK = re.compile(r"\]\(<?([^)\s>]+)>?\)")
CITE = re.compile(r"\bDL-(\d+)\b")
TEXT = (".md", ".py", ".ts", ".tsx", ".cjs", ".mjs", ".yml", ".yaml", ".toml")
TITLE_MAX = 110


def files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [ROOT / f for f in out.splitlines() if (ROOT / f).is_file()]


def entries() -> dict[int, Path]:
    return {int(p.stem[3:]): p for p in DECISIONS.glob("DL-*.md")}


def index_table() -> str:
    rows = ["| Entry | Date | Status | Title |", "| --- | --- | --- | --- |"]
    for _, path in sorted(entries().items()):
        text = path.read_text(encoding="utf-8")
        head = re.match(r"#+ DL-\d+ — (.+)", text)
        title = head.group(1).strip() if head else "(no heading)"
        if len(title) > TITLE_MAX:
            title = title[: TITLE_MAX - 1].rstrip() + "…"
        title = title.replace("|", "\\|")
        status = re.search(r"\*\*Status:\*\*\s*([^·*\n]+)", text)
        date = re.search(r"\*\*Date:\*\*\s*([\d-]+)", text)
        rows.append(
            f"| [{path.stem}]({path.name}) | {date.group(1) if date else ''} "
            f"| {status.group(1).strip() if status else ''} | {title} |"
        )
    return "\n".join(rows)


def with_index(readme: str) -> str:
    before, rest = readme.split(START, 1)
    return f"{before}{START}\n{index_table()}\n{END}{rest.split(END, 1)[1]}"


def check() -> list[str]:
    problems = []
    readme = README.read_text(encoding="utf-8")
    if with_index(readme) != readme:
        problems.append("docs/decisions/README.md: index is stale; run `scripts/docs.py index`")
    known = set(entries())
    for path in files():
        if path.suffix not in TEXT:
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for n in sorted({int(m) for m in CITE.findall(text)} - known):
            problems.append(f"{rel}: cites DL-{n:02d}, which is no entry in docs/decisions/")
        if path.suffix != ".md":
            continue
        for target in LINK.findall(text):
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target or ":" in target:
                continue  # anchor-only, or a URL
            resolved = (path.parent / target).resolve()
            if resolved.is_relative_to(ROOT / "data"):
                continue  # a pipeline output, gitignored by design
            if not resolved.exists():
                problems.append(f"{rel}: broken link to {target}")
    return problems


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "index":
        text = with_index(README.read_text(encoding="utf-8"))
        README.write_text(text, encoding="utf-8", newline="\n")
        return 0
    if command == "check":
        problems = check()
        print("\n".join(problems) or "docs: ok")
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
