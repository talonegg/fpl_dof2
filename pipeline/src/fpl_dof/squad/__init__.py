"""The owner's squad: what it is now, and how it should be set up this week.

Pure core (DP-03). Nothing here fetches anything; it reads the conformed silver model and the
declared configuration, and returns dataclasses. That is what makes the awkward reconstruction
arithmetic testable without a network.
"""

from fpl_dof.squad.selection import Selection, select_team
from fpl_dof.squad.state import (
    HeldPlayer,
    Provenance,
    SquadState,
    SquadStateError,
    free_transfers_after,
    load_squad_state,
)

__all__ = [
    "HeldPlayer",
    "Provenance",
    "Selection",
    "SquadState",
    "SquadStateError",
    "free_transfers_after",
    "load_squad_state",
    "select_team",
]
