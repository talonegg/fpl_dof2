"""Things you should be told without having to look for them.

The design constraint here is not detection, it is **attention**. A weekly output that lists
everything interesting is a weekly output nobody reads by November, and the failure mode of an
unread alert is identical to the failure mode of no alert. So severity is scarce: ``URGENT`` is
reserved for things that are irreversible or dated, and everything else has to earn its place.

Four families:

*Availability* — an owned player is injured, suspended or doubtful. The single most common cause of
a wasted gameweek, and the one thing the forecast cannot fix on its own because the news arrives
after the model has run.

*Price* — an owned player is close to a rise or fall. A rule of thumb, and labelled as one: FPL does
not publish the price algorithm, so this is net transfer pressure and nothing more.

*Chip expiry* (E2-S7) — the deliberately dumb insurance policy. Set-one chips expire at a published
gameweek and are simply gone afterwards. This is not a chip *planner* — that is E4-S3 — and it does
not try to be. It exists because E4-S3 sits last in the sequence and the thing that gets lost if it
slips is four chips.

*Squad state* — the reconstruction warned about something, or the free-transfer count is at its cap
and about to be wasted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import pandas as pd

from fpl_dof.config.models import AlertsConfig
from fpl_dof.frames import as_float, as_int
from fpl_dof.rules.models import GameRules
from fpl_dof.squad.state import SquadState


class AlertSeverity(IntEnum):
    """Ordered so sorting puts the things that cannot be undone at the top."""

    INFO = 10
    WARNING = 20
    URGENT = 30

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class Alert:
    severity: AlertSeverity
    category: str
    message: str
    player_id: int | None = None
    detail: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity.label,
            "category": self.category,
            "message": self.message,
            "player_id": self.player_id,
            "detail": self.detail or {},
        }


def collect_alerts(
    *,
    state: SquadState,
    players: pd.DataFrame,
    rules: GameRules,
    config: AlertsConfig,
    current_gameweek: int,
    chips: pd.DataFrame | None = None,
) -> list[Alert]:
    """Everything worth saying this week, most urgent first."""
    alerts: list[Alert] = []
    alerts.extend(_availability(state, players, config))
    alerts.extend(_price_pressure(state, players, config))
    alerts.extend(_chip_expiry(state, chips, config, current_gameweek))
    alerts.extend(_squad_state(state, rules))
    return sorted(alerts, key=lambda a: (-a.severity, a.category, a.player_id or 0))


def _owned(state: SquadState, players: pd.DataFrame) -> pd.DataFrame:
    return players[players["player_id"].isin(state.player_ids())]


def _availability(state: SquadState, players: pd.DataFrame, config: AlertsConfig) -> list[Alert]:
    alerts: list[Alert] = []
    for row in _owned(state, players).itertuples():
        player_id = as_int(row.player_id)
        name = str(getattr(row, "web_name", player_id))
        status = str(row.status)
        news = str(getattr(row, "news", "") or "")
        chance = getattr(row, "chance_of_playing_next_round", None)

        if status in {"i", "s", "u"}:
            alerts.append(
                Alert(
                    severity=AlertSeverity.URGENT,
                    category="availability",
                    message=f"{name} is unavailable ({_status_label(status)})"
                    + (f": {news}" if news else ""),
                    player_id=player_id,
                    detail={"status": status, "news": news},
                )
            )
        elif status == "d" or (
            chance is not None
            and not pd.isna(chance)
            and as_float(chance) <= config.doubtful_chance_threshold
        ):
            odds = "" if chance is None or pd.isna(chance) else f" ({as_float(chance):.0f}% chance)"
            alerts.append(
                Alert(
                    severity=AlertSeverity.WARNING,
                    category="availability",
                    message=f"{name} is doubtful{odds}" + (f": {news}" if news else ""),
                    player_id=player_id,
                    detail={"status": status, "chance": None if chance is None else chance},
                )
            )
    return alerts


def _status_label(status: str) -> str:
    return {"i": "injured", "s": "suspended", "u": "unavailable", "n": "not in squad"}.get(
        status, status
    )


def _price_pressure(state: SquadState, players: pd.DataFrame, config: AlertsConfig) -> list[Alert]:
    """Net transfer pressure on owned players.

    A heuristic and nothing more. FPL has never published the price-change algorithm, so this says
    "under pressure", not "will change tonight" — and the difference matters, because acting on a
    confident-sounding guess about a rise is how a manager takes a needless early hit.
    """
    if "transfers_in_event" not in players.columns:
        return []
    total = as_float(players["selected_by_percent"].sum())
    if total <= 0:
        return []

    alerts: list[Alert] = []
    for row in _owned(state, players).itertuples():
        net = as_int(row.transfers_in_event) - as_int(row.transfers_out_event)
        share = abs(net) / max(total, 1.0)
        if share < config.price_change_ownership_threshold:
            continue
        name = str(getattr(row, "web_name", row.player_id))
        direction = "rise" if net > 0 else "fall"
        alerts.append(
            Alert(
                severity=AlertSeverity.INFO,
                category="price",
                message=(
                    f"{name} is under pressure to {direction} "
                    f"(net {net:+,} transfers this gameweek)"
                ),
                player_id=as_int(row.player_id),
                detail={"net_transfers": net, "direction": direction},
            )
        )
    return alerts


def _chip_expiry(
    state: SquadState,
    chips: pd.DataFrame | None,
    config: AlertsConfig,
    current_gameweek: int,
) -> list[Alert]:
    """Unused chips, and how long is left. E2-S7.

    The expiry gameweek is **read from the chip table**, which comes from the API's own chip
    windows. "Set one expires at GW19" is true this season, and writing it down is exactly the kind
    of fact that quietly stops being true (Invariant 2).
    """
    if chips is None or chips.empty:
        return []

    used = set(state.chips_used)
    alerts: list[Alert] = []
    # Group by expiry so a "set" is derived from the data rather than assumed to be four chips.
    for stop_event, group in chips.groupby("stop_event"):
        stop = as_int(stop_event)
        if stop < current_gameweek:
            continue
        remaining = sorted(
            {
                str(row.name_)
                for row in group.rename(columns={"name": "name_"}).itertuples()
                if str(row.name_) not in used
            }
        )
        if not remaining:
            continue
        weeks_left = stop - current_gameweek

        if current_gameweek >= config.chip_urgent_gameweek:
            severity = AlertSeverity.URGENT
        elif current_gameweek >= config.chip_warning_gameweek:
            severity = AlertSeverity.WARNING
        else:
            severity = AlertSeverity.INFO

        alerts.append(
            Alert(
                severity=severity,
                category="chips",
                message=(
                    f"{len(remaining)} unused chip(s) expire at the gameweek {stop} deadline "
                    f"({weeks_left} gameweek(s) away): {', '.join(remaining)}"
                ),
                detail={
                    "expires_gameweek": stop,
                    "gameweeks_remaining": weeks_left,
                    "chips": remaining,
                },
            )
        )
    return alerts


def _squad_state(state: SquadState, rules: GameRules) -> list[Alert]:
    alerts = [
        Alert(
            severity=AlertSeverity.WARNING,
            category="squad_state",
            message=warning,
        )
        for warning in state.warnings
    ]
    if state.free_transfers >= rules.transfers.max_free_transfers:
        alerts.append(
            Alert(
                severity=AlertSeverity.WARNING,
                category="transfers",
                message=(
                    f"free transfers are at the maximum of {state.free_transfers}; another week of "
                    "rolling earns nothing, so an unused transfer is now genuinely wasted"
                ),
            )
        )
    return alerts


def describe(alerts: list[Alert]) -> list[str]:
    if not alerts:
        return ["No alerts."]
    return [f"[{alert.severity.label:>7}] {alert.category}: {alert.message}" for alert in alerts]


__all__ = ["Alert", "AlertSeverity", "collect_alerts", "describe"]
