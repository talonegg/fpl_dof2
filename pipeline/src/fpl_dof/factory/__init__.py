"""The model factory's interface: the strategy registry (MOD-03, DL-86).

The orchestrator reaches forecasters and their records only through this package; the boundary is
an import-linter contract in ``pyproject.toml``. The model-free trailing form (DL-70) is the
harness's own benchmark, so it is reached through here too.
"""

from fpl_dof.forecast.form import form_by_player_id, trailing_form

__all__ = ["form_by_player_id", "trailing_form"]
