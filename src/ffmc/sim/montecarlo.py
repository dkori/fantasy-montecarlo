"""Per-player Monte Carlo simulation and aggregation.

Given a player's per-stat distributions (each reconstructed from de-vigged prop
odds) and a scoring config, draw N independent samples per stat, score each
simulated stat line, and summarize the resulting fantasy-point distribution.

v1 samples each stat INDEPENDENTLY. This is the biggest known limitation: real
stats are positively correlated, so independence compresses the tails of the
total. The PlayerModel keeps each marginal separate so a copula can later couple
the uniforms feeding each sampler without changing the marginals themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np

from ffmc.scoring.config import ScoringConfig, StatLine


class StatDistribution(Protocol):
    """Anything that can produce N samples of a stat."""

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray: ...


@dataclass
class PlayerModel:
    """A player's four stat distributions (any may be None if not offered)."""

    name: str
    receptions: Optional[StatDistribution] = None
    receiving_yards: Optional[StatDistribution] = None
    rushing_yards: Optional[StatDistribution] = None
    touchdowns: Optional[StatDistribution] = None


@dataclass
class ScoreDistribution:
    """Summary of a simulated fantasy-point distribution."""

    name: str
    samples: np.ndarray

    @property
    def mean(self) -> float:
        return float(np.mean(self.samples))

    @property
    def median(self) -> float:
        return float(np.median(self.samples))

    @property
    def std(self) -> float:
        return float(np.std(self.samples))

    def quantile(self, q: float) -> float:
        return float(np.quantile(self.samples, q))

    @property
    def floor(self) -> float:
        """10th-percentile outcome."""
        return self.quantile(0.10)

    @property
    def ceiling(self) -> float:
        """90th-percentile outcome."""
        return self.quantile(0.90)

    def prob_over(self, threshold: float) -> float:
        """P(fantasy points > threshold)."""
        return float(np.mean(self.samples > threshold))

    def summary(self) -> dict:
        return {
            "name": self.name,
            "mean": round(self.mean, 2),
            "median": round(self.median, 2),
            "std": round(self.std, 2),
            "floor_p10": round(self.floor, 2),
            "ceiling_p90": round(self.ceiling, 2),
        }


def simulate_player(
    model: PlayerModel,
    scoring: ScoringConfig,
    n_sims: int = 50_000,
    seed: Optional[int] = None,
    correlated: bool = False,
) -> ScoreDistribution:
    """Run the Monte Carlo for one player and return the score distribution.

    correlated=False (default): every stat is sampled independently. Nothing
        about the marginals changes; this is the original, fully odds-derived
        model. Its known limitation is compressed tails (see README).

    correlated=True: couple the stats with a Gaussian copula whose parameters
        come from measured nflverse rank correlations (see ffmc.sim.correlations
        and analysis/nflverse_correlation_check.py). Each stat's MARGINAL is
        unchanged (we only change how the per-stat uniforms co-move), so
        odds-implied probabilities are preserved; only the joint / total-score
        tails widen. Correlations are predicted per player from odds-derived
        usage (position-agnostic; see ffmc.sim.correlations).
    """
    rng = np.random.default_rng(seed)
    if correlated:
        return _simulate_correlated(model, scoring, n_sims, rng)
    return _simulate_independent(model, scoring, n_sims, rng)


def _simulate_independent(
    model: PlayerModel, scoring: ScoringConfig, n_sims: int, rng: np.random.Generator
) -> ScoreDistribution:
    zeros = np.zeros(n_sims)
    rec = model.receptions.sample(n_sims, rng) if model.receptions else zeros
    rec_yds = (
        model.receiving_yards.sample(n_sims, rng) if model.receiving_yards else zeros
    )
    rush_yds = (
        model.rushing_yards.sample(n_sims, rng) if model.rushing_yards else zeros
    )
    tds = model.touchdowns.sample(n_sims, rng) if model.touchdowns else zeros
    return ScoreDistribution(
        name=model.name,
        samples=_score(scoring, rec, rec_yds, rush_yds, tds),
    )


def _simulate_correlated(
    model: PlayerModel, scoring: ScoringConfig, n_sims: int, rng: np.random.Generator
) -> ScoreDistribution:
    # Imported here to keep the independent path dependency-free.
    from scipy.stats import norm

    from ffmc.sim.correlations import STATS

    dists = {
        "receptions": model.receptions,
        "receiving_yards": model.receiving_yards,
        "rushing_yards": model.rushing_yards,
        "touchdowns": model.touchdowns,
    }
    present = [i for i, s in enumerate(STATS) if dists[s] is not None]

    zeros = np.zeros(n_sims)
    values = {s: zeros for s in STATS}

    if present:
        spec = _resolve_spec(model, dists)
        full_cov = spec.gaussian_matrix()
        # Sub-matrix over only the stats this player actually has lines for.
        sub = full_cov[np.ix_(present, present)]
        z = rng.multivariate_normal(np.zeros(len(present)), sub, size=n_sims)
        u = norm.cdf(z)  # correlated uniforms, one column per present stat
        for col, stat_idx in enumerate(present):
            stat = STATS[stat_idx]
            values[stat] = dists[stat].invert(u[:, col])

    return ScoreDistribution(
        name=model.name,
        samples=_score(
            scoring,
            values["receptions"],
            values["receiving_yards"],
            values["rushing_yards"],
            values["touchdowns"],
        ),
    )


def _resolve_spec(model: "PlayerModel", dists: dict):
    """Choose the correlation spec for a player.

    Position-agnostic: predict per-player correlations from odds-derived usage
    features (rush_share, YPC, TD-rate) computed from the marginals'
    expectations. No position label or role bucketing is used.
    """
    from ffmc.sim.correlations import CorrelationSpec, PlayerFeatures

    def _exp(d):
        return d.expected_value() if d is not None else None

    # One position-agnostic path: build usage features from the marginals and
    # map them to correlations. A player with no rushing line simply has
    # rush_share = 0, so rushing couplings vanish -- no branching needed.
    features = PlayerFeatures.from_expectations(
        exp_receptions=_exp(dists["receptions"]),
        exp_receiving_yards=_exp(dists["receiving_yards"]),
        exp_rushing_yards=_exp(dists["rushing_yards"]),
        exp_touchdowns=_exp(dists["touchdowns"]),
    )
    return CorrelationSpec.from_features(features)


def _score(scoring, rec, rec_yds, rush_yds, tds):
    return (
        rec * scoring.points_per_reception
        + rec_yds * scoring.points_per_receiving_yard
        + rush_yds * scoring.points_per_rushing_yard
        + tds * scoring.points_per_touchdown
    )


# Kept for readability / testing parity with the vectorized path above.
def score_line(line: StatLine, scoring: ScoringConfig) -> float:
    return scoring.score(line)
