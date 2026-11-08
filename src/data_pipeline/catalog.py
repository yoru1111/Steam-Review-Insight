"""Cached Steam application catalog used only for game-name lookup."""
from datetime import datetime, timezone
import http.client
import json
import logging
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .schema import app_id
from .storage import read_json, write_json

LOG = logging.getLogger(__name__)
STORE_ENDPOINT = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_RETRY_SECONDS = 60 * 60
MAX_RESULTS = 50_000


class CatalogError(RuntimeError):
    """Steam catalog could not be downloaded or validated."""


def _games(rows):
    games = {}
    if not isinstance(rows, list):
        raise CatalogError("Steam catalog has no app list")
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = app_id(row.get("appid"))
        name = row.get("name")
        if identifier is not None and isinstance(name, str) and name.strip():
            games[identifier] = name.strip()
    if not games:
        raise CatalogError("Steam catalog contains no named apps")
    return games


class SteamCatalog:
    def __init__(self, cache_path: Path, *, opener=urlopen, clock=time.time,
                 ttl_seconds=DEFAULT_TTL_SECONDS, retry_seconds=DEFAULT_RETRY_SECONDS,
                 timeout=30):
        self.cache_path = Path(cache_path)
        self.opener = opener
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self.retry_seconds = retry_seconds
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next_retry = 0.0

    def _read_cache(self):
        payload = read_json(self.cache_path)
        if not isinstance(payload, dict) or not isinstance(payload.get("games"), dict):
            return None
        games = {}
        for key, name in payload["games"].items():
            identifier = app_id(key)
            if identifier is not None and isinstance(name, str) and name.strip():
                games[identifier] = name.strip()
        fetched_at = payload.get("fetched_at")
        if not games or not isinstance(fetched_at, (int, float)):
            return None
        return games, float(fetched_at)

    def _request_json(self, url, *, api_key=None):
        headers = {"User-Agent": "Steam-Review-Insight/1.0"}
        if api_key:
            headers["x-webapi-key"] = api_key
        request = Request(url, headers=headers)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if code == 401:
                raise CatalogError("Steam catalog authentication failed (HTTP 401); check the Web API key") from None
            if code == 403:
                raise CatalogError(
                    "Steam catalog access denied (HTTP 403); check the Web API key, key type, and access policy"
                ) from None
            raise CatalogError(f"Steam catalog HTTP {code}") from None
        except (TimeoutError, URLError, OSError, http.client.HTTPException) as exc:
            reason = type(getattr(exc, "reason", exc)).__name__
            raise CatalogError(f"Steam catalog network error ({reason})") from None
        except (ValueError, RecursionError):
            raise CatalogError("Steam catalog returned invalid JSON") from None

    def _download_store_catalog(self, key):
        games = {}
        last_appid = 0
        while True:
            options = {"include_games": True, "last_appid": last_appid,
                       "max_results": MAX_RESULTS}
            query = urlencode({"input_json": json.dumps(options, separators=(",", ":"))})
            payload = self._request_json(STORE_ENDPOINT + "?" + query, api_key=key)
            response = payload.get("response") if isinstance(payload, dict) else None
            if not isinstance(response, dict):
                raise CatalogError("Steam store catalog has no response object")
            rows = response.get("apps", [])
            if not rows:
                break
            games.update(_games(rows))
            next_appid = app_id(rows[-1].get("appid")) if isinstance(rows[-1], dict) else None
            if next_appid is None or next_appid <= last_appid:
                raise CatalogError("Steam store catalog pagination did not advance")
            last_appid = next_appid
            if len(rows) < MAX_RESULTS:
                break
        if not games:
            raise CatalogError("Steam store catalog contains no named games")
        return games, "IStoreService/GetAppList/v1"

    def _download(self):
        key = os.environ.get("STEAM_WEB_API_KEY", "").strip()
        if not key:
            raise CatalogError("STEAM_WEB_API_KEY is not configured for the Steam store catalog")
        return self._download_store_catalog(key)

    def games(self):
        """Return cached games, refreshing at most daily and retaining stale data on failure."""
        cached = self._read_cache()
        current = self.clock()
        if cached and current - cached[1] < self.ttl_seconds:
            return cached[0]
        if current < self._next_retry:
            return cached[0] if cached else {}
        with self._lock:
            cached = self._read_cache()
            current = self.clock()
            if cached and current - cached[1] < self.ttl_seconds:
                return cached[0]
            if current < self._next_retry:
                return cached[0] if cached else {}
            try:
                games, source = self._download()
                write_json(self.cache_path, {
                    "fetched_at": current,
                    "fetched_at_utc": datetime.fromtimestamp(current, timezone.utc).isoformat(),
                    "source": source,
                    "games": {str(key): games[key] for key in sorted(games)},
                })
                self._next_retry = 0.0
                return games
            except CatalogError as exc:
                self._next_retry = current + self.retry_seconds
                LOG.warning("%s; using %s", exc, "stale cache" if cached else "bundled catalog")
                return cached[0] if cached else {}
