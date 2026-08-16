"""E4-S6 — the explanation layer. FR-23, FR-24.

A recommendation nobody can argue with is a recommendation nobody should follow. Everything here
exists so that the answer to "why?" is in the artefact rather than in the solver's head:
decomposition, the marginal gain over doing nothing, the runners-up and *why they lost*, the
ownership bet in plain English, the price exposure, and the assumptions the number rests on.

**"Roll the transfer" is a first-class candidate, always shown**, with its own number attached. A
recommendation to hold is a decision, not the absence of one, and presenting it as a blank space is
how a manager talks themselves into a hit.

The D-13 caveat
---------------
[DL-21](../../../../docs/planning/00-decision-log.md) found the forecast loses to a model-free
benchmark on top-20 precision — the exact part of the ranking a hit, a chip or a wildcard acts on —
and opened D-13. E4's own §0 makes the consequence a constraint on this epic rather than a footnote:

    No -8 hit, chip or wildcard may be justified by `xp_v1` alone until top-20 precision beats B0.

So the caveat is a **field on the recommendation**, not a log line and not a footnote: it travels
through the contract, and the panel that renders a hit, a chip or a wildcard renders it too. Closing
D-13 is not this epic's scope. Not silently proceeding as though it were closed is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from fpl_dof.optimise.chips import chip_label
from fpl_dof.optimise.risk import OwnershipBet

#: Recommendation kinds a caveat can attach to.
APPLIES_HIT = "hit"
APPLIES_CHIP = "chip"
APPLIES_WILDCARD = "wildcard"


@dataclass(frozen=True, slots=True)
class Caveat:
    """Something a human must weigh before acting, carried on the recommendation itself."""

    code: str
    headline: str
    detail: str
    applies_to: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "headline": self.headline,
            "detail": self.detail,
            "applies_to": list(self.applies_to),
        }


D13_CAVEAT = Caveat(
    code="D-13",
    headline="This call rests on a forecast that is unvalidated at the head of the ranking.",
    detail=(
        "The walk-forward backtest (DL-21) found the expected-points model has the best mean "
        "absolute error of anything measured and the *worst* top-20 precision — 0.00 against 0.05 "
        "for a price-and-position baseline. Hits, chips and wildcards act on the head of the "
        "ranking, which is exactly where the model has not yet earned trust. Treat this as an "
        "option to weigh, not a settled recommendation, and do not take it on the model's word "
        "alone. Debt D-13 tracks closing this; it is not closed."
    ),
    applies_to=(APPLIES_HIT, APPLIES_CHIP, APPLIES_WILDCARD),
)


D21_CAVEAT = Caveat(
    code="D-21",
    headline="The chip-timing re-rank concentrates on the front of the horizon, unexplained.",
    detail=(
        "Replayed against eight real historical deadlines (DL-28), the simulation re-rank changed "
        "the chip recommendation at every one of them, and at the default Balanced dial it moved "
        "the chip to the *first* gameweek of the horizon every time. A three-dial probe shows this "
        "is not a fixed artefact — the safe dial declined to move the chip at all at one deadline, "
        "and the aggressive dial chose a different week at another — so the percentile genuinely "
        "responds to the dial. But the front-loading at the two dials most likely to be run is a "
        "strong regularity nothing yet explains. The re-rank is proven to move a chip decision and "
        "to respond to the dial; it is not proven to time chips well. Do not play a chip on the "
        "re-rank's timing alone. Debt D-21 tracks identifying the mechanism; it is not closed."
    ),
    applies_to=(APPLIES_CHIP,),
)


def caveats_for(*, takes_hit: bool, chips_played: Iterable[str] = ()) -> tuple[Caveat, ...]:
    """The caveats a recommendation must carry, given what it actually recommends.

    Deliberately computed from the recommendation rather than attached everywhere: a caveat printed
    on advice that does not need it is a caveat nobody reads by November, and an unread caveat has
    the same effect as none.
    """
    chips = tuple(chips_played)
    if not takes_hit and not chips:
        return ()
    return (D13_CAVEAT, D21_CAVEAT) if chips else (D13_CAVEAT,)


@dataclass(frozen=True, slots=True)
class Contribution:
    """One line of the decomposition: where the expected points came from."""

    label: str
    points: float
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"label": self.label, "points": round(self.points, 3), "detail": self.detail}


@dataclass(frozen=True, slots=True)
class RunnerUp:
    """An option that lost, and by how much. The margin is the argument."""

    label: str
    total_expected_points: float
    margin: float
    """Negative: how far short of the recommendation this option fell."""

    simulated_score: float | None
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "total_expected_points": round(self.total_expected_points, 3),
            "margin": round(self.margin, 3),
            "simulated_score": (
                None if self.simulated_score is None else round(self.simulated_score, 3)
            ),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PriceExposure:
    """What the plan does to the squad's money, which is not the same as what it does to points."""

    spend: float
    bank_after: float
    sell_value_committed: float
    players_bought: int
    players_sold: int
    statement: str

    def as_dict(self) -> dict[str, object]:
        return {
            "spend": round(self.spend, 1),
            "bank_after": round(self.bank_after, 1),
            "sell_value_committed": round(self.sell_value_committed, 1),
            "players_bought": self.players_bought,
            "players_sold": self.players_sold,
            "statement": self.statement,
        }


@dataclass(frozen=True, slots=True)
class Explanation:
    """Everything behind one recommendation."""

    headline: str
    marginal_gain_over_doing_nothing: float
    decomposition: tuple[Contribution, ...]
    runners_up: tuple[RunnerUp, ...]
    ownership_bet: OwnershipBet | None
    price_exposure: PriceExposure | None
    assumptions: tuple[str, ...]
    caveats: tuple[Caveat, ...] = field(default=())

    @property
    def has_caveats(self) -> bool:
        return bool(self.caveats)

    def as_dict(self) -> dict[str, object]:
        return {
            "headline": self.headline,
            "marginal_gain_over_doing_nothing": round(self.marginal_gain_over_doing_nothing, 3),
            "decomposition": [item.as_dict() for item in self.decomposition],
            "runners_up": [item.as_dict() for item in self.runners_up],
            "ownership_bet": self.ownership_bet.as_dict() if self.ownership_bet else None,
            "price_exposure": self.price_exposure.as_dict() if self.price_exposure else None,
            "assumptions": list(self.assumptions),
            "caveats": [caveat.as_dict() for caveat in self.caveats],
        }


def start_probability_assumptions(
    player_ids: Iterable[int],
    *,
    names: Mapping[int, str],
    start_probability: Mapping[int, float],
    threshold: float = 0.85,
    limit: int = 5,
) -> tuple[str, ...]:
    """ "This assumes he starts, which the model puts at 71%" — the epic's own example.

    Only the players the assumption is doing work for. Listing every starter at 95% buries the one
    at 55%, which is the only one worth reading.
    """
    doubtful = sorted(
        (
            (int(player_id), float(start_probability.get(int(player_id), 1.0)))
            for player_id in player_ids
        ),
        key=lambda pair: (pair[1], pair[0]),
    )
    return tuple(
        f"{names.get(player_id, str(player_id))} is assumed to start, which the model puts at "
        f"{probability:.0%}."
        for player_id, probability in doubtful
        if probability < threshold
    )[:limit]


def price_exposure(
    *,
    bought: Sequence[float],
    sold: Sequence[float],
    bank_after: float,
) -> PriceExposure:
    spend = float(sum(bought))
    raised = float(sum(sold))
    if not bought and not sold:
        statement = "No money moves: the plan holds the squad it has."
    else:
        statement = (
            f"£{spend:.1f}m committed to {len(bought)} incoming player(s), funded by "
            f"£{raised:.1f}m "
            f"raised from {len(sold)} outgoing, leaving £{bank_after:.1f}m in the bank. Selling "
            "value already reflects the sell-on fee, so this is money you can actually spend."
        )
    return PriceExposure(
        spend=spend,
        bank_after=bank_after,
        sell_value_committed=raised,
        players_bought=len(bought),
        players_sold=len(sold),
        statement=statement,
    )


def chip_margin_sentence(
    *, chip: str, gameweek: int, runner_up: RunnerUp | None, versus_nothing: float | None
) -> str:
    """Design §6.3's own example sentence, which is the point of enumerating scenarios.

    "Free Hit in GW18 beats GW17 by 4.1 points and beats not playing it by 9.3" is a claim a human
    can argue with. A chip binary flipping inside a solver is not.
    """
    parts = [f"{chip_label(chip)} in GW{gameweek}"]
    if runner_up is not None:
        parts.append(f"beats {runner_up.label} by {abs(runner_up.margin):.1f} points")
    if versus_nothing is not None:
        parts.append(f"beats playing no chip by {versus_nothing:.1f}")
    return " ".join([parts[0], "; ".join(parts[1:])]).strip().rstrip(",") + "."


__all__ = [
    "APPLIES_CHIP",
    "APPLIES_HIT",
    "APPLIES_WILDCARD",
    "D13_CAVEAT",
    "D21_CAVEAT",
    "Caveat",
    "Contribution",
    "Explanation",
    "PriceExposure",
    "RunnerUp",
    "caveats_for",
    "chip_margin_sentence",
    "price_exposure",
    "start_probability_assumptions",
]
