"""The model factory's interface: the strategy registry (MOD-03, DL-86).

The orchestrator reaches forecasters and their records only through this package; the boundary is
an import-linter contract in ``pyproject.toml``. The model-free trailing form (DL-70) is the
harness's own benchmark, so it is reached through here too.
"""

from fpl_dof.forecast.diagnostics import PriceDependence, regress_xp_on_price
from fpl_dof.forecast.form import form_by_player_id, trailing_form
from fpl_dof.forecast.inputs import ForecastInputs
from fpl_dof.forecast.model_card import write_model_card
from fpl_dof.forecast.models import TeamStrengthModel
from fpl_dof.forecast.xp_v1 import team_matches

__all__ = [
    "ForecastInputs",
    "PriceDependence",
    "TeamStrengthModel",
    "form_by_player_id",
    "regress_xp_on_price",
    "team_matches",
    "trailing_form",
    "write_model_card",
]
