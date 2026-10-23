"""The web data contract.

This is the seam (DP-04). Everything upstream is Python; everything downstream is TypeScript in a
browser; the only thing that crosses is these files, and their shape is defined by the JSON Schemas
in ``contracts/v1/`` rather than by whatever the publisher happened to emit.

Validation runs on the way out. Publishing an artefact that does not match its schema would break
the app in a way that only shows up in a browser, which is the slowest possible place to find out.

``rules.json`` is published deliberately (DL-14, Invariant 9): the browser's legality checks read
the same numbers the solver used, so a hardcoded club limit in a ``.tsx`` file is never necessary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

#: The contract's major version. Bumped only for a breaking change, which publishes ``v{n+1}``
#: beside ``v{n}`` until the app has moved (WEB-02). It is the single source: ``Contract.directory``
#: and the generated TypeScript constant (and through it the app's data path, the service
#: worker's cache name and URL pattern, the smoke check and the workflows' data paths) all derive
#: from it.
CONTRACT_VERSION = 1

#: The contract's minor version, published as ``meta.contract_minor``. **Bump it by one with every
#: additive change** (a new optional field, a new artefact): the schemas' ``const`` stays the major,
#: so an old app still accepts the data, and an app needing a newer minor than the data carries
#: shows a warning and renders what it can. Reset to 1 when the major is bumped.
CONTRACT_MINOR = 3

#: Artefact name -> schema filename. The published directory is exactly these files.
ARTEFACTS: dict[str, str] = {
    "meta": "meta.schema.json",
    "rules": "rules.schema.json",
    "players": "players.schema.json",
    "squad": "squad.schema.json",
    "week": "week.schema.json",
    "plan": "plan.schema.json",
    # The two trend artefacts (DL-37). Additive, so contract v1 does not bump: a client that has
    # never heard of them keeps working, which is the whole point of versioning the seam (DP-04).
    # Both are fetched lazily by the routes that need them, never in the app shell's eager load.
    "history": "history.schema.json",
    "fixtures": "fixtures.schema.json",
    # The mini-league (E6-S10). Written only when a league is configured, and it is not by default:
    # unlike every other artefact here, its *absence* is the normal published state.
    "league": "league.schema.json",
    # The data health page's artefact (E7-S6, DL-41). Additive like the trend pair above, and
    # fetched lazily by `/health` alone: it is the page you open when something looks wrong, so
    # putting it on the first-paint path would tax every other page for it.
    "health": "health.schema.json",
    # The season log (DL-69). Written only when a team ID is configured and the game has recorded
    # picks for it, so like `league` its absence is a normal published state. Fetched lazily by
    # `/log` alone.
    "log": "log.schema.json",
    # The five-model comparison, from the frozen harness's records. Written only when the
    # prospective harness has recorded a decision, so its absence is a normal published state.
    "models": "models.schema.json",
    # The 2025/26 model history: a backtest, built offline and checked in as a static file under
    # web/public/static/ because CI cannot run the backtest. Never written by the publish stage;
    # registered here so it is validated and gets generated TypeScript types.
    "models_history": "models_history.schema.json",
    # All-player next-GW xP MAE across seasons. Built from xp_scores CSVs and checked in / published
    # for the models page. Registered here for validation and generated TypeScript types.
    "xp_accuracy": "xp_accuracy.schema.json",
    # The strategy registry as published (MOD-03): every strategy's id, label, role and digest,
    # generated from config/strategies/. Additive, so contract v1 does not bump.
    "strategies": "strategies.schema.json",
}


class ContractViolationError(RuntimeError):
    """A published artefact did not match its schema. Nothing is written."""


@dataclass(frozen=True, slots=True)
class Contract:
    """The schema set for one contract version."""

    root: Path
    version: int = CONTRACT_VERSION

    @property
    def directory(self) -> Path:
        return self.root / f"v{self.version}"

    def schema(self, artefact: str) -> dict[str, Any]:
        path = self.directory / ARTEFACTS[artefact]
        if not path.exists():
            raise ContractViolationError(f"no schema for {artefact!r} at {path}")
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def validate(self, artefact: str, payload: Any) -> None:
        validator = jsonschema.Draft202012Validator(self.schema(artefact))
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
        if errors:
            detail = "; ".join(
                f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
                for error in errors[:10]
            )
            raise ContractViolationError(
                f"{artefact}.json does not match {ARTEFACTS[artefact]}: {detail}"
            )

    def write(
        self, artefact: str, payload: Any, destination: Path, filename: str | None = None
    ) -> Path:
        """Validate, then write. Never the other way round.

        ``filename`` names a second file in one artefact's schema — each strategy's own week and
        plan (MOD-04); it defaults to ``<artefact>.json``.
        """
        self.validate(artefact, payload)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / (filename or f"{artefact}.json")
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        return path


def find_contracts_root(start: Path | None = None) -> Path:
    """Locate the repository's ``contracts/`` directory."""
    from fpl_dof.paths import find_repo_root

    root = find_repo_root(start)
    if root is None:
        raise ContractViolationError(
            "could not locate the repository root, so contracts/ cannot be found"
        )
    directory = root / "contracts"
    if not directory.is_dir():
        raise ContractViolationError(f"{directory} does not exist")
    return directory
