"""Gold conformed datasets (PIPE-02, PIPE-05).

Decision-ready multi-season datasets:
- ``player_career_history``: Multi-season player history keyed on permanent player_code (PIPE-02).
- ``team_match_odds``: Canonical match odds and de-vigged expectations across all seasons (PIPE-05).
"""

from __future__ import annotations

from fpl_dof.gold.match_odds import build_team_match_odds, read_team_match_odds
from fpl_dof.gold.player_career import (
    build_player_career_history,
    read_player_career_history,
)

__all__ = [
    "build_player_career_history",
    "build_team_match_odds",
    "read_player_career_history",
    "read_team_match_odds",
]
