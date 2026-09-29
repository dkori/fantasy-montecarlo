import math

from ffmc.odds.devig import (
    american_to_implied_prob,
    decimal_to_implied_prob,
    devig_pair,
    devig_prob_from_pair,
)


def test_american_to_implied_prob_negative():
    assert math.isclose(american_to_implied_prob(-110), 110 / 210, rel_tol=1e-9)


def test_american_to_implied_prob_positive():
    assert math.isclose(american_to_implied_prob(+120), 100 / 220, rel_tol=1e-9)


def test_decimal_to_implied_prob():
    assert math.isclose(decimal_to_implied_prob(2.0), 0.5, rel_tol=1e-9)


def test_devig_sums_to_one():
    r = devig_pair(-110, -110)
    assert math.isclose(r.over + r.under, 1.0, rel_tol=1e-12)
    assert math.isclose(r.over, 0.5, rel_tol=1e-9)
    assert r.overround > 1.0  # there was vig to remove


def test_devig_preserves_ratio():
    # Heavy favorite over: de-vigged over should stay > 0.5.
    r = devig_pair(-260, +200)
    assert r.over > 0.5
    assert math.isclose(r.over + r.under, 1.0, rel_tol=1e-12)


def test_devig_prob_from_pair_matches():
    assert devig_prob_from_pair(-140, 110) == devig_pair(-140, 110).over
