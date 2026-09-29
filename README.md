# fantasy-montecarlo

Monte Carlo fantasy football projections built from **sportsbook player-prop odds**.

The idea: a sportsbook's posted over/under prop lines for a player encode the
market's probability distribution over that player's stat outcomes. If we
de-vig those odds and reconstruct the implied distribution for each stat, we can
draw random outcomes, convert them to fantasy points, and build a Monte Carlo
distribution of a player's fantasy score — a floor/ceiling/median, not just a
single point projection.

Long-term goal: a browser add-on that overlays these projections on the Yahoo
Fantasy UI. For now it's an offline CLI.

## What it models (v1)

Stats: **receptions, receiving yards, rushing yards, touchdowns**. (No QBs,
kickers, or defense yet.)

- **Yards** are treated as continuous.
- **Receptions** are treated as discrete counts.
- **Touchdowns** are treated as discrete counts, derived from the anytime-TD
  market (see below).

## How it works

1. **Fetch odds** for a player from a sportsbook via [The Odds API](https://the-odds-api.com)
   (free tier, alternate-line markets). Responses are cached to `data/cache/`
   so development doesn't burn the monthly request quota.
2. **De-vig** each over/under pair. Posted implied probabilities include the
   bookmaker's margin (overround/"vig") and do **not** sum to 1; we remove it so
   the numbers are a real probability distribution.
3. **Reconstruct a distribution** per stat from the ladder of de-vigged lines
   (see `distributions/`), then **inverse-transform sample** from it.
4. **Score** each simulated stat line using a league scoring config.
5. **Aggregate** thousands of simulations into a fantasy-score distribution
   (mean, median, quantiles, floor/ceiling, P(> threshold)).

## Correlated mode (Gaussian copula)

Pass `--correlated` to couple a player's stats instead of treating them as
independent. Correlations are **measured from real nflverse game logs** (2018–
2023), not assumed — see `analysis/`.

**Position-agnostic, predicted from the odds.** There is no position label and
no WR/RB branch. Every correlation is a *continuous function* of odds-derived
usage that any player has (possibly zero) — chiefly **rush_share** (= expected
rushing yards ÷ total expected yards) and **YPC**. A player's profile emerges
from their own prop lines: a pure receiver has rush_share 0 (rushing couplings
vanish), a pure runner has rush_share ≈ 1, a dual-threat lands smoothly between.
Calibrated by pooling *all* skill players (193, WR/TE/RB/FB, 2018–2023) with no
position filter — position is not an input at any stage.

| Stat pair | Value | Basis |
|---|---|---|
| receptions ↔ receiving yards | **0.80** (flat) | strong & uniform across all players (sd 0.06) |
| rushing yards ↔ TDs | **0.024 + 0.489·rush_share**, clamped [0, 0.45] | ~0 for receivers → ~0.40 for runners (**R²=0.64**) |
| receiving yards ↔ TDs | **0.364 − 0.265·rush_share** + YPC tilt (faded by receiving share) | falls as scoring migrates to the ground (R²=0.33) |
| rushing yards ↔ receiving yards / receptions | **0.017 + 0.161·rush_share**, clamped [0, 0.30] | mild; volume tracks together (R²=0.12) |
| receptions ↔ TDs | **≈ 0.24 + 0.09·(TD/100yds)**, clamped [0.24, 0.38] | weak red-zone tilt (R²≈0.04) |

Example (one formula, no position): rush_share 0 → rush↔TD 0.02, recyds↔TD 0.41;
rush_share 0.5 → 0.27 / 0.20; rush_share 1.0 → 0.45 / 0.10. TDs remain a single
pooled count (rush + receive) because the anytime-TD market prices only one
number, so rush↔TD couples rushing yards to *total* TDs (exactly what was
measured).

YPC = expected receiving yards ÷ expected receptions; both come straight from
the marginals, so this is computable at runtime from the odds. If a feature
can't be computed (e.g. no receiving-yards line), it falls back to a pooled
mean, or to `--role` (`perimeter_wr | slot_wr | te | pass_catching_rb`) if given.

**Important honesty note:** the odds do *not* contain these correlations —
single-stat props never price the joint. These features *predict* correlation
via a relationship calibrated on history, and the predictive power is real but
**modest** (R² ~0.15 for the useful one). Treat per-player values as
better-than-uniform estimates, not precise truths.

Mechanics: draw correlated normals `z ~ N(0, R)`, map to uniforms `u = Φ(z)`,
push each `u` through that stat's inverse-CDF. Each **marginal is provably
unchanged** (odds-implied probabilities preserved); only co-movement — and thus
the total-score tails — changes. Spearman correlations are converted to the
copula's Pearson parameter via `ρ_pearson = 2·sin(π·ρ_spearman/6)`.

Effect (sample WR, 200k sims): mean stays 16.4 in both modes; the p10–p90
spread widens from ~22.8 (independent) to ~31 (correlated) — the compressed-
tails bias being corrected. Two players differing only in usage get different
couplings: a deep threat (YPC 20) → yds↔TD 0.50 vs a possession type (YPC 9) →
0.275.

Remaining caveats: correlations come from top-usage players; TD correlations
are inherently noisy (near-binary per game); the Gaussian copula has thin tail
dependence (a t-copula would better model "everything clicks at once" games);
and cross-player correlation (a WR and his QB) is still **not** modeled.

## Assumptions & known limitations

These are deliberate v1 simplifications. Read them before trusting the numbers.

- **Independence between stats (the default mode).** By default we sample
  receptions, receiving yards, rushing yards, and TDs independently per player.
  In reality they are positively correlated (more catches → more yards → more
  TD chances). Independence **understates the variance of the total** — the boom
  and bust tails get compressed, so a point projection is fine but floor/ceiling
  look more confident than reality. An **opt-in correlated mode** (Gaussian
  copula, `--correlated`) corrects this; see below. Independence remains the
  default so nothing changes silently.
- **The vig must be removed, and how you remove it is a modeling choice.** v1
  uses simple multiplicative (proportional) de-vigging. This ignores
  favorite-longshot bias; Shin's method or a power method would be better. The
  de-vig interface is pluggable.
- **Tail extrapolation.** Books only post lines over a limited range. Outcomes
  beyond the lowest/highest posted line require extrapolating the tail of the
  CDF, which is a genuine assumption (we use a parametric tail). Tails matter a
  lot for ceiling games.
- **Touchdowns come from a single probability.** Books typically post only
  "anytime TD" = P(at least 1 TD), not a full ladder. We convert that to a
  Poisson rate `λ = -ln(1 - p)` and sample TD counts from Poisson(λ). This is a
  standard trick but it is an assumption about the shape of the TD distribution.
- **Single bookmaker.** v1 reads one book's lines rather than consensus across
  books. A consensus/fair-line blend would be more robust.
- **Market efficiency.** The whole approach assumes the sportsbook's lines are a
  good estimate of true probabilities. That's a defensible prior, but it means
  the projections inherit any market bias.

## Project layout

```
src/ffmc/
  odds/           # The Odds API client (cached) + de-vig math
  distributions/  # ladder -> CDF -> inverse-transform sampler
  scoring/        # league scoring config + stat-line -> points
  sim/            # per-player Monte Carlo + aggregation
  cli/            # offline command-line entry point
data/cache/       # cached raw odds JSON (gitignored)
data/samples/     # small committed fixtures for offline dev/tests
tests/
```

## Setup

```bash
pip install -e ".[dev]"
export ODDS_API_KEY=your_key_here   # from https://the-odds-api.com
```

## Usage

```bash
# Run against the committed sample event (no API key needed), independent mode:
ffmc simulate --event data/samples/sample_event.json --book draftkings \
    --scoring ppr --sims 50000 --thresholds 10,15,20

# Same, but with the measured-correlation Gaussian copula and a role:
ffmc simulate --event data/samples/sample_event.json --book draftkings \
    --scoring ppr --sims 50000 --correlated --role perimeter_wr

# List upcoming NFL events (needs ODDS_API_KEY or a cached response):
ffmc events

# Fetch player props for one event and simulate (needs ODDS_API_KEY):
ffmc fetch --event-id <id> --book draftkings --scoring ppr
```

### Reproducing the correlation analysis

```bash
pip install -e ".[analysis]"          # adds pandas + pyarrow
python analysis/nflverse_correlation_check.py   # pulls public nflverse data
python analysis/correlation_sensitivity.py      # how much rho moves the tails
```

## Roadmap

- [x] Gaussian copula for intra-player stat correlation (opt-in, measured corrs)
- [ ] t-copula option for stronger tail dependence
- [ ] Shin's method de-vig
- [ ] Consensus across multiple books
- [ ] Yahoo Fantasy OAuth adapter (pull roster + league scoring)
- [ ] Browser extension overlay
