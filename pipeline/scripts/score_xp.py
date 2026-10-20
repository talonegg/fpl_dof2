"""Score per-player xP accuracy for every finished prospective gameweek (CI, after score.py).

    python pipeline/scripts/score_xp.py

For each ``decisions/GW{n}.json`` that carries ``xp_sha256`` (decide.py since the 2026-10-14
harness-only re-freeze), whose gameweek is finished and data-checked, and that is not yet in
``xp_scores.csv``: load the kept xP files from ``data/gold/xp/GW{n}/``, refuse any whose sha256
differs from the decision, join FPL's live ``total_points`` (which sums both fixtures of a double
gameweek) and append rows to ``xp_scores.csv``. Then rebuild ``xp_scores_paired.csv`` and
``xp_calibration.csv`` from everything scored. Never touches decisions, state or scores.csv.

Design: research/fpl-xp-accuracy-scoring.md. Pre-registration: prospective/PREREG_C1_vs_C3.md.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpl_dof.prospective.xp_accuracy import (
    PAIRED_FIELDS,
    SCORE_FIELDS,
    calibration,
    paired,
    population,
    score_gw,
)
from fpl_dof.sources import LiveFeed

ROOT = Path(os.environ.get("PROSPECTIVE_ROOT", "/workspace/fpl_prospective"))
SEASON = "2026/27"


class Feed(Protocol):
    """The live reads this script makes: :class:`fpl_dof.sources.LiveFeed`, or a test's fake."""

    def state(self) -> dict[str, Any]: ...

    def gameweek_live(self, gameweek: int) -> dict[str, Any]: ...


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_gw(doc: dict[str, Any], root: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame | None]:
    """The verified xP frames per model and the deadline availability (None if not kept)."""
    gold = root / doc["xp_gold_dir"]
    xp: dict[str, pd.DataFrame] = {}
    avail = None
    for name, want in doc["xp_sha256"].items():
        p = gold / f"{name}.parquet" if name == "avail" else gold / f"xp_{name}.parquet"
        if not p.exists():
            raise FileNotFoundError(p)
        if _sha(p) != want:
            raise ValueError(f"GW{doc['gw']} {p.name}: sha256 differs from the decision")
        d = pd.read_parquet(p).rename(columns={"player_id": "player", "xp_next": "xp"})
        if name == "avail":
            avail = d[["player", "avail"]]
        else:
            xp[name] = d[["player", "position", "xp"]]
    return xp, avail


def actuals(doc: dict[str, Any], live: dict[str, Any], players: set[int]) -> pd.DataFrame:
    """Actual points per player *code*; a listed player with no live row scored 0 in 0 minutes."""
    by_el = {int(e["id"]): e["stats"] for e in live.get("elements", [])}
    c2e = {int(k): int(v) for k, v in doc["code_to_element"].items()}
    rows = []
    for code in sorted(players):
        st = by_el.get(c2e.get(code, -1), {})
        rows.append(
            {
                "player": code,
                "actual": int(st.get("total_points", 0)),
                "minutes": int(st.get("minutes", 0)),
            }
        )
    return pd.DataFrame(rows)


def run(root: Path = ROOT, feed: Feed | None = None, now: dt.datetime | None = None) -> int:
    if feed is None:
        with LiveFeed() as live:
            return run(root, live, now)
    scores_p = root / "xp_scores.csv"
    old = pd.read_csv(scores_p) if scores_p.exists() else pd.DataFrame(columns=list(SCORE_FIELDS))
    done = set(old["gw"].astype(int)) if len(old) else set()
    docs = [json.loads(p.read_text()) for p in sorted((root / "decisions").glob("GW*.json"))]
    docs = [d for d in docs if "xp_sha256" in d]
    events = {int(e["id"]): e for e in feed.state()["events"]} if docs else {}
    stamp = (now or dt.datetime.now(dt.UTC)).isoformat()
    new_rows: list[dict[str, Any]] = []
    for doc in docs:
        gw = int(doc["gw"])
        ev = events.get(gw, {})
        if gw in done or not (ev.get("finished") and ev.get("data_checked")):
            continue
        try:
            xp, avail = load_gw(doc, root)
        except (FileNotFoundError, ValueError) as exc:
            print(f"score_xp: GW{gw} not scored: {exc}")
            continue
        listed = set(avail["player"].astype(int)) if avail is not None else None
        pool = set().union(*(set(d["player"].astype(int)) for d in xp.values()))
        act = actuals(doc, feed.gameweek_live(gw), pool)
        if avail is not None:
            act = act.merge(avail, on="player", how="left")
        act.to_parquet(root / doc["xp_gold_dir"] / "actual.parquet", index=False)
        new_rows += score_gw(
            season=SEASON, gw=gw, xp=xp, actual=act, listed=listed,
            xp_sha256=doc["xp_sha256"], scored_at=stamp,
        )  # fmt: skip
        print(f"score_xp: scored GW{gw}")
    if not new_rows and not scores_p.exists():
        print("score_xp: nothing to score")
        return 0
    allr = pd.concat([old, pd.DataFrame(new_rows, columns=list(SCORE_FIELDS))], ignore_index=True)
    allr = allr.sort_values(["gw", "subset", "model"], kind="stable")
    allr.to_csv(scores_p, index=False, float_format="%.6f")
    pd.DataFrame(paired(allr), columns=list(PAIRED_FIELDS)).to_csv(
        root / "xp_scores_paired.csv", index=False, float_format="%.6f"
    )
    pops = []
    for doc in docs:
        ap = root / doc["xp_gold_dir"] / "actual.parquet"
        if int(doc["gw"]) in set(allr["gw"].astype(int)) and ap.exists():
            xp, _ = load_gw(doc, root)
            pops.append((SEASON, int(doc["gw"]), population(xp, pd.read_parquet(ap))[0]))
    models = sorted(allr["model"].unique())
    pd.DataFrame(calibration(pops, models)).to_csv(
        root / "xp_calibration.csv", index=False, float_format="%.4f"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
