# PROJECT_CONTEXT

Read this first. It is the single entry point for understanding this project —
what it is, why it's built the way it is, what's done, what's unverified, and
where to look for detail. It is written for a person or agent picking this up
cold with no prior conversation.

## What this is

`fantasy-montecarlo` (package `ffmc`) turns **sportsbook player-prop odds** into
**Monte Carlo distributions of a player's fantasy-football score**. The core
premise: a book's posted over/under prop lines encode the market's implied
probability distribution over a player's stat outcomes. If we de-vig those odds,
reconstruct each stat's implied distribution, draw random outcomes, convert to
fantasy points, and repeat thousands of times, we get a *distribution* of a
player's fantasy score — floor / median / ceiling / P(exceeds X) — not just a
single point projection.

Scope (v1): **receptions, receiving yards, rushing yards, touchdowns**. No QBs,
kickers, or defense. Long-term goal: a browser extension overlaying these on the
Yahoo Fantasy UI. Right now it's an offline Python CLI.

## Current status (honest)

**Works and is tested (32 tests passing):**
- De-vig math, distribution reconstruction, sampling, scoring, per-player Monte
  Carlo, the opt-in correlated mode, and the CLI — all validated end-to-end on
  committed sample fixtures and against real nflverse data for the correlations.

**Built but NOT verified against the live API — the biggest open risk:**
- The Odds API integration (`src/ffmc/odds/client.py`, `markets.py`) was written
  from prior knowledge, not tested against the live endpoint. The market keys,
  JSON response shape, and free-tier request limits are **educated guesses**,
  flagged "confirm live" in the code. The first real `fetch` with an API key
  will likely need parser tweaks. **No live sportsbook data has ever flowed
  through the pipeline.**

**Not started:** Yahoo OAuth adapter, browser extension, t-copula, Shin's-method
de-vig. See "Roadmap" below.

## How the pipeline works (end to end)

1. **Fetch** odds for an event from The Odds API (or load a saved JSON fixture).
   Responses are cached to `data/cache/` to protect the free-tier quota.
2. **De-vig** each over/under pair. Raw implied probabilities include the book's
   margin and don't sum to 1; we remove it so the numbers are a real
   distribution. → `odds/devig.py`
3. **Reconstruct a distribution** per stat from the ladder of de-vigged lines,
   and make it sampleable via an inverse-CDF. → `distributions/`
4. **Score** each simulated stat line with a league scoring config. → `scoring/`
5. **Simulate** thousands of draws per player and summarize the fantasy-score
   distribution; optionally couple the stats with a Gaussian copula. → `sim/`
6. A **CLI** runs all this offline. → `cli/main.py`

## Repository map

```
src/ffmc/
  odds/           # American-odds math, de-vig, The Odds API client + payload parser
  distributions/  # ladder -> CDF -> inverse-transform sampler (per stat)
  scoring/        # league scoring config; stat line -> points
  sim/            # per-player Monte Carlo, aggregation, correlation (copula)
  cli/            # offline command-line entry point (console script `ffmc`)
analysis/         # standalone nflverse studies that justify the correlation model
data/samples/     # committed example event payloads (offline dev, no API key)
data/cache/       # cached live odds JSON (gitignored)
tests/            # pytest suite (32 tests)
```

## Detailed docs (read as needed)

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module-by-module explanation of
  every source file: what it does, key classes/functions, and how data flows.
- [docs/CORRELATIONS.md](docs/CORRELATIONS.md) — the correlation model in depth:
  the whole reasoning history, what the odds can and cannot tell us, the
  position-agnostic rush_share design, the fitted coefficients, and the nflverse
  analyses that produced them. **This is the most nuanced part of the project;
  read it before touching `sim/correlations.py`.**
- [docs/DECISIONS.md](docs/DECISIONS.md) — key modeling decisions and the
  assumptions/limitations behind them, with the rationale for each. Read this to
  avoid re-litigating settled questions or silently breaking an intentional choice.
- [README.md](README.md) — user-facing: install, usage, and a summary of the
  model. Overlaps with these docs but aimed at a user, not a maintainer.

## Environment / running it

- Python >= 3.10. In THIS sandbox the default `python` is 3.9; use the explicit
  interpreter `/root/.pyenv/versions/3.11.15/bin/python` (a bare `pyenv local`
  sets the version file but the shim doesn't always resolve for non-interactive
  shells here).
- Install: `pip install -e ".[dev,analysis]"` (dev = pytest; analysis = pandas +
  pyarrow for the nflverse scripts).
- Test: `pytest` (or `<py3.11> -m pytest`).
- Run offline: `ffmc simulate --event data/samples/sample_event.json --book draftkings --scoring ppr --correlated`
- Live: set `ODDS_API_KEY` (free key from the-odds-api.com), then `ffmc events` /
  `ffmc fetch --event-id <id> --book draftkings`.

## Git / this repo

- GitHub: `dkori/fantasy-montecarlo`, default branch `main`.
- In the sandbox the working clone is `/projects/sandbox/fantasy-montecarlo-remote`
  (the folder name has a `-remote` suffix for historical reasons; the repo itself
  is named `fantasy-montecarlo`). Push access works.

## Roadmap

- [ ] Validate the live Odds API integration (fix market keys / parser) — highest priority
- [ ] t-copula option (stronger tail dependence than the Gaussian copula)
- [ ] Shin's-method de-vig (better than the current multiplicative method)
- [ ] Yahoo Fantasy OAuth adapter (pull roster + league scoring)
- [ ] Browser extension overlay
