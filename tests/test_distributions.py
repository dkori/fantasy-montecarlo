import numpy as np

from ffmc.distributions.ladder import (
    ContinuousLadderDistribution,
    DiscreteLadderDistribution,
    LadderPoint,
)
from ffmc.distributions.poisson import (
    PoissonTouchdownDistribution,
    lambda_from_anytime_td,
)


def test_continuous_cdf_monotonic():
    pts = [
        LadderPoint(40.0, 0.80),
        LadderPoint(60.0, 0.55),
        LadderPoint(80.0, 0.30),
        LadderPoint(100.0, 0.12),
    ]
    d = ContinuousLadderDistribution(pts)
    xs = np.linspace(0, 200, 500)
    cdf = np.array([d.cdf(x) for x in xs])
    assert np.all(np.diff(cdf) >= -1e-9)  # non-decreasing
    assert cdf[0] >= 0.0 and cdf[-1] <= 1.0 + 1e-9


def test_continuous_sampler_recovers_prob_over():
    # P(X > 60) should be ~0.55 given the ladder point at 60.
    pts = [
        LadderPoint(40.0, 0.80),
        LadderPoint(60.0, 0.55),
        LadderPoint(80.0, 0.30),
        LadderPoint(100.0, 0.12),
    ]
    d = ContinuousLadderDistribution(pts)
    rng = np.random.default_rng(0)
    s = d.sample(200_000, rng)
    assert abs(np.mean(s > 60.0) - 0.55) < 0.02
    assert abs(np.mean(s > 80.0) - 0.30) < 0.02
    assert np.all(s >= 0.0)  # yards floor


def test_discrete_pmf_normalized_and_recovers_prob():
    # P(X > 4.5) = P(X >= 5) should be ~0.45.
    pts = [
        LadderPoint(2.5, 0.72),
        LadderPoint(4.5, 0.45),
        LadderPoint(6.5, 0.18),
    ]
    d = DiscreteLadderDistribution(pts)
    assert abs(d.pmf().sum() - 1.0) < 1e-9
    rng = np.random.default_rng(1)
    s = d.sample(200_000, rng)
    assert abs(np.mean(s >= 5) - 0.45) < 0.03
    assert np.all(s == np.floor(s))  # integer counts


def test_poisson_td_rate():
    # P(>=1) = 0.5  =>  lambda = ln 2
    assert abs(lambda_from_anytime_td(0.5) - np.log(2)) < 1e-9
    d = PoissonTouchdownDistribution(0.5)
    rng = np.random.default_rng(2)
    s = d.sample(200_000, rng)
    assert abs(np.mean(s >= 1) - 0.5) < 0.01


def test_discrete_nbinom_fits_all_anchors():
    """NB fit reproduces every posted anchor simultaneously (not just one)."""
    pts = [
        LadderPoint(2.5, 0.72),
        LadderPoint(4.5, 0.45),
        LadderPoint(6.5, 0.18),
    ]
    d = DiscreteLadderDistribution(pts)
    cdf = np.cumsum(d.pmf())
    for lp in pts:
        k = int(np.floor(lp.threshold))
        model_over = 1.0 - cdf[k]
        assert abs(model_over - lp.prob_over) < 0.04
    # Overdispersed relative to Poisson (variance/mean > 1).
    assert 1.0 + d.alpha * d.mu > 1.0


def test_discrete_upper_tail_decays_not_clamped():
    """Beyond the top posted line the PMF should decay, with no mass spike at k_max."""
    pts = [LadderPoint(2.5, 0.72), LadderPoint(4.5, 0.45), LadderPoint(6.5, 0.18)]
    d = DiscreteLadderDistribution(pts)
    pmf = d.pmf()
    # Tail past the highest posted integer (6) must be monotonically small,
    # and the final cell must not be an anomalous spike (the old clamp bug).
    top = 7
    assert np.all(np.diff(pmf[top:]) <= 1e-6)  # non-increasing tail
    assert pmf[-1] < pmf[top]                   # last cell is tiny, not a dump


def test_discrete_single_line_fallback():
    """A single posted line is underdetermined; fit still matches that point."""
    d = DiscreteLadderDistribution([LadderPoint(4.5, 0.45)])
    cdf = np.cumsum(d.pmf())
    assert abs((1.0 - cdf[4]) - 0.45) < 0.04
    assert abs(d.pmf().sum() - 1.0) < 1e-9
