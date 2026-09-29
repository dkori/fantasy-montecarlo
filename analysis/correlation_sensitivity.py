"""Correlation sensitivity screen (exploratory — NOT part of the shipped model).

Purpose: quantify how much a player's TOTAL fantasy-score distribution responds
to an assumed correlation between receptions and receiving yards. This does NOT
estimate the true correlation (impossible from odds alone); it only traces the
response curve as we turn the rho knob.

Interpretation (asymmetric screen):
  - If p10/p50/p90 barely move across rho in [0, 0.9], correlation is negligible
    for ANY true value -> independence is fine, no data needed.
  - If they move materially, the screen is inconclusive about the "right" answer;
    it just means the true rho (which must come from real game logs) matters.

Method: keep the REAL odds-derived marginals (from the sample fixture). Couple
receptions and receiving yards with a Gaussian copula: draw correlated standard
normals, map to uniforms via Phi, then push each uniform through that stat's own
inverse-CDF. This leaves each marginal exactly unchanged; only co-movement
changes. Rushing yards and TDs are left independent (this WR has no rush lines).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import norm

from ffmc.odds.markets import build_player_models
from ffmc.scoring.config import ppr


def continuous_invert(dist, u: np.ndarray) -> np.ndarray:
    """Inverse-CDF of a ContinuousLadderDistribution from supplied uniforms."""
    return dist._invert(u)  # noqa: SLF001 (exploratory script)


def discrete_invert(dist, u: np.ndarray) -> np.ndarray:
    """Inverse-CDF of a DiscreteLadderDistribution from supplied uniforms."""
    cdf = np.cumsum(dist.pmf())
    # searchsorted on the CDF maps u -> smallest support index with CDF >= u
    idx = np.searchsorted(cdf, u, side="left")
    idx = np.clip(idx, 0, len(dist._support) - 1)  # noqa: SLF001
    return dist._support[idx].astype(float)  # noqa: SLF001


def simulate_with_rho(model, scoring, rho: float, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)

    # Correlated standard normals for (receptions, receiving_yards).
    cov = np.array([[1.0, rho], [rho, 1.0]])
    z = rng.multivariate_normal(mean=[0.0, 0.0], cov=cov, size=n)
    u = norm.cdf(z)  # correlated uniforms, columns: [rec, rec_yds]

    rec = discrete_invert(model.receptions, u[:, 0])
    rec_yds = continuous_invert(model.receiving_yards, u[:, 1])

    # Independent draws for the remaining stats.
    tds = (
        model.touchdowns.sample(n, rng)
        if model.touchdowns
        else np.zeros(n)
    )
    rush = (
        model.rushing_yards.sample(n, rng)
        if model.rushing_yards
        else np.zeros(n)
    )

    return (
        rec * scoring.points_per_reception
        + rec_yds * scoring.points_per_receiving_yard
        + rush * scoring.points_per_rushing_yard
        + tds * scoring.points_per_touchdown
    )


def main() -> None:
    payload = json.loads(
        (Path(__file__).parent.parent / "data/samples/sample_event.json").read_text()
    )
    model = build_player_models(payload, book_key="draftkings")["Sample WR"]
    scoring = ppr()
    n, seed = 400_000, 12345

    print("Correlation sensitivity: receptions <-> receiving yards (PPR)")
    print("Real odds-derived marginals; rho is a swept INPUT, not an estimate.\n")
    print(f"{'rho':>5} {'mean':>7} {'p10':>7} {'p50':>7} {'p90':>7} "
          f"{'sd':>6} {'p90-p10':>8} {'corr(check)':>12}")

    base = None
    for rho in [0.0, 0.3, 0.5, 0.7, 0.9]:
        pts = simulate_with_rho(model, scoring, rho, n, seed)
        p10, p50, p90 = np.percentile(pts, [10, 50, 90])
        # empirical realized correlation of the two coupled stats (sanity check)
        rng = np.random.default_rng(seed)
        z = rng.multivariate_normal([0, 0], [[1, rho], [rho, 1]], size=n)
        uu = norm.cdf(z)
        rc = discrete_invert(model.receptions, uu[:, 0])
        ry = continuous_invert(model.receiving_yards, uu[:, 1])
        realized = np.corrcoef(rc, ry)[0, 1]
        row = (f"{rho:>5.1f} {pts.mean():>7.2f} {p10:>7.2f} {p50:>7.2f} "
               f"{p90:>7.2f} {pts.std():>6.2f} {p90 - p10:>8.2f} {realized:>12.3f}")
        print(row)
        if rho == 0.0:
            base = (p10, p50, p90, p90 - p10)

    p10b, p50b, p90b, spreadb = base
    print("\nShift vs. independence (rho=0):")
    for rho in [0.5, 0.9]:
        pts = simulate_with_rho(model, scoring, rho, n, seed)
        p10, p50, p90 = np.percentile(pts, [10, 50, 90])
        print(f"  rho={rho}:  p10 {p10 - p10b:+.2f}   p50 {p50 - p50b:+.2f}   "
              f"p90 {p90 - p90b:+.2f}   spread(p90-p10) {(p90 - p10) - spreadb:+.2f}")


if __name__ == "__main__":
    main()
