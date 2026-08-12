"""Entity resolution — matching a source's players onto canonical ones (FR-07, R-10).

**Why this is the most dangerous code in the repository.** A mismatch attributes one footballer's
expected goals to another. Nothing raises, no schema fails, no gate for volume or freshness sees
anything unusual, and the model becomes confidently wrong about exactly the players it has the most
data on. Every design decision here is a trade of coverage for safety, in that direction.

Three tiers, per Design §3.2:

1. **Deterministic** — normalised name plus club plus position. No judgement, no threshold.
2. **Fuzzy** — token-set similarity within the same club, accepted only above a high threshold
   *and* only when it beats the runner-up by a configured margin. Ambiguity is refused, not
   resolved.
3. **Override** — a committed, reviewed mapping in ``entity_overrides.yaml``. Checked first,
   because a human who has looked at the player outranks any amount of string comparison.

Everything else is recorded as ``unmatched`` and kept. A dropped row is an invisible gap; a row
marked unmatched is a number on the data-health page and a quality gate with something to measure.

**Two guardrails that are not negotiable.** One canonical player claimed by two players from the
same source raises immediately — that is not a low-confidence match, it is a contradiction, and
continuing would merge two careers. And resolution is keyed by season and re-run from scratch each
one, because club-based matching is invalidated the moment somebody transfers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from fpl_dof.config.models import EntityResolutionConfig
from fpl_dof.frames import as_int
from fpl_dof.obs.logging import get_logger
from fpl_dof.silver.tables import Table, columns_for
from fpl_dof.sources.names import normalise, team_key, token_set_ratio

log = get_logger(__name__)

OVERRIDES_FILENAME = "entity_overrides.yaml"

#: Columns an adapter fills in when it emits a crosswalk row. Resolution fills in the rest.
REF_COLUMNS: tuple[str, ...] = (
    "season",
    "source",
    "source_player_id",
    "source_name",
    "source_team",
    "source_position",
)


class ResolutionConflictError(RuntimeError):
    """Two players from one source resolved to the same canonical player.

    A hard failure rather than a gate, deliberately. A conflict is not "the data looks thin", it is
    two mutually exclusive statements about who somebody is, and the only safe response is to stop
    before either of them reaches a model.
    """


@dataclass(frozen=True, slots=True)
class Candidate:
    player_id: int
    player_code: int
    full_name: str
    web_name: str
    team: str
    position: str


@dataclass
class ResolutionReport:
    """What resolution did, per source. Rolled into warnings and the gate context."""

    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def unmatched_rate(self, source: str) -> float:
        counts = self.counts.get(source, {})
        total = sum(counts.values())
        return counts.get("unmatched", 0) / total if total else 0.0


def load_overrides(directory: Path | None = None) -> dict[str, dict[str, int]]:
    """Read the committed override file. Missing or empty is normal and means no overrides."""
    path = (directory or Path(__file__).parent) / OVERRIDES_FILENAME
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not loaded:
        return {}
    if not isinstance(loaded, Mapping):
        raise ResolutionConflictError(f"{path} must contain a mapping of source -> id -> code")
    return {
        str(source): {str(key): int(value) for key, value in (entries or {}).items()}
        for source, entries in loaded.items()
    }


def _candidates(players: pd.DataFrame, teams: pd.DataFrame) -> list[Candidate]:
    names = {as_int(row.team_id): str(row.name) for row in teams.itertuples()}
    return [
        Candidate(
            player_id=as_int(row.player_id),
            player_code=as_int(row.code),
            full_name=str(row.full_name),
            web_name=str(row.web_name),
            team=team_key(names.get(as_int(row.team_id), "")),
            position=str(row.position),
        )
        for row in players.itertuples()
    ]


def _deterministic_index(
    candidates: list[Candidate],
) -> dict[tuple[str, str, str], list[Candidate]]:
    index: dict[tuple[str, str, str], list[Candidate]] = {}
    for candidate in candidates:
        for name in {normalise(candidate.full_name), normalise(candidate.web_name)}:
            index.setdefault((name, candidate.team, candidate.position), []).append(candidate)
    return index


def _deterministic_match(
    name: str,
    club: str,
    position: str | None,
    index: dict[tuple[str, str, str], list[Candidate]],
    config: EntityResolutionConfig,
) -> Candidate | None:
    """Exact normalised name plus club, and position too when it is being trusted.

    Only ever returns a match when it is unique. Two players in one club with the same normalised
    name is rare and real — two Rodrigos in a Manchester City squad is not a hypothetical — and the
    right answer there is to fall through to the override file rather than to pick one.
    """
    positions = (
        [position] if position and config.match_on_position else ["GKP", "DEF", "MID", "FWD"]
    )
    found = [
        candidate
        for candidate_position in positions
        for candidate in index.get((name, club, candidate_position), [])
    ]
    unique = {candidate.player_id: candidate for candidate in found}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _fuzzy_match(
    name: str,
    club: str,
    position: str | None,
    candidates: list[Candidate],
    config: EntityResolutionConfig,
) -> tuple[Candidate | None, float]:
    """Best candidate within the club, or nothing when the choice is not clear-cut."""
    scored = sorted(
        (
            (
                max(
                    token_set_ratio(name, candidate.full_name),
                    token_set_ratio(name, candidate.web_name),
                ),
                candidate,
            )
            for candidate in candidates
            if candidate.team == club
            and (position is None or not config.match_on_position or candidate.position == position)
        ),
        key=lambda pair: (-pair[0], pair[1].player_id),
    )
    if not scored:
        return None, 0.0
    best_score, best = scored[0]
    if best_score < config.fuzzy_threshold:
        return None, best_score
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_score - runner_up < config.fuzzy_margin:
        # Two plausible people. Refusing is the whole point: an unmatched player is visible, and a
        # coin-flipped one is not.
        return None, best_score
    return best, best_score


def resolve(
    refs: pd.DataFrame,
    players: pd.DataFrame,
    teams: pd.DataFrame,
    *,
    season: str,
    config: EntityResolutionConfig,
    overrides: Mapping[str, Mapping[str, int]] | None = None,
) -> tuple[pd.DataFrame, ResolutionReport]:
    """Resolve every source reference to a canonical player, or record that it could not be.

    Pure: frames in, frames out, no I/O and no clock (DP-03). ``season`` is passed rather than read
    so that a re-run for a different season cannot pick up this one's answers by accident.
    """
    report = ResolutionReport()
    columns = columns_for(Table.PLAYER_CROSSWALK)
    if refs.empty:
        return pd.DataFrame(columns=columns), report

    candidates = _candidates(players, teams)
    by_code = {candidate.player_code: candidate for candidate in candidates}
    index = _deterministic_index(candidates)
    override_map = {source: dict(entries) for source, entries in (overrides or {}).items()}

    rows: list[dict[str, object]] = []
    claimed: dict[tuple[str, int], str] = {}

    for record in refs.sort_values(["source", "source_player_id"]).itertuples():
        source = str(record.source)
        source_id = str(record.source_player_id)
        name = str(record.source_name)
        club = team_key(str(record.source_team or ""))
        position = str(record.source_position) if pd.notna(record.source_position) else None

        matched: Candidate | None = None
        method = "unmatched"
        confidence = 0.0

        code = override_map.get(source, {}).get(source_id)
        if code is not None:
            matched = by_code.get(code)
            if matched is None:
                report.warnings.append(
                    f"{source}: override for {source_id} points at player code {code}, which is "
                    "not in this season's player list; the override is stale and was ignored"
                )
            else:
                method, confidence = "override", 1.0

        if matched is None:
            found = _deterministic_match(normalise(name), club, position, index, config)
            if found is not None:
                matched, method, confidence = found, "deterministic", 1.0

        if matched is None:
            found, score = _fuzzy_match(name, club, position, candidates, config)
            if found is not None:
                matched, method, confidence = found, "fuzzy", round(score, 4)

        if matched is not None:
            owner = claimed.get((source, matched.player_id))
            if owner is not None:
                raise ResolutionConflictError(
                    f"{source} players {owner!r} and {source_id!r} both resolved to canonical "
                    f"player {matched.player_id} ({matched.full_name}); one source cannot hold two "
                    "identities for one footballer, and continuing would merge them"
                )
            claimed[(source, matched.player_id)] = source_id

        rows.append(
            {
                "season": season,
                "source": source,
                "source_player_id": source_id,
                "source_name": name,
                "source_team": str(record.source_team or "") or None,
                "source_position": position,
                "player_id": matched.player_id if matched else None,
                "player_code": matched.player_code if matched else None,
                "match_method": method,
                "confidence": confidence,
                "verified": method == "override",
            }
        )
        report.counts.setdefault(source, {}).setdefault(method, 0)
        report.counts[source][method] += 1

    for source, counts in sorted(report.counts.items()):
        rate = report.unmatched_rate(source)
        log.info(
            "resolve.source",
            extra={"source": source, "counts": counts, "unmatched_rate": round(rate, 4)},
        )
        if counts.get("unmatched"):
            report.warnings.append(
                f"{source}: {counts['unmatched']} of {sum(counts.values())} players unmatched "
                f"({rate:.1%})"
            )

    return pd.DataFrame(rows, columns=columns), report


def resolve_teams(names: pd.Series, teams: pd.DataFrame) -> dict[str, int]:
    """Map club names as a source writes them onto canonical team ids.

    Exact on the reduced key only. A wrong club is cheap to notice and expensive to guess at: it
    silently reassigns a whole fixture's goal expectation to the wrong twenty players.
    """
    lookup: dict[str, int] = {}
    for row in teams.itertuples():
        lookup[team_key(str(row.name))] = as_int(row.team_id)
        lookup.setdefault(team_key(str(row.short_name)), as_int(row.team_id))
    return {
        str(value): lookup[team_key(str(value))]
        for value in names.dropna().unique()
        if team_key(str(value)) in lookup
    }


__all__ = [
    "OVERRIDES_FILENAME",
    "REF_COLUMNS",
    "Candidate",
    "ResolutionConflictError",
    "ResolutionReport",
    "load_overrides",
    "resolve",
    "resolve_teams",
]
