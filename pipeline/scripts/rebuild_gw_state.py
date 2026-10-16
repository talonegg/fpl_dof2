#!/usr/bin/env python3
"""Rebuild per-model ``state/<model>.json`` for a gameweek whose decision was written but whose
state was lost (GW7: run 38974140926, decide.py crashed on the missing ``state/`` dir right after
``decisions/GW7.json`` was written, so ``prospective/gw07.tgz`` on `ledger` has no state/).

How: replay the frozen policy (``policy.decide``) for each model with exactly what decide.py used
-- the same starting state (seeded from ``real_squad_start`` in the decision, as decide.py does
when no state exists), the hashed xP file kept under ``data/gold/xp/GW{n}/`` and the model's
frozen config -- then check the replayed pick reproduces the recorded one (transfers, captain,
vice, hit) before writing anything. Any mismatch or hash failure aborts with nothing written.

Read-only on its input. Writes only to ``--out`` (a scratch dir; refuses an existing state/).
Must run where the frozen bundle is extracted at its frozen paths (as in the CI prospective job):

    python pipeline/scripts/rebuild_gw_state.py --root /tmp/gw07 --gw 7 --out /tmp/gw07-state

Never run it against the `ledger` checkout. Landing the result on `ledger` is a separate,
approved step (repack gw07.tgz with state/ added, or let GW8's run restore it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

FROZEN = Path("/workspace/fpl_dof2_frozen")
HARNESS = Path("/workspace/fpl_prospective")
COMPARED = ("transfers", "captain_name", "vice_name", "hit_points")


def seed_state(decision: dict[str, Any], name: str) -> dict[str, Any]:
    """The state decide.py starts a model from when ``state/<model>.json`` does not exist."""
    real = decision["real_squad_start"]
    return dict(
        model=name,
        next_gw=decision["gw"],
        **{k: real[k] for k in ("players", "bank", "free_transfers")},
        log=[],
        started_from=real["source"],
    )


def check_pick(name: str, replayed: dict[str, Any], recorded: dict[str, Any]) -> list[str]:
    return [
        f"{name}.{k}: replayed {replayed.get(k)!r} != recorded {recorded.get(k)!r}"
        for k in COMPARED
        if replayed.get(k) != recorded.get(k)
    ]


def rebuild(
    root: Path,
    gw: int,
    pdecide: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
    models: dict[str, Any],
    cfg: Any,
    rules: Any,
    read_xp: Callable[[Path], Any],
) -> dict[str, dict[str, Any]]:
    decision = json.loads((root / "decisions" / f"GW{gw}.json").read_text())
    gold = root / decision["xp_gold_dir"]
    states: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for name, m in models.items():
        xp = gold / f"xp_{name}.parquet"
        sha = hashlib.sha256(xp.read_bytes()).hexdigest()
        if sha != decision["xp_sha256"][name]:
            problems.append(f"{name}: {xp} sha256 {sha} != recorded {decision['xp_sha256'][name]}")
            continue
        st = seed_state(decision, name)
        pick, ns = pdecide(read_xp(xp), json.loads(json.dumps(st)), gw, m["config"], cfg, rules)
        problems += check_pick(name, pick, decision["models"][name])
        states[name] = ns
    if problems:
        raise SystemExit("refusing to write state:\n  " + "\n  ".join(problems))
    return states


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="an unpacked record (scratch copy)")
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if "ledger" in a.out.resolve().parts or (a.out / "state").exists():
        raise SystemExit(f"refusing to write into {a.out}")
    sys.path[:0] = [
        str(FROZEN / "pipeline/src"),
        str(FROZEN / "backtest"),
        str(HARNESS / "prospective"),
    ]
    import pandas as pd
    from models import MODELS  # type: ignore[import-not-found]

    os.chdir(FROZEN)
    import backtest as bt  # type: ignore[import-not-found]
    from backtest import CFG
    from common import DATA_DIR  # type: ignore[import-not-found]
    from policy import decide as pdecide  # type: ignore[import-not-found]

    rules, _ = bt.load(str(DATA_DIR), ["2026/27"])
    states = rebuild(a.root, a.gw, pdecide, MODELS, CFG(), rules, pd.read_parquet)
    (a.out / "state").mkdir(parents=True)
    for name, ns in states.items():
        (a.out / "state" / f"{name}.json").write_text(json.dumps(ns, indent=2))
    print(f"wrote {len(states)} states to {a.out / 'state'} (picks reproduced exactly)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
