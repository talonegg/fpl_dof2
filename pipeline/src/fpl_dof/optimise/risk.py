"""E4-S4 — the risk dial, and the ownership bet it implies. FR-21, FR-16, DL-07, DL-24.

**Ownership here is `selected_by_percent` and nothing else.** That is OD-06's resolution, recorded
at [DL-24](../../../../docs/planning/00-decision-log.md) before any of this was written. The
standard formula `EO = selected_by% + captained_by%` is correct and is *not computable from
public FPL data*: captaincy share is exposed by no public endpoint, and the gameweek data that is
published carries only a single most-captained player id — an id, not a distribution.

Two consequences this module is built around, and both are obligations rather than caveats:

1. **Every figure is labelled "selected by".** Never "effective ownership", never "captaincy share".
   A risk dial driven by an estimated quantity presented as a measured one is worse than no risk
   dial, because it invites confidence the number cannot carry.
2. **The most-captained player is a separate, plain callout**, not folded into a number that implies
   more precision than the data supports.

What the dial cannot see, stated once so it can be repeated wherever ownership is shown: it cannot
distinguish "60% own him and 40% of those captain him" from "60% own him and 5% captain him". That
is a real gap, and it is most visible at exactly the players the dial exists to reason about.

The second, quieter gap: `selected_by_percent` is ownership across all ~11m managers, while the
charter's target is the top 100k, whose template differs materially. DL-24 explicitly does not close
that one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from fpl_dof.config.models import RiskConfig

#: The label every ownership figure carries, in Python and in the browser. DL-24's exact wording.
OWNERSHIP_LABEL = "selected by"

#: Named here rather than written into each rendering site, because the honesty of the whole risk
#: dial rests on this sentence being present and identical everywhere.
OWNERSHIP_SOURCE_STATEMENT = (
    "Ownership is FPL's published `selected_by_percent` — the share of all managers who own the "
    "player. It is exact and it is not effective ownership: captaincy share is published by no FPL "
    "endpoint, so this figure cannot tell a heavily captained player from a merely popular one "
    "(OD-06, resolved at DL-24). It is also whole-field ownership, not the top-100k template this "
    "tool is aimed at."
)

DIAL_DESCRIPTIONS = {
    "safe": (
        "Safe — penalise deviation from the template. Owning the popular players caps the "
        "downside: when a 60%-owned forward hauls, not owning him is a large rank loss."
    ),
    "balanced": (
        "Balanced — a small penalty. Broadly follows expected points, avoiding only the most "
        "extreme template gaps. The default posture (OD-05, resolved at DL-25)."
    ),
    "aggressive": (
        "Aggressive — reward low ownership, favouring differentials with comparable expected "
        "points. For chasing rank from behind, or with genuine conviction in an edge."
    ),
}


@dataclass(frozen=True, slots=True)
class OwnershipPosition:
    """One player, how much of the field owns him, and which way you are betting on him."""

    player_id: int
    web_name: str
    selected_by_percent: float
    owned: bool
    starting: bool

    @property
    def deviation(self) -> float:
        """Signed percentage points of the field you are for or against.

        Positive when you own a player most managers do not; negative when you do not own one most
        managers do. It is the second that costs rank, and the second that is easy not to notice.
        """
        held = 100.0 if self.owned else 0.0
        return round(held - self.selected_by_percent, 2)


@dataclass(frozen=True, slots=True)
class OwnershipBet:
    """The bet, in the plain English Design §7.1 asks for. FR-16.

    Making it explicit is more valuable than any particular dial setting, because it is what lets a
    human apply judgement the model does not have.
    """

    dial: str
    dial_description: str
    source_statement: str
    ownership_label: str
    underweight: tuple[OwnershipPosition, ...]
    overweight: tuple[OwnershipPosition, ...]
    most_captained: MostCaptained | None
    statements: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "dial": self.dial,
            "dial_description": self.dial_description,
            "source_statement": self.source_statement,
            "ownership_label": self.ownership_label,
            "underweight": [_position_dict(p) for p in self.underweight],
            "overweight": [_position_dict(p) for p in self.overweight],
            "most_captained": self.most_captained.as_dict() if self.most_captained else None,
            "statements": list(self.statements),
        }


@dataclass(frozen=True, slots=True)
class MostCaptained:
    """The single most-captained player, surfaced as a plain callout (DL-24).

    ``player_id`` is ``None`` when the figure is not available. That is reported rather than
    omitted: "we do not know who the field is captaining" is information, and an absent callout
    reads as "nobody stands out", which is a different and wrong claim.
    """

    player_id: int | None
    web_name: str
    selected_by_percent: float
    owned: bool
    statement: str

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "web_name": self.web_name,
            "selected_by_percent": self.selected_by_percent,
            "owned": self.owned,
            "statement": self.statement,
        }


def _position_dict(position: OwnershipPosition) -> dict[str, object]:
    return {
        "player_id": position.player_id,
        "web_name": position.web_name,
        "selected_by_percent": position.selected_by_percent,
        "owned": position.owned,
        "starting": position.starting,
        "deviation": position.deviation,
    }


def dial_weight(config: RiskConfig) -> float:
    """Expected points per percentage point of ownership, per starter, per gameweek."""
    return config.ownership_weight.get(config.dial, 0.0)


def describe_dial(config: RiskConfig) -> str:
    return DIAL_DESCRIPTIONS.get(config.dial, config.dial)


def ownership_bet(
    *,
    squad: Iterable[int],
    starting: Iterable[int],
    ownership: Mapping[int, float],
    names: Mapping[int, str],
    config: RiskConfig,
    most_captained_id: int | None = None,
    top_n: int = 5,
) -> OwnershipBet:
    """State the bet the recommended squad is making against the field.

    Both directions, always. A tool that only reports the differentials you own flatters the
    recommendation: the exposure that actually moves rank is usually the popular player you have
    *left out*, and that one is invisible unless it is listed.
    """
    owned = {int(i) for i in squad}
    started = {int(i) for i in starting}

    positions = [
        OwnershipPosition(
            player_id=player_id,
            web_name=names.get(player_id, str(player_id)),
            selected_by_percent=round(float(share), 2),
            owned=player_id in owned,
            starting=player_id in started,
        )
        for player_id, share in ownership.items()
    ]

    underweight = tuple(
        sorted(
            (p for p in positions if not p.owned and p.selected_by_percent > 0),
            key=lambda p: (-p.selected_by_percent, p.player_id),
        )[:top_n]
    )
    overweight = tuple(
        sorted(
            (p for p in positions if p.owned),
            key=lambda p: (p.selected_by_percent, p.player_id),
        )[:top_n]
    )

    captain_callout = _most_captained(most_captained_id, ownership, names, owned)
    return OwnershipBet(
        dial=config.dial,
        dial_description=describe_dial(config),
        source_statement=OWNERSHIP_SOURCE_STATEMENT,
        ownership_label=OWNERSHIP_LABEL,
        underweight=underweight,
        overweight=overweight,
        most_captained=captain_callout,
        statements=_statements(underweight, overweight, captain_callout),
    )


def _most_captained(
    most_captained_id: int | None,
    ownership: Mapping[int, float],
    names: Mapping[int, str],
    owned: set[int],
) -> MostCaptained | None:
    if most_captained_id is None:
        return MostCaptained(
            player_id=None,
            web_name="",
            selected_by_percent=0.0,
            owned=False,
            statement=(
                "The most-captained player for this gameweek is not available in the published "
                "data, so this recommendation cannot tell you where the field's captaincy is "
                "concentrated (D-15)."
            ),
        )
    player_id = int(most_captained_id)
    share = round(float(ownership.get(player_id, 0.0)), 2)
    name = names.get(player_id, str(player_id))
    held = player_id in owned
    stance = "you own him" if held else "you do not own him"
    return MostCaptained(
        player_id=player_id,
        web_name=name,
        selected_by_percent=share,
        owned=held,
        statement=(
            f"{share:.1f}% of managers are {OWNERSHIP_LABEL} {name}, and he is this gameweek's "
            f"most-captained pick — {stance}."
        ),
    )


def _statements(
    underweight: Sequence[OwnershipPosition],
    overweight: Sequence[OwnershipPosition],
    most_captained: MostCaptained | None,
) -> tuple[str, ...]:
    lines: list[str] = []
    for position in underweight:
        lines.append(
            f"You are {abs(position.deviation):.0f}% underweight on {position.web_name} "
            f"({position.selected_by_percent:.1f}% {OWNERSHIP_LABEL}): you gain if he blanks and "
            "lose ground on most of the field if he hauls."
        )
    for position in overweight:
        lines.append(
            f"You are {position.deviation:.0f}% overweight on {position.web_name} "
            f"({position.selected_by_percent:.1f}% {OWNERSHIP_LABEL}): a differential, so he wins "
            "you rank if he returns and costs you little if he does not."
        )
    if most_captained is not None and most_captained.player_id is not None:
        lines.append(most_captained.statement)
    return tuple(lines)


__all__ = [
    "DIAL_DESCRIPTIONS",
    "OWNERSHIP_LABEL",
    "OWNERSHIP_SOURCE_STATEMENT",
    "MostCaptained",
    "OwnershipBet",
    "OwnershipPosition",
    "describe_dial",
    "dial_weight",
    "ownership_bet",
]
