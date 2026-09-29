# ARCHITECTURE

Module-by-module reference for `src/ffmc/`. Read
[../PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) first for the big picture. For the
correlation model specifically, see [CORRELATIONS.md](CORRELATIONS.md).

Data flows: **odds → distributions → sim → score**, with `scoring` and `cli`
supporting. Design principles: each stat's marginal distribution is independent
of the odds source; scoring is injected config; the odds source is swappable;
correlation is layered on top of the marginals without altering them.

---

## `odds/` — odds ingestion and de-vigging

### `odds/devig.py`
Pure, dependency-light functions (no numpy needed).
- `american_to_implied_prob(odds)` — American odds → raw (vig-inclusive)
  implied probability. Also `decimal_to_implied_prob`.
- `devig_pair(over_odds, under_odds, method)` → `DevigResult(over, under, overround)`.
  The two raw implied probs sum to `overround` (> 1, that's the vig).
  **Multiplicative** de-vig rescales each so they sum to 1, preserving ratio.
  `DevigMethod` is an enum with room for Shin's/power methods later
  (`MULTIPLICATIVE` is the only one implemented).
- `devig_prob_from_pair(...)` — convenience returning just the de-vigged P(over).

### `odds/markets.py`
Turns a raw Odds API event payload into `PlayerModel`s.
- Market-key constants: `MARKET_RECEPTIONS`, `MARKET_RECEIVING_YDS`,
  `MARKET_RUSHING_YDS` (each includes the `_alternate` variant),
  `MARKET_ANYTIME_TD`; `ALL_MARKETS` is their union. **These keys are unverified
  against the live API** — centralized here so a rename is one line.
- `build_player_models(payload, book_key)` → `{player_name: PlayerModel}`. For
  each stat it collects the over/under pairs per threshold, de-vigs each to get
  P(X > threshold), builds a ladder, and constructs the right distribution:
  receptions → `DiscreteLadderDistribution`, yards → `ContinuousLadderDistribution`,
  TDs → `PoissonTouchdownDistribution` (from the anytime-TD Yes/No pair).
- Anytime-TD is a single P(≥1 TD), not a ladder — handled separately.

### `odds/client.py`
`OddsClient` — The Odds API v4 wrapper with on-disk caching.
- Caches every response to `data/cache/<hash>.json`; a live HTTP call happens
  only on a cache miss (or `force_refresh`). Protects the free-tier quota and
  lets all dev run offline.
- `list_events(sport)` — upcoming games (cheap, no props).
- `event_player_props(event_id, markets, ...)` — player props live on the
  **event-odds endpoint**, not the bulk odds endpoint. Optional `bookmakers`
  filter. Reads `ODDS_API_KEY` from env.
- **Untested against the live API.**

---

## `distributions/` — ladder → sampleable distribution

Each posted line, after de-vig, gives a point on the survival function
`S(t) = P(X > t)`, i.e. a CDF point `F(t) = 1 - S(t)`. With several alternate
lines we get several CDF points and reconstruct a full, sampleable distribution.
All classes expose `sample(n, rng)`, `invert(u)` (inverse-CDF from supplied
uniforms — this is what lets the copula drive them), and `expected_value()`.

### `distributions/ladder.py`
- `LadderPoint(threshold, prob_over)` — one de-vigged posted line.
- `ContinuousLadderDistribution` (yards): interior CDF via **monotone PCHIP**
  interpolation (shape-preserving, keeps density ≥ 0); **exponential survival
  tails** beyond the posted range (upper-tail rate fit from the last segment's
  slope); values floored at 0. `expected_value()` integrates the survival
  function. Inverse-transform sampling on a dense CDF grid.
- `DiscreteLadderDistribution` (receptions): fits a **negative-binomial** to the
  posted CDF anchors (a half-line at 4.5 pins P(X ≤ 4)). NB is chosen because it
  is a single coherent overdispersed count model — giving a principled PMF
  *between* integers (no arbitrary uniform fill) and a proper decaying upper
  tail (no residual mass clamped at k_max). Fit is least-squares on (mu, alpha);
  degrades to near-Poisson with a single anchor.

### `distributions/poisson.py`
- `PoissonTouchdownDistribution(prob_anytime_td)` — TDs from the anytime-TD
  market. Since books post only P(≥1 TD), we back out `lambda = -ln(1 - p)` and
  sample TD counts from Poisson(lambda). `lambda_from_anytime_td(p)` is the
  standalone conversion. This is a standard assumption about TD-count shape.

---

## `scoring/` — league scoring

### `scoring/config.py`
- `StatLine(receptions, receiving_yards, rushing_yards, touchdowns)` — one
  outcome. NOTE: `touchdowns` is **combined** rush + receive (the anytime-TD
  market prices one number; we can't split them).
- `ScoringConfig(points_per_*)` with `.score(line)`. Factories `ppr()`,
  `half_ppr()`, `standard()`; `from_preset(name)` and `PRESETS` for the CLI.
  Defaults are full-PPR (1.0/reception, 0.1/yard for both rush and receive,
  6/TD). Scoring is data, not code, so the same sim serves any league.

---

## `sim/` — Monte Carlo and correlation

### `sim/montecarlo.py`
- `PlayerModel(name, receptions, receiving_yards, rushing_yards, touchdowns)` —
  a player's four stat distributions; any may be `None` (no line offered).
- `ScoreDistribution(name, samples)` — wraps the simulated point array with
  `mean`, `median`, `std`, `quantile(q)`, `floor` (p10), `ceiling` (p90),
  `prob_over(threshold)`, `summary()`.
- `simulate_player(model, scoring, n_sims=50_000, seed=None, correlated=False)`
  — the entry point. `correlated=False` (default) samples each stat
  independently. `correlated=True` uses the Gaussian copula.
- Internals: `_simulate_independent` draws each marginal separately.
  `_simulate_correlated` builds the correlation matrix (via `_resolve_spec`,
  which computes usage features from the marginals' `expected_value()`s and
  calls `CorrelationSpec.from_features`), takes the **sub-matrix over only the
  stats the player actually has**, draws correlated normals, maps them to
  uniforms via `Phi`, and pushes each uniform through that stat's `invert(u)`.
  This leaves every marginal exactly unchanged.

### `sim/correlations.py`
The correlation model — **see [CORRELATIONS.md](CORRELATIONS.md) for the full
reasoning; do not edit without reading it.** In brief: position-agnostic,
continuous functions of odds-derived usage (chiefly `rush_share`). Key pieces:
`spearman_to_gaussian` (converts measured rank corr to the copula's Pearson
parameter), `PlayerFeatures` (usage features from marginal expectations),
`CorrelationSpec.from_features` (the single usage→correlation mapping), and
`gaussian_matrix()` (assembles + PSD-projects the 4×4 matrix).

---

## `cli/main.py`
Console script `ffmc` (defined in `pyproject.toml`). Subcommands:
- `simulate --event <path.json>` — simulate every player in a saved payload.
- `events` — list upcoming events (needs key or cache).
- `fetch --event-id <id>` — fetch live props for an event and simulate.

Common flags: `--scoring ppr|half_ppr|standard`, `--sims`, `--seed`, `--book`,
`--thresholds 10,15,20` (P(>x) columns), `--sport`, `--correlated` (opt into the
copula; default is independent). There is intentionally **no `--role` flag** —
correlations are derived from the odds, not position.

---

## `analysis/` (not shipped in the package)
Standalone scripts that pull public nflverse data to justify the correlation
model. `nflverse_correlation_check.py` measures per-player rank correlations and
how they vary with usage. `correlation_sensitivity.py` shows how much the
total-score tails move as an assumed correlation is dialed. See
[CORRELATIONS.md](CORRELATIONS.md).
