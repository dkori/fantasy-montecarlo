# DECISIONS

Settled modeling decisions and the assumptions behind them. Read this to avoid
re-litigating questions that were already reasoned through, or silently breaking
an intentional choice. Each entry: the decision, why, and the known limitation.

## De-vigging is mandatory, and multiplicative for now
Raw implied probabilities include the book's margin and don't sum to 1. We
**must** de-vig before treating them as a distribution, or every projection is
biased. We use **multiplicative** (proportional) de-vig — simplest, ignores
favorite-longshot bias. `DevigMethod` enum leaves room for Shin's/power methods.
*Limitation:* multiplicative de-vig is slightly biased vs. Shin's; acceptable v1.

## Yards continuous, receptions/TDs discrete
Yards are treated as continuous (`ContinuousLadderDistribution`); receptions and
TDs as integer counts. Sampling discrete stats as counts (not rounded
continuous draws) avoids bias.

## Receptions → negative-binomial fit (not CDF interpolation)
An earlier version interpolated the CDF linearly between posted integers (⇒
uniform PMF between them) and clamped residual tail mass at k_max — both were
arbitrary and the second contradicted its own docstring. Replaced with a
**negative-binomial fit** to the posted CDF anchors: one coherent overdispersed
count model giving a principled between-integer shape and a proper decaying tail.
*Limitation:* NB is a 2-param family fit to ≥3 anchors, so it's a least-squares
fit, not exact interpolation — small residuals if a book's anchors aren't
NB-shaped (by design; more honest than forcing an exact match).

## TDs from anytime-TD via Poisson
Books post only P(≥1 TD), not a TD ladder. We back out `lambda = -ln(1-p)` and
sample Poisson(lambda). *Limitation:* an assumption about TD-count shape; and
rush + receive TDs are necessarily **pooled** into one count (the market prices
one number).

## Tail extrapolation is a real assumption
Books post lines over a limited range; outcomes beyond require extrapolating the
CDF tail. Yards use an exponential survival tail (rate from the last posted
segment). *Limitation:* genuinely unobserved; matters for ceiling games. Not
validated against realized outcomes.

## Scoring is injected config, not hardcoded
PPR / half-PPR / standard differ only in constants. `ScoringConfig` is passed
in, so the same sim serves any league (and can later pull Yahoo league settings).

## Independence is the DEFAULT; correlation is opt-in
`simulate_player(correlated=False)` by default — the only model with zero
fabricated joint structure. `--correlated` opts into the Gaussian copula. This
is deliberate: nothing changes silently, and independence's bias (thin tails) is
documented rather than "fixed" with numbers the odds don't contain. See
[CORRELATIONS.md](CORRELATIONS.md) for the whole story.

## Correlation model is position-agnostic (hard requirement)
No position labels or role buckets anywhere at runtime. Correlations are
continuous functions of odds-derived usage (`rush_share`, YPC). This was an
explicit user requirement and an earlier position-gated version was removed.
**Do not reintroduce position/role branching.** Details in
[CORRELATIONS.md](CORRELATIONS.md).

## Marginals are sacred
Whatever we do for correlation, each stat's own odds-implied distribution must
stay exactly unchanged. The copula only alters co-movement (it drives the
existing inverse-CDFs with correlated uniforms). Any change that shifts a
marginal is a bug.

## Monte Carlo (not analytic convolution) — because of the copula
For the *independent* case, the total-score distribution could be computed
exactly by FFT-convolving the per-stat PDFs (faster, noise-free). We considered
this. We kept Monte Carlo because the **correlated** case has no simple
closed form (sum of copula-coupled non-Gaussian variables), and we didn't want
two engines. If independent-mode speed/exactness ever matters, an analytic path
could be added just for that case (and would double as a test oracle).

## Single bookmaker
We read one book's lines (`--book`), not a consensus across books. *Limitation:*
a consensus/fair-line blend would be more robust. Not done.

## Market efficiency assumption
The whole approach assumes the book's lines are a good estimate of true
probabilities. Defensible prior, but projections inherit any market bias.

## The Odds API specifics are UNVERIFIED
Market keys, response shape, and free-tier limits in `odds/` are educated
guesses, not confirmed against the live endpoint. This is the top open risk —
see [../PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md). First live `fetch` will
likely need parser adjustments in `markets.py`.
