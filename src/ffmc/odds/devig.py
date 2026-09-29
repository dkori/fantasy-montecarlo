"""Odds conversion and de-vigging utilities.

A sportsbook's posted odds encode an *implied probability* for each outcome, but
those implied probabilities include the book's margin (the "vig" or overround),
so the two sides of an over/under do NOT sum to 1. Before we can treat the
numbers as a real probability distribution we have to remove that margin.

This module provides:
  - american_to_implied_prob: American odds -> raw implied probability
  - devig_pair:              remove vig from a single over/under pair
  - DevigMethod:             pluggable strategy (multiplicative now, room for Shin)

Everything here is pure and unit-testable; no network, no numpy required.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def american_to_implied_prob(odds: float) -> float:
    """Convert American odds to a raw (vig-inclusive) implied probability.

    Positive odds (underdog):  P = 100 / (odds + 100)
    Negative odds (favorite):  P = -odds / (-odds + 100)

    >>> round(american_to_implied_prob(-110), 4)
    0.5238
    >>> round(american_to_implied_prob(+120), 4)
    0.4545
    """
    if odds == 0:
        raise ValueError("American odds of 0 are not valid")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to a raw implied probability (1 / decimal)."""
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    return 1.0 / decimal_odds


class DevigMethod(str, Enum):
    """Strategy for removing the bookmaker margin from a set of outcomes."""

    MULTIPLICATIVE = "multiplicative"
    # Future: SHIN = "shin", POWER = "power"


@dataclass(frozen=True)
class DevigResult:
    """De-vigged probabilities for the two sides of a threshold.

    ``over`` is P(X > line) and ``under`` is P(X <= line); they sum to 1.
    ``overround`` is the pre-devig sum (a diagnostic; e.g. 1.045 = 4.5% vig).
    """

    over: float
    under: float
    overround: float


def devig_pair(
    over_odds: float,
    under_odds: float,
    method: DevigMethod = DevigMethod.MULTIPLICATIVE,
) -> DevigResult:
    """Remove vig from a single over/under pair given as American odds.

    The two raw implied probabilities sum to ``overround`` (> 1). Multiplicative
    de-vigging simply rescales each so they sum to 1, preserving their ratio.

    >>> r = devig_pair(-110, -110)
    >>> round(r.over, 3), round(r.under, 3)
    (0.5, 0.5)
    >>> round(r.overround, 3)
    1.048
    """
    p_over_raw = american_to_implied_prob(over_odds)
    p_under_raw = american_to_implied_prob(under_odds)
    overround = p_over_raw + p_under_raw

    if method is DevigMethod.MULTIPLICATIVE:
        p_over = p_over_raw / overround
        p_under = p_under_raw / overround
    else:  # pragma: no cover - reserved for future methods
        raise NotImplementedError(f"De-vig method {method} not implemented yet")

    return DevigResult(over=p_over, under=p_under, overround=overround)


def devig_prob_from_pair(
    over_odds: float,
    under_odds: float,
    method: DevigMethod = DevigMethod.MULTIPLICATIVE,
) -> float:
    """Convenience: return just the de-vigged P(X > line) for an over/under pair."""
    return devig_pair(over_odds, under_odds, method).over
