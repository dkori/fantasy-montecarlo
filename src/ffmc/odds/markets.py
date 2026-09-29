"""The Odds API market keys and a parser from raw payload -> PlayerModel.

Market keys (confirm against the live API with your key; centralized here so a
rename is a one-line change). The Odds API groups over/under outcomes under a
market; each outcome has a player ``description``, a ``name`` of "Over"/"Under",
a ``point`` (the line/threshold), and a ``price`` (the odds).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ffmc.distributions.ladder import (
    ContinuousLadderDistribution,
    DiscreteLadderDistribution,
    LadderPoint,
)
from ffmc.distributions.poisson import PoissonTouchdownDistribution
from ffmc.odds.devig import DevigMethod, devig_prob_from_pair
from ffmc.sim.montecarlo import PlayerModel

# Main + alternate line markets we consume.
MARKET_RECEPTIONS = ["player_receptions", "player_receptions_alternate"]
MARKET_RECEIVING_YDS = ["player_reception_yds", "player_reception_yds_alternate"]
MARKET_RUSHING_YDS = ["player_rush_yds", "player_rush_yds_alternate"]
MARKET_ANYTIME_TD = ["player_anytime_td"]

ALL_MARKETS = (
    MARKET_RECEPTIONS + MARKET_RECEIVING_YDS + MARKET_RUSHING_YDS + MARKET_ANYTIME_TD
)


def _collect_over_under(
    outcomes: list[dict],
) -> dict[str, dict[float, dict[str, float]]]:
    """Group outcomes -> {player: {point: {"Over": price, "Under": price}}}."""
    by_player: dict[str, dict[float, dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for o in outcomes:
        player = o.get("description")
        point = o.get("point")
        side = o.get("name")  # "Over" / "Under" / "Yes" / "No"
        price = o.get("price")
        if player is None or price is None:
            continue
        if point is None:
            point = 0.5  # anytime-TD style Yes/No has no point
        by_player[player][float(point)][side] = float(price)
    return by_player


def _ladder_for(
    markets_payload: dict, market_keys: list[str], book_key: Optional[str]
) -> dict[str, list[LadderPoint]]:
    """Build per-player ladders of de-vigged P(X > threshold) from over/under pairs."""
    ladders: dict[str, list[LadderPoint]] = defaultdict(list)
    for book in markets_payload.get("bookmakers", []):
        if book_key and book["key"] != book_key:
            continue
        for market in book.get("markets", []):
            if market["key"] not in market_keys:
                continue
            grouped = _collect_over_under(market.get("outcomes", []))
            for player, points in grouped.items():
                for point, sides in points.items():
                    if "Over" in sides and "Under" in sides:
                        p_over = devig_prob_from_pair(
                            sides["Over"], sides["Under"], DevigMethod.MULTIPLICATIVE
                        )
                        ladders[player].append(LadderPoint(point, p_over))
    # De-dup thresholds (prefer keeping one point per threshold).
    for player, pts in ladders.items():
        seen: dict[float, LadderPoint] = {}
        for p in pts:
            seen[p.threshold] = p
        ladders[player] = sorted(seen.values(), key=lambda p: p.threshold)
    return ladders


def _anytime_td_probs(
    markets_payload: dict, book_key: Optional[str]
) -> dict[str, float]:
    """Extract de-vigged P(>=1 TD) per player from the anytime-TD (Yes/No) market."""
    out: dict[str, float] = {}
    for book in markets_payload.get("bookmakers", []):
        if book_key and book["key"] != book_key:
            continue
        for market in book.get("markets", []):
            if market["key"] not in MARKET_ANYTIME_TD:
                continue
            grouped = _collect_over_under(market.get("outcomes", []))
            for player, points in grouped.items():
                for _, sides in points.items():
                    if "Yes" in sides and "No" in sides:
                        out[player] = devig_prob_from_pair(
                            sides["Yes"], sides["No"], DevigMethod.MULTIPLICATIVE
                        )
                    elif "Yes" in sides:
                        # Only one side priced; use raw implied (best effort).
                        from ffmc.odds.devig import american_to_implied_prob

                        out[player] = american_to_implied_prob(sides["Yes"])
    return out


def build_player_models(
    markets_payload: dict, book_key: Optional[str] = None
) -> dict[str, PlayerModel]:
    """Turn one event's odds payload into {player_name: PlayerModel}."""
    rec = _ladder_for(markets_payload, MARKET_RECEPTIONS, book_key)
    rec_yds = _ladder_for(markets_payload, MARKET_RECEIVING_YDS, book_key)
    rush_yds = _ladder_for(markets_payload, MARKET_RUSHING_YDS, book_key)
    td = _anytime_td_probs(markets_payload, book_key)

    players = set(rec) | set(rec_yds) | set(rush_yds) | set(td)
    models: dict[str, PlayerModel] = {}
    for name in players:
        models[name] = PlayerModel(
            name=name,
            receptions=(
                DiscreteLadderDistribution(rec[name]) if rec.get(name) else None
            ),
            receiving_yards=(
                ContinuousLadderDistribution(rec_yds[name])
                if rec_yds.get(name)
                else None
            ),
            rushing_yards=(
                ContinuousLadderDistribution(rush_yds[name])
                if rush_yds.get(name)
                else None
            ),
            touchdowns=(
                PoissonTouchdownDistribution(td[name]) if name in td else None
            ),
        )
    return models
