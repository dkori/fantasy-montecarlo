"""League scoring configuration.

Scoring is data, not code: PPR / half-PPR / standard differ only in constants,
and eventually these can be pulled from a Yahoo league's settings. A StatLine is
one simulated outcome for a player; ScoringConfig.score() turns it into points.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatLine:
    """One player's (simulated) statistical outcome for a game."""

    receptions: float = 0.0
    receiving_yards: float = 0.0
    rushing_yards: float = 0.0
    touchdowns: float = 0.0  # rushing + receiving TDs combined (v1)


@dataclass(frozen=True)
class ScoringConfig:
    """Points awarded per unit of each stat.

    Defaults are full-PPR standard values. Use the factory helpers for the
    common presets.
    """

    points_per_reception: float = 1.0
    points_per_receiving_yard: float = 0.1  # 1 pt / 10 yds
    points_per_rushing_yard: float = 0.1
    points_per_touchdown: float = 6.0

    def score(self, line: StatLine) -> float:
        return (
            line.receptions * self.points_per_reception
            + line.receiving_yards * self.points_per_receiving_yard
            + line.rushing_yards * self.points_per_rushing_yard
            + line.touchdowns * self.points_per_touchdown
        )


def ppr() -> ScoringConfig:
    return ScoringConfig(points_per_reception=1.0)


def half_ppr() -> ScoringConfig:
    return ScoringConfig(points_per_reception=0.5)


def standard() -> ScoringConfig:
    return ScoringConfig(points_per_reception=0.0)


PRESETS = {"ppr": ppr, "half_ppr": half_ppr, "standard": standard}


def from_preset(name: str) -> ScoringConfig:
    key = name.lower().replace("-", "_")
    if key not in PRESETS:
        raise ValueError(
            f"Unknown scoring preset '{name}'. Options: {', '.join(PRESETS)}"
        )
    return PRESETS[key]()
