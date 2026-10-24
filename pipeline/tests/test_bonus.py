"""M8's bonus: pin the shipped formula.

EXP-01 (D-34) graded a variant that integrated over each player's own BPS spread; it restored the
bonus total but worsened held-out MAE and was rejected, and its code was removed. The shipped
formula holds the player's BPS at its expectation, so an average player gets almost nothing; the
repayment is D-38.
"""

from __future__ import annotations

import pytest

from fpl_dof.forecast.models import BonusModel


def test_the_shipped_formula_is_the_point_estimate_against_21_others() -> None:
    model = BonusModel(typical_bps_mean=14.0, typical_bps_sd=9.0)
    assert model.expected_bonus(14.0) == pytest.approx((3 + 2 * 21 + 210) * 0.5**21, rel=1e-9)


def test_more_expected_bps_never_means_less_bonus() -> None:
    model = BonusModel(typical_bps_mean=14.0, typical_bps_sd=9.0)
    values = [model.expected_bonus(x) for x in (0.0, 10.0, 14.0, 20.0, 30.0, 45.0)]
    assert values == sorted(values)
