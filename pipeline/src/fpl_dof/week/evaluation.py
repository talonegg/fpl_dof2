"""The evaluation step's seam: which gameweeks are evaluated, and the step a Finished one is due.

ORC-05 builds the step and writes ``ledger:evaluation/gwNN.json``, stamped with the realised-points
scorer's version (ORC-04). Until then this module only reads those files, so the gameweek state can
tell Finished from Evaluated (ORC-01), and :func:`evaluate` is a logged no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

from fpl_dof.gameweek import GameweekState
from fpl_dof.obs.logging import get_logger
from fpl_dof.paths import DataLayout

log = get_logger(__name__)

EVALUATION_DIRECTORY = "evaluation"

#: The scorer version an evaluation must be stamped with to count. ORC-04/05 own it: a new scorer
#: version makes every gameweek Finished again, and so evaluated again.
SCORER_VERSION = "0"


def evaluation_path(layout: DataLayout, gameweek: int) -> Path:
    """``<data>/ledger/evaluation/gw05.json``, named as the advice is."""
    return layout.ledger / EVALUATION_DIRECTORY / f"gw{gameweek:02d}.json"


def evaluated(layout: DataLayout) -> frozenset[int]:
    """The gameweeks whose evaluation is stamped with :data:`SCORER_VERSION`.

    An unreadable file counts as not evaluated, logged: the step runs again rather than the
    gameweek being judged on nothing (DP-15).
    """
    directory = layout.ledger / EVALUATION_DIRECTORY
    done: set[int] = set()
    for path in directory.glob("gw*.json") if directory.is_dir() else ():
        try:
            gameweek = int(path.stem.removeprefix("gw"))
            stamp = json.loads(path.read_text(encoding="utf-8")).get("scorer_version")
        except (ValueError, OSError, AttributeError) as exc:
            log.warning("evaluation.unreadable", extra={"path": str(path), "detail": str(exc)})
            continue
        if stamp == SCORER_VERSION:
            done.add(gameweek)
    return frozenset(done)


def evaluate(state: GameweekState, layout: DataLayout) -> None:
    """The evaluation step for a Finished gameweek. ORC-05 fills it; until then it only logs."""
    log.info(
        "evaluation.due",
        extra={
            "gameweek": state.gameweek,
            "path": str(evaluation_path(layout, state.gameweek)),
            "detail": "the evaluation step is not built yet (ORC-05)",
        },
    )
