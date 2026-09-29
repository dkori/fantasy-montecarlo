"""Reconstruct a sampleable distribution from a ladder of prop lines.

A sportsbook posts, for a given stat, one or more over/under lines. After
de-vigging, each line ``t`` gives us a point on the *survival function*:

    S(t) = P(X > t)          equivalently   F(t) = P(X <= t) = 1 - S(t)

With several alternate lines we get several points on F. To draw random values
we need a full CDF, so we:

  1. sort the (threshold, F) points,
  2. enforce monotonicity (F must be non-decreasing),
  3. interpolate between known points (monotone PCHIP),
  4. extrapolate the tails beyond the posted range (parametric),
  5. inverse-transform sample: draw u ~ U(0,1), return F^{-1}(u).

Two flavors:
  - ContinuousLadderDistribution: for yards. Monotone PCHIP on the CDF interior,
    exponential survival tails beyond the posted range.
  - DiscreteLadderDistribution:   for receptions. Fits a negative-binomial to the
    posted CDF anchors, giving a coherent PMF between integers and a proper
    decaying upper tail (no uniform fill, no clamped residual mass).

Touchdowns are handled separately (see poisson.py) because books post only an
anytime-TD probability, not a ladder.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import minimize
from scipy.stats import nbinom


@dataclass
class LadderPoint:
    """One posted line: threshold value and de-vigged P(X > threshold)."""

    threshold: float
    prob_over: float  # P(X > threshold), de-vigged, in (0, 1)


def _to_sorted_cdf_points(points: list[LadderPoint]) -> tuple[np.ndarray, np.ndarray]:
    """Return (thresholds, F) arrays sorted by threshold, F = 1 - P(over).

    Enforces that F is strictly non-decreasing (books' alternate lines can be
    mildly inconsistent after de-vigging; we clamp rather than fail).
    """
    if not points:
        raise ValueError("Need at least one ladder point to build a distribution")

    pts = sorted(points, key=lambda p: p.threshold)
    thresholds = np.array([p.threshold for p in pts], dtype=float)
    f = np.array([1.0 - p.prob_over for p in pts], dtype=float)

    if np.any(np.diff(thresholds) <= 0):
        raise ValueError("Ladder thresholds must be distinct")

    # Enforce monotone non-decreasing CDF (repair small inversions).
    f = np.maximum.accumulate(f)
    f = np.clip(f, 1e-9, 1.0 - 1e-9)
    return thresholds, f


@dataclass
class ContinuousLadderDistribution:
    """Continuous distribution reconstructed from a ladder (for yards).

    Interior: monotone PCHIP interpolation of the CDF.
    Tails: exponential decay of the survival/CDF beyond the posted range, with a
    rate inferred from the outermost posted segment. Values are clamped at 0
    (a player can't gain negative yards in this model).
    """

    points: list[LadderPoint]
    floor: float = 0.0  # hard lower bound on the stat (yards >= 0)
    _thresholds: np.ndarray = field(init=False, repr=False)
    _f: np.ndarray = field(init=False, repr=False)
    _cdf: PchipInterpolator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._thresholds, self._f = _to_sorted_cdf_points(self.points)
        if len(self._thresholds) == 1:
            # Single line: we can't interpolate a shape. Fall back to an
            # exponential distribution anchored to the one probability.
            self._cdf = None  # type: ignore[assignment]
        else:
            self._cdf = PchipInterpolator(
                self._thresholds, self._f, extrapolate=False
            )

    # --- tail models -----------------------------------------------------
    def _lower_tail_rate(self) -> float:
        """Rate for exponential lower tail below the smallest threshold."""
        t0, f0 = self._thresholds[0], self._f[0]
        span = max(t0 - self.floor, 1e-6)
        # F(floor) -> 0, F(t0) = f0  =>  treat as exponential rise.
        return -np.log(max(1.0 - f0, 1e-9)) / span if f0 < 1 else 1.0 / span

    def _upper_tail_rate(self) -> float:
        """Rate for exponential upper tail above the largest threshold."""
        tn, fn = self._thresholds[-1], self._f[-1]
        s_n = 1.0 - fn  # survival at last threshold
        # Estimate scale from the last interior segment's slope if possible.
        if len(self._thresholds) >= 2:
            t_prev, f_prev = self._thresholds[-2], self._f[-2]
            s_prev = 1.0 - f_prev
            if s_prev > s_n > 0:
                # survival decays exp(-rate * x); fit rate from two points.
                return (np.log(s_prev) - np.log(s_n)) / (tn - t_prev)
        return 1.0 / max(tn, 1.0)

    def cdf(self, x: float) -> float:
        x = max(x, self.floor)
        if self._cdf is None:
            # single-line exponential fallback
            t0, f0 = self._thresholds[0], self._f[0]
            rate = self._lower_tail_rate()
            return float(1.0 - (1.0 - f0) * np.exp(-rate * (x - self.floor)) /
                         np.exp(-rate * (t0 - self.floor)))
        t0, tn = self._thresholds[0], self._thresholds[-1]
        if x <= t0:
            rate = self._lower_tail_rate()
            return float(self._f[0] * (1.0 - np.exp(-rate * (x - self.floor))) /
                         (1.0 - np.exp(-rate * (t0 - self.floor)) + 1e-12))
        if x >= tn:
            rate = self._upper_tail_rate()
            s_n = 1.0 - self._f[-1]
            return float(1.0 - s_n * np.exp(-rate * (x - tn)))
        return float(self._cdf(x))

    def expected_value(self) -> float:
        """E[X] via the survival-function integral E[X] = integral_0^inf S(x) dx
        (valid because X >= floor >= 0), evaluated on a dense grid."""
        tn = self._thresholds[-1]
        hi = tn + 5.0 * (1.0 / max(self._upper_tail_rate(), 1e-6))
        grid = np.linspace(self.floor, hi, 4000)
        surv = 1.0 - np.array([self.cdf(x) for x in grid])
        trap = getattr(np, "trapezoid", None) or np.trapz  # NumPy 2.0 renamed it
        return float(self.floor + trap(surv, grid))

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """Inverse-transform sampling on a dense CDF grid."""
        u = rng.random(n)
        return self.invert(u)

    def invert(self, u: np.ndarray) -> np.ndarray:
        """Inverse CDF: map supplied uniforms in [0,1] to stat values.

        This is the entry point a copula uses to drive the marginal with its own
        (correlated) uniforms instead of fresh independent ones.
        """
        return self._invert(np.asarray(u, dtype=float))

    def _invert(self, u: np.ndarray) -> np.ndarray:
        # Build a dense grid spanning well past the posted range and invert.
        t0, tn = self._thresholds[0], self._thresholds[-1]
        lo = self.floor
        hi = tn + 5.0 * (1.0 / max(self._upper_tail_rate(), 1e-6))
        grid = np.linspace(lo, hi, 2000)
        cdf_vals = np.array([self.cdf(x) for x in grid])
        # Ensure monotone for interp.
        cdf_vals = np.maximum.accumulate(cdf_vals)
        cdf_vals[0], cdf_vals[-1] = 0.0, 1.0
        return np.interp(u, cdf_vals, grid)


@dataclass
class DiscreteLadderDistribution:
    """Discrete count distribution reconstructed from a ladder (for receptions).

    Lines are posted at half-integers (e.g. 2.5, 4.5), so P(X > 2.5) = P(X >= 3)
    and each line pins a CDF anchor at the integer below it:
    P(X <= floor(line)). We fit a **negative-binomial** distribution to those
    anchors and use it as the PMF over integer counts 0..k_max.

    Why negative-binomial rather than interpolating the CDF:
      - It is a single coherent probability model, so it gives a principled
        shape *between* the posted integers (no arbitrary "uniform fill") and a
        proper, decaying *upper tail* beyond the highest posted line (not
        residual mass clamped at k_max).
      - Reception counts are overdispersed (variance > mean); NB is the standard
        overdispersed generalization of Poisson and reduces toward Poisson as
        dispersion vanishes.

    Fitting: we choose NB parameters (mean mu >= 0, dispersion alpha > 0) to
    minimize squared error between the NB CDF and the de-vigged anchor points.
    With only one anchor the problem is underdetermined, so we fall back to a
    Poisson-like fit (alpha -> small) that matches that single point.

    Parameterization (mean/dispersion):
        mean = mu,   variance = mu + alpha * mu**2
        In scipy's nbinom(n, p):  n = 1/alpha,  p = n / (n + mu).
    """

    points: list[LadderPoint]
    k_max: int = 30
    _pmf: np.ndarray = field(init=False, repr=False)
    _support: np.ndarray = field(init=False, repr=False)
    _mu: float = field(init=False, repr=False)
    _alpha: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        thresholds, f = _to_sorted_cdf_points(self.points)
        # A half-line at t pins P(X <= floor(t)) = F. Build (k, target_cdf) pairs.
        anchor_k = np.floor(thresholds).astype(int)
        target_cdf = f

        self._mu, self._alpha = self._fit_nbinom(anchor_k, target_cdf)

        support = np.arange(0, self.k_max + 1)
        n, p = self._nbinom_params(self._mu, self._alpha)
        pmf = nbinom.pmf(support, n, p)
        # Fold the (tiny) tail beyond k_max into the last cell so it sums to 1.
        tail = max(0.0, 1.0 - pmf.sum())
        pmf[-1] += tail
        pmf = np.clip(pmf, 0.0, None)
        pmf /= pmf.sum()
        self._support = support
        self._pmf = pmf

    @staticmethod
    def _nbinom_params(mu: float, alpha: float) -> tuple[float, float]:
        """Convert (mean, dispersion) to scipy nbinom (n, p)."""
        mu = max(mu, 1e-6)
        alpha = max(alpha, 1e-6)
        n = 1.0 / alpha
        p = n / (n + mu)
        return n, p

    def _fit_nbinom(
        self, anchor_k: np.ndarray, target_cdf: np.ndarray
    ) -> tuple[float, float]:
        """Least-squares fit of (mu, alpha) to the anchor CDF points."""

        def objective(theta: np.ndarray) -> float:
            mu, alpha = theta
            if mu <= 0 or alpha <= 0:
                return 1e9
            n, p = self._nbinom_params(mu, alpha)
            model_cdf = nbinom.cdf(anchor_k, n, p)
            return float(np.sum((model_cdf - target_cdf) ** 2))

        # Initial guess: mu from the median anchor, mild overdispersion.
        # If an anchor is near 0.5, its k is close to the median ~ mean.
        idx = int(np.argmin(np.abs(target_cdf - 0.5)))
        mu0 = max(float(anchor_k[idx]) + 0.5, 0.5)
        x0 = np.array([mu0, 0.3])

        if len(anchor_k) == 1:
            # Underdetermined: pin alpha small (near-Poisson) and solve mu so the
            # single anchor CDF matches. A 1-D search on mu is robust.
            k0, c0 = float(anchor_k[0]), float(target_cdf[0])
            alpha = 1e-3

            def obj_mu(mu_arr: np.ndarray) -> float:
                mu = mu_arr[0]
                if mu <= 0:
                    return 1e9
                n, p = self._nbinom_params(mu, alpha)
                return float((nbinom.cdf(k0, n, p) - c0) ** 2)

            res = minimize(obj_mu, x0=np.array([mu0]), method="Nelder-Mead")
            return float(max(res.x[0], 1e-6)), alpha

        res = minimize(objective, x0=x0, method="Nelder-Mead")
        mu, alpha = res.x
        return float(max(mu, 1e-6)), float(max(alpha, 1e-6))

    @property
    def mu(self) -> float:
        return self._mu

    @property
    def alpha(self) -> float:
        return self._alpha

    def pmf(self) -> np.ndarray:
        return self._pmf

    def expected_value(self) -> float:
        return float(np.dot(self._support, self._pmf))

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        return self.invert(rng.random(n))

    def invert(self, u: np.ndarray) -> np.ndarray:
        """Inverse CDF for the fitted discrete distribution.

        Maps uniforms to integer counts via the PMF's cumulative distribution
        (smallest k with CDF(k) >= u). Lets a copula drive receptions with its
        correlated uniforms while preserving this exact marginal.
        """
        u = np.asarray(u, dtype=float)
        cdf = np.cumsum(self._pmf)
        cdf[-1] = 1.0  # guard against fp drift so u ~ 1.0 maps in-range
        idx = np.searchsorted(cdf, u, side="left")
        idx = np.clip(idx, 0, len(self._support) - 1)
        return self._support[idx].astype(float)
