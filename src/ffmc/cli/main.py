"""Offline CLI for fantasy-montecarlo.

Examples:
    # Simulate every player in a cached/sample event payload (no API key):
    ffmc simulate --event data/samples/sample_event.json --scoring ppr --sims 50000

    # List upcoming NFL events (needs ODDS_API_KEY or a cached response):
    ffmc events

    # Fetch player props for one event and simulate (needs ODDS_API_KEY):
    ffmc fetch --event-id <id> --book draftkings --scoring ppr
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ffmc.odds.client import OddsClient
from ffmc.odds.markets import ALL_MARKETS, build_player_models
from ffmc.scoring.config import from_preset
from ffmc.sim.montecarlo import simulate_player


def _print_distribution(dist, thresholds: list[float]) -> None:
    s = dist.summary()
    print(f"\n{s['name']}")
    print(f"  mean {s['mean']:>6}   median {s['median']:>6}   sd {s['std']:>5}")
    print(f"  floor(p10) {s['floor_p10']:>6}   ceiling(p90) {s['ceiling_p90']:>6}")
    if thresholds:
        probs = "   ".join(
            f">{t}: {dist.prob_over(t) * 100:4.1f}%" for t in thresholds
        )
        print(f"  {probs}")


def _load_event(path: str) -> dict:
    return json.loads(Path(path).read_text())


def cmd_simulate(args: argparse.Namespace) -> int:
    payload = _load_event(args.event)
    models = build_player_models(payload, book_key=args.book)
    if not models:
        print("No players parsed from payload (check --book / market keys).")
        return 1
    scoring = from_preset(args.scoring)
    thresholds = [float(t) for t in args.thresholds.split(",")] if args.thresholds else []
    _run_and_print(models, scoring, args, thresholds)
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    client = OddsClient()
    events = client.list_events(sport=args.sport)
    for e in events:
        print(f"{e['id']}  {e['commence_time']}  {e['away_team']} @ {e['home_team']}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    client = OddsClient()
    payload = client.event_player_props(
        event_id=args.event_id,
        markets=ALL_MARKETS,
        sport=args.sport,
        bookmakers=args.book,
    )
    models = build_player_models(payload, book_key=args.book)
    scoring = from_preset(args.scoring)
    thresholds = [float(t) for t in args.thresholds.split(",")] if args.thresholds else []
    _run_and_print(models, scoring, args, thresholds)
    return 0


def _run_and_print(models, scoring, args, thresholds) -> None:
    mode = "correlated (Gaussian copula)" if args.correlated else "independent"
    print(f"[mode: {mode}]")
    for name in sorted(models):
        model = models[name]
        dist = simulate_player(
            model,
            scoring,
            n_sims=args.sims,
            seed=args.seed,
            correlated=args.correlated,
        )
        _print_distribution(dist, thresholds)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ffmc", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--scoring", default="ppr", help="ppr | half_ppr | standard")
    common.add_argument("--sims", type=int, default=50_000)
    common.add_argument("--seed", type=int, default=None)
    common.add_argument("--book", default=None, help="bookmaker key, e.g. draftkings")
    common.add_argument(
        "--thresholds", default="", help="comma list of point thresholds for P(>x)"
    )
    common.add_argument("--sport", default="americanfootball_nfl")
    common.add_argument(
        "--correlated",
        action="store_true",
        help="couple stats with a Gaussian copula (measured nflverse correlations); "
        "default is independent",
    )


    sp = sub.add_parser("simulate", parents=[common], help="simulate from a saved event payload")
    sp.add_argument("--event", required=True, help="path to event odds JSON")
    sp.set_defaults(func=cmd_simulate)

    ep = sub.add_parser("events", parents=[common], help="list upcoming events")
    ep.set_defaults(func=cmd_events)

    fp = sub.add_parser("fetch", parents=[common], help="fetch props for an event and simulate")
    fp.add_argument("--event-id", required=True)
    fp.set_defaults(func=cmd_fetch)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
