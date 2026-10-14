"""CI driver for the frozen prospective models. The effectful edge (DP-03); checks live in
:mod:`fpl_dof.prospective`. The frozen harness (decide.py / score.py) runs unmodified.

    python pipeline/scripts/prospective_ci.py prepare   # verify bundle, fetch odds history
    python pipeline/scripts/prospective_ci.py plan      # -> GITHUB_OUTPUT: decide=, score=, gw=
                                                        #    (timing rule: fpl_dof.prospective.timing)
    python pipeline/scripts/prospective_ci.py silver --ok 0|1   # record the silver refresh
    python pipeline/scripts/prospective_ci.py status    # fail-closed status for new decisions
    python pipeline/scripts/prospective_ci.py pack OUT  # deterministic tarball of the record
    python pipeline/scripts/prospective_ci.py unpack TARBALL

Paths come from the harness's own constants: the bundle must be extracted to
``/workspace/fpl_dof2_frozen`` (frozen code) and ``/workspace/fpl_prospective`` (harness), the
locations it was frozen at. ``PROSPECTIVE_ROOT`` / ``PROSPECTIVE_FROZEN`` override them for tests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl_dof.prospective.bundle import verify_bundle
from fpl_dof.prospective.fdcouk import fetch_history
from fpl_dof.prospective.freshness import assess, silver_stats
from fpl_dof.prospective.timing import DECIDE_WINDOW, decide_timing, odds_coverage

ROOT = Path(os.environ.get("PROSPECTIVE_ROOT", "/workspace/fpl_prospective"))
FROZEN = Path(os.environ.get("PROSPECTIVE_FROZEN", "/workspace/fpl_dof2_frozen"))
PREP = ROOT / "ci"
STATUS = ROOT / "status"
SEASON = "2026/27"
API = "https://fantasy.premierleague.com/api/"
UA = "fpl-dof-ci/1.0 (+https://github.com/talonegg/fpl_dof2; low-rate)"
ODDS_URL = "https://www.football-data.co.uk/fixtures.csv"
#: What survives between runs (on the `ledger` branch). raw/ and cache/ are rebuilt; the
#: decision documents record the sha256 of every raw input they used.
RECORD = ("decisions", "state", "status", "scores.csv", "report.md")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return bytes(r.read())


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
    odds = fetch_history(FROZEN, expected, _get)
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
    return dict(json.loads(_get(API + "bootstrap-static/")))


def _last_finished(bootstrap: dict[str, Any]) -> int:
    done = [e["id"] for e in bootstrap["events"] if e["finished"] and e["data_checked"]]
    return max(done) if done else 0


def plan() -> int:
    bs = _bootstrap()
    nxt = next((e for e in bs["events"] if e["is_next"]), None)
    decide, gw, reason, coverage = False, 0, "no next gameweek", [0, 0]
    if nxt is not None:
        gw = int(nxt["id"])
        deadline = dt.datetime.fromisoformat(nxt["deadline_time"].replace("Z", "+00:00"))
        already = (ROOT / "decisions" / f"GW{gw}.json").exists()
        joined = total = 0
        if not already and dt.timedelta(0) < deadline - _now() <= DECIDE_WINDOW:
            fixtures = json.loads(_get(API + "fixtures/"))
            try:
                csv_bytes = _get(ODDS_URL)
            except OSError as exc:
                print(f"plan: fixtures.csv fetch failed ({exc}); treating odds as absent")
                csv_bytes = b""
            joined, total = odds_coverage(csv_bytes, gw, bs["teams"], fixtures)
        timing = decide_timing(
            now=_now(), deadline=deadline, already_decided=already, joined=joined, total=total
        )
        decide, reason, coverage = timing.decide, timing.reason, [joined, total]
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


def status() -> int:
    """Write status/GW{n}.json for every decision without one. Decisions are create-only, so the
    status is computed once, right after the decision, against the inputs that decision used."""
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
    for p in sorted((ROOT / "decisions").glob("GW*.json")):
        target = STATUS / p.name
        if target.exists():
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        result = assess(
            doc,
            bundle=report,
            silver=stats,
            last_finished=int(plan_doc.get("last_finished", 0)),
            odds_history=odds,
        )
        _write(target, {"gw": doc.get("gw"), "assessed_at": _now().isoformat(), "models": result})
        print(
            f"status {p.stem}: "
            + ", ".join(f"{m}={'ok' if r['available'] else r['reason']}" for m, r in result.items())
        )
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
            files += [(f, str(f.relative_to(ROOT))) for f in sorted(p.rglob("*")) if f.is_file()]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path, arc in sorted(files, key=lambda x: x[1]):
            _add(tar, path, arc)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue())
    print(f"packed {len(files)} files -> {out}")
    return 0


def unpack(tarball: Path) -> int:
    """Restore only the record's own paths; anything else in the tarball is ignored."""
    with tarfile.open(tarball, "r:gz") as tar:
        members = [
            m
            for m in tar.getmembers()
            if m.isfile() and Path(m.name).parts and Path(m.name).parts[0] in RECORD
        ]
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
    if a.cmd == "pack":
        return pack(a.out)
    return unpack(a.tarball)


if __name__ == "__main__":
    raise SystemExit(main())
