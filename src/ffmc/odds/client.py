"""The Odds API client with on-disk caching.

The free tier is quota-limited (a few hundred requests/month), so every response
is cached to ``data/cache/`` keyed by the request. During development you work
almost entirely from cache; a live call is only made on a cache miss (or when
``force_refresh`` is set).

Player props live on the *event-odds* endpoint, not the bulk odds endpoint:
    GET /v4/sports/{sport}/events/{event_id}/odds

The exact market keys (e.g. player_receptions, player_reception_yds and their
_alternate variants, player_anytime_td) should be confirmed against the live API
once you have a key; they are centralized in ffmc.odds.markets.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

import requests

BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_CACHE_DIR = Path("data/cache")


class OddsAPIError(RuntimeError):
    pass


class OddsClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ODDS_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = session or requests.Session()

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"{digest}.json"

    def _get(self, path: str, params: dict[str, Any], *, force_refresh: bool = False) -> Any:
        cache_key = path + "?" + json.dumps(params, sort_keys=True)
        cache_file = self._cache_path(cache_key)

        if cache_file.exists() and not force_refresh:
            return json.loads(cache_file.read_text())

        if not self.api_key:
            raise OddsAPIError(
                "No cached response and ODDS_API_KEY is not set. "
                "Set the env var or work from a fixture in data/samples/."
            )

        params = {**params, "apiKey": self.api_key}
        resp = self._session.get(f"{BASE_URL}{path}", params=params, timeout=30)
        if resp.status_code != 200:
            raise OddsAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        cache_file.write_text(json.dumps(data))
        # Surface quota usage if the API returned it.
        remaining = resp.headers.get("x-requests-remaining")
        if remaining is not None:
            print(f"[odds-api] requests remaining this period: {remaining}")
        return data

    def list_events(self, sport: str = "americanfootball_nfl", **kw) -> list[dict]:
        """Upcoming events (games) for a sport. Cheap; does not include props."""
        return self._get(f"/sports/{sport}/events", {}, **kw)

    def event_player_props(
        self,
        event_id: str,
        markets: list[str],
        sport: str = "americanfootball_nfl",
        regions: str = "us",
        bookmakers: Optional[str] = None,
        odds_format: str = "american",
        **kw,
    ) -> dict:
        """Player-prop odds for a single event.

        ``markets`` is a comma-joined list of market keys (see ffmc.odds.markets).
        ``bookmakers`` optionally restricts to a single book, e.g. 'draftkings'.
        """
        params: dict[str, Any] = {
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": odds_format,
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        return self._get(f"/sports/{sport}/events/{event_id}/odds", params, **kw)
