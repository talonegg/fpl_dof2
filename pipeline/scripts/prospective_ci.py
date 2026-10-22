"""CI driver for the frozen prospective models. The effectful edge (DP-03); checks live in
:mod:`fpl_dof.prospective`. The frozen harness (decide.py / score.py) runs unmodified.

    python pipeline/scripts/prospective_ci.py prepare   # verify bundle, fetch odds history
    python pipeline/scripts/prospective_ci.py plan      # -> GITHUB_OUTPUT: decide=, score=, gw=
    #   (timing rule: fpl_dof.prospective.timing)
    python pipeline/scripts/prospective_ci.py silver --ok 0|1   # record the silver refresh
    python pipeline/scripts/prospective_ci.py status    # fail-closed status for new decisions
    python pipeline/scripts/prospective_ci.py preview   # provisional advice (scratch copy, dry run)
    python pipeline/scripts/prospective_ci.py pack OUT  # deterministic tarball of the record
    python pipeline/scripts/prospective_ci.py unpack TARBALL

Paths come from the harness's own constants: the bundle must be extracted to
``/workspace/fpl_dof2_frozen`` (frozen code) and ``/workspace/fpl_prospective`` (harness), the
locations it was frozen at. ``PROSPECTIVE_ROOT`` / ``PROSPECTIVE_FROZEN`` override them for tests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl_dof.prospective.bundle import verify_bundle
from fpl_dof.prospective.freshness import assess, silver_stats
from fpl_dof.prospective.timing import DECIDE_WINDOW, decide_timing, odds_coverage
from fpl_dof.sources import UPCOMING_ODDS_RECORD, LiveFeed

ROOT = Path(os.environ.get("PROSPECTIVE_ROOT", "/workspace/fpl_prospective"))
FROZEN = Path(os.environ.get("PROSPECTIVE_FROZEN", "/workspace/fpl_dof2_frozen"))
PREP = ROOT / "ci"
STATUS = ROOT / "status"
#: Provisional (pre-window) advice. Deliberately NOT in RECORD: never packed to the ledger branch,
#: never restored by unpack, never read as a decision. Handed to publish as models.json preview.
PREVIEW = ROOT / "preview"
#: Hard cap on one preview run; the frozen decide.py takes roughly the same time as a real decide.
#: The interpreter the frozen harness is run with in CI (decide.py hardcodes it for model_runner).
HARNESS_PY = os.environ.get("PROSPECTIVE_PY", "/workspace/fpl_dof2/.venv/bin/python")
PREVIEW_TIMEOUT_S = int(os.environ.get("PROSPECTIVE_PREVIEW_TIMEOUT", "1500"))
SEASON = "2026/27"
#: What survives between runs (on the `ledger` branch). raw/ and cache/ are rebuilt; the
#: decision documents record the sha256 of every raw input they used.
RECORD = (
    "decisions",
    "state",
    "status",
    "scores.csv",
    "report.md",
    # Per-player xP accuracy (score_xp.py) and the kept, hashed xP files it scores.
    "xp_scores.csv",
    "xp_scores_paired.csv",
    "xp_calibration.csv",
    "data/gold/xp",
    # The upcoming odds each decision used, as fetched (REM-07): the frozen A+odds model's input.
    UPCOMING_ODDS_RECORD,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _manifest() -> dict[str, Any]:
    return dict(json.loads((ROOT / "manifest.json").read_text(encoding="utf-8")))


def prepare() -> int:
    manifest = _manifest()
    report = verify_bundle(FROZEN, ROOT, manifest)
    expected = manifest["models"]["A_odds"]["model_files_sha256"]
    with LiveFeed() as feed:
        odds = feed.place_odds_history(FROZEN, expected)
    # Re-verify now the downloaded files are in place, so the per-model view is final.
    report = verify_bundle(FROZEN, ROOT, manifest)
    _write(
        PREP / "bundle.json",
        {
            "shared_ok": report.shared_ok,
            "manifest_ok": report.manifest_ok,
            "common_mismatches": report.common_mismatches,
            "harness_mismatches": report.harness_mismatches,
            "model_problems": report.model_problems,
        },
    )
    _write(PREP / "odds_history.json", odds)
    print(
        f"bundle shared_ok={report.shared_ok}; odds history problems: "
        f"{[k for k, v in odds.items() if v] or 'none'}"
    )
    return 0


def _bootstrap() -> dict[str, Any]:
    with LiveFeed() as feed:
        return feed.state()


def _fixtures() -> list[dict[str, Any]]:
    with LiveFeed() as feed:
        return feed.fixtures()


def _upcoming_odds() -> tuple[pd.DataFrame, bytes]:
    """This gameweek's market odds, conformed, and the snapshot's bytes; empty if unreachable."""
    try:
        with LiveFeed() as feed:
            return feed.upcoming_odds()
    except Exception as exc:
        print(f"plan: upcoming odds unavailable ({type(exc).__name__}: {exc}); treating as absent")
        return pd.DataFrame(columns=["home_team", "away_team"]), b""


def _last_finished(bootstrap: dict[str, Any]) -> int:
    done = [e["id"] for e in bootstrap["events"] if e["finished"] and e["data_checked"]]
    return max(done) if done else 0


#: Directories the frozen decide.py writes into but never creates. ``state/`` is absent from the
#: bundle and from the ledger record until the first decision, so decide.py wrote GW7's decision
#: and then crashed on ``state/engine.json`` (run 38974140926, 2026-10-17), losing every model's
#: state. Create them before any decision can run. ``raw/`` is left out of the record, and the
#: frozen score.py writes ``raw/live_GW<n>.json`` into it, so a score-only run after a restore
#: crashed (run 39854574887, 2026-10-22).
HARNESS_DIRS = ("decisions", "state", "raw")


def ensure_harness_dirs() -> None:
    for d in HARNESS_DIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)


def plan() -> int:
    ensure_harness_dirs()
    bs = _bootstrap()
    nxt = next((e for e in bs["events"] if e["is_next"]), None)
    decide, gw, reason, coverage = False, 0, "no next gameweek", [0, 0]
    if nxt is not None:
        gw = int(nxt["id"])
        deadline = dt.datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
        already = (ROOT / "decisions" / f"GW{gw}.json").exists()
        joined = total = 0
        raw = b""
        if not already and dt.timedelta(0) < deadline - _now() <= DECIDE_WINDOW:
            odds, raw = _upcoming_odds()
            joined, total = odds_coverage(odds, gw, bs["teams"], _fixtures())
        timing = decide_timing(
            now=_now(), deadline=deadline, already_decided=already, joined=joined, total=total
        )
        decide, reason, coverage = timing.decide, timing.reason, [joined, total]
        if decide and raw:
            record = ROOT / UPCOMING_ODDS_RECORD / f"GW{gw}_fixtures.csv"
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_bytes(raw)
    finished = {e["id"] for e in bs["events"] if e["finished"] and e["data_checked"]}
    decided = {int(p.stem[2:]) for p in (ROOT / "decisions").glob("GW*.json")}
    scores = ROOT / "scores.csv"
    scored = (
        {int(line.split(",", 1)[0]) for line in scores.read_text().splitlines()[1:] if line}
        if scores.exists()
        else set()
    )
    score = bool((decided & finished) - scored)
    bundle = _read(PREP / "bundle.json") or {}
    if not bundle.get("shared_ok"):
        decide = score = False  # never run unverified frozen code
    _write(
        PREP / "plan.json",
        {
            "gw": gw,
            "decide": decide,
            "decide_reason": reason,
            "odds_coverage": coverage,
            "score": score,
            "last_finished": _last_finished(bs),
            "at": _now().isoformat(),
        },
    )
    out = os.environ.get("GITHUB_OUTPUT")
    lines = f"decide={str(decide).lower()}\nscore={str(score).lower()}\ngw={gw}\n"
    if out:
        with Path(out).open("a", encoding="utf-8") as f:
            f.write(lines)
    print(lines.strip().replace("\n", " ") + f" ({reason})")
    return 0


def silver(ok: bool) -> int:
    _write(
        PREP / "silver.json", {"refresh_ok": ok, "refreshed_at": _now().isoformat() if ok else None}
    )
    return 0


def _assess(doc: dict[str, Any]) -> dict[str, Any]:
    """The fail-closed input check for one decision document (frozen or preview)."""
    from fpl_dof.prospective.bundle import BundleReport

    b = _read(PREP / "bundle.json") or {}
    report = BundleReport(
        manifest_ok=bool(b.get("manifest_ok")),
        common_mismatches=list(b.get("common_mismatches", ["bundle not verified"])),
        harness_mismatches=list(b.get("harness_mismatches", [])),
        model_problems=dict(b.get("model_problems", {})),
    )
    odds = _read(PREP / "odds_history.json") or {}
    plan_doc = _read(PREP / "plan.json") or {}
    srec = _read(PREP / "silver.json") or {}
    silver_path = ROOT / "data" / "silver" / "season=2026-27" / "player_gameweek.parquet"
    stats = None
    if silver_path.exists():
        import pandas as pd

        frame = pd.read_parquet(
            silver_path, columns=["season", "gameweek", "minutes", "expected_goals"]
        )
        refreshed = srec.get("refreshed_at")
        stats = silver_stats(
            frame,
            season=SEASON,
            last_finished=int(plan_doc.get("last_finished", 0)),
            refresh_ok=bool(srec.get("refresh_ok")),
            refreshed_at=dt.datetime.fromisoformat(refreshed) if refreshed else None,
        )
    return dict(
        assess(
            doc,
            bundle=report,
            silver=stats,
            last_finished=int(plan_doc.get("last_finished", 0)),
            odds_history=odds,
        )
    )


def status() -> int:
    """Write status/GW{n}.json for every decision without one. Decisions are create-only, so the
    status is computed once, right after the decision, against the inputs that decision used."""
    for p in sorted((ROOT / "decisions").glob("GW*.json")):
        target = STATUS / p.name
        if target.exists():
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        result = _assess(doc)
        _write(target, {"gw": doc.get("gw"), "assessed_at": _now().isoformat(), "models": result})
        print(
            f"status {p.stem}: "
            + ", ".join(f"{m}={'ok' if r['available'] else r['reason']}" for m, r in result.items())
        )
    return 0


def _record_digest() -> dict[str, str]:
    """sha256 of every file in the record, keyed by its record path."""
    out: dict[str, str] = {}
    for item in RECORD:
        p = ROOT / item
        files = (
            [p]
            if p.is_file()
            else sorted(f for f in p.rglob("*") if f.is_file())
            if p.is_dir()
            else []
        )
        for f in files:
            out[f.relative_to(ROOT).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def _scratch_ignore(directory: str, names: list[str]) -> set[str]:
    """What the scratch copy leaves out: per-run caches/raw inputs, the decisions and the kept xP
    copies (a dry run reads neither), and any earlier preview."""
    rel = Path(directory).resolve().relative_to(ROOT.resolve()).as_posix()
    skip = {"cache", "raw", "decisions", "preview"} if rel == "." else set()
    if rel == "data":
        skip.add("gold")
    return skip & set(names)


def preview(gw: int | None = None) -> int:
    """Provisional advice for the next gameweek, before its frozen decision exists.

    Runs the frozen ``decide.py --dry-run`` unmodified against a *scratch copy* of the harness
    root (``FPL_PROSPECTIVE_ROOT`` is the harness's own override), so even a misbehaving run cannot
    touch ``decisions/``, ``state/``, ``data/gold/xp`` or anything the ledger pack reads. The
    resulting ``decision_preview.json`` is copied to ``preview/GW{n}.json`` with its fail-closed
    input check, and the record is verified byte-identical afterwards. Never fails the job.
    """
    plan_doc = _read(PREP / "plan.json") or {}
    gw = gw or int(plan_doc.get("gw") or 0)
    bundle = _read(PREP / "bundle.json") or {}
    reason = None
    if gw <= 0:
        reason = "no next gameweek"
    elif (ROOT / "decisions" / f"GW{gw}.json").exists():
        reason = f"GW{gw} already has a frozen decision"
    elif not bundle.get("shared_ok"):
        reason = "bundle not verified"  # never run unverified frozen code
    if reason:
        print(f"preview: skipped ({reason})")
        return 0
    before = _record_digest()
    target = PREVIEW / f"GW{gw}.json"
    with tempfile.TemporaryDirectory(prefix="prospective-preview-") as tmp:
        scratch = Path(tmp) / "root"
        shutil.copytree(ROOT, scratch, ignore=_scratch_ignore, symlinks=True)
        (scratch / "decisions").mkdir()
        env = {
            **os.environ,
            "FPL_PROSPECTIVE_ROOT": str(scratch),
            "FPL_PROSPECTIVE_DATA": str(scratch / "data"),
        }
        try:
            proc = subprocess.run(
                [
                    HARNESS_PY if Path(HARNESS_PY).exists() else sys.executable,
                    "decide.py",
                    "--dry-run",
                    "--gw",
                    str(gw),
                ],
                cwd=scratch,
                env=env,
                capture_output=True,
                text=True,
                timeout=PREVIEW_TIMEOUT_S,
                check=False,
            )
            print(proc.stdout[-4000:])
            out = scratch / "cache" / f"dryrun_GW{gw}" / "decision_preview.json"
            doc = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
            if proc.returncode != 0 or doc is None:
                print(f"preview: decide.py --dry-run failed (exit {proc.returncode})")
                print(proc.stderr[-4000:])
                doc = None
        except subprocess.TimeoutExpired:
            print(f"preview: timed out after {PREVIEW_TIMEOUT_S}s")
            doc = None
    if _record_digest() != before:  # cannot happen via the scratch copy; fail loudly if it does
        raise SystemExit("preview: the prospective record changed; refusing to publish a preview")
    if doc is None:
        return 0
    if (ROOT / "decisions" / f"GW{gw}.json").exists():
        print(f"preview: GW{gw} was decided meanwhile; preview discarded")
        return 0
    doc["provisional"] = True
    doc["preview_status"] = {"assessed_at": _now().isoformat(), "models": _assess(doc)}
    _write(target, doc)
    print(f"preview: wrote {target}")
    return 0


def _add(tar: tarfile.TarFile, path: Path, arc: str) -> None:
    info = tarfile.TarInfo(arc)
    data = path.read_bytes()
    info.size, info.mtime, info.mode, info.uid, info.gid = len(data), 0, 0o644, 0, 0
    tar.addfile(info, io.BytesIO(data))


def pack(out: Path) -> int:
    """Deterministic tarball (sorted, zero mtimes/owners, gzip without a timestamp), so an
    unchanged record is byte-identical and the append-only ledger step is a no-op."""
    import gzip

    files: list[tuple[Path, str]] = []
    for item in RECORD:
        p = ROOT / item
        if p.is_file():
            files.append((p, item))
        elif p.is_dir():
            files += [
                (f, f.relative_to(ROOT).as_posix()) for f in sorted(p.rglob("*")) if f.is_file()
            ]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path, arc in sorted(files, key=lambda x: x[1]):
            _add(tar, path, arc)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue())
    print(f"packed {len(files)} files -> {out}")
    return 0


def _in_record(name: str) -> bool:
    """True for a record path itself or anything under a record directory (``data/gold/xp/...``)."""
    p = Path(name)
    if p.is_absolute() or ".." in p.parts:
        return False
    return any(name == r or name.startswith(r + "/") for r in RECORD)


def unpack(tarball: Path) -> int:
    """Restore only the record's own paths; anything else in the tarball is ignored."""
    with tarfile.open(tarball, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile() and _in_record(m.name)]
        tar.extractall(ROOT, members=members, filter="data")
    print(f"restored {len(members)} files from {tarball}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sub.add_parser("plan")
    s = sub.add_parser("silver")
    s.add_argument("--ok", type=int, required=True)
    sub.add_parser("status")
    pv = sub.add_parser("preview")
    pv.add_argument("--gw", type=int, default=None)
    p = sub.add_parser("pack")
    p.add_argument("out", type=Path)
    u = sub.add_parser("unpack")
    u.add_argument("tarball", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "prepare":
        return prepare()
    if a.cmd == "plan":
        return plan()
    if a.cmd == "silver":
        return silver(bool(a.ok))
    if a.cmd == "status":
        return status()
    if a.cmd == "preview":
        return preview(a.gw)
    if a.cmd == "pack":
        return pack(a.out)
    return unpack(a.tarball)


if __name__ == "__main__":
    raise SystemExit(main())
