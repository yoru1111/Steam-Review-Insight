"""Public Store appdetails metadata with configurable TTL and stale fallback."""
from datetime import datetime
import time
from urllib.parse import urlencode, urlsplit

from .collector import CollectionError
from .public_steam import PublicSteamClient
from .service import require_app_id
from .storage import now, read_json, write_json, writer_lock

DETAILS_ENDPOINT = "https://store.steampowered.com/api/appdetails"


def image_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        valid = host.endswith(".steamstatic.com") or host == "steamcdn-a.akamaihd.net"
        return value if (parsed.scheme == "https" and valid and not parsed.username and not parsed.password
                         and parsed.port in (None, 443)) else None
    except ValueError:
        return None


def release_date(value, coming_soon):
    if coming_soon or not isinstance(value, str):
        return None
    for pattern in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    return None


def string_list(value):
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def parse_details(payload, app_id):
    entry = payload.get(str(app_id)) if isinstance(payload, dict) else None
    if not isinstance(entry, dict) or entry.get("success") is not True:
        raise CollectionError("Steam game details are unavailable for this App ID")
    data = entry.get("data")
    if not isinstance(data, dict) or data.get("steam_appid") != app_id:
        raise CollectionError("Steam game details App ID mismatch")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise CollectionError("Steam game details have no valid name")
    genres = data.get("genres")
    genres = [row["description"].strip() for row in genres
              if isinstance(row, dict) and isinstance(row.get("description"), str) and row["description"].strip()
              ] if isinstance(genres, list) else []
    released = data.get("release_date")
    released = released if isinstance(released, dict) else {}
    coming_soon = released.get("coming_soon") if type(released.get("coming_soon")) is bool else None
    raw_date = released.get("date") if isinstance(released.get("date"), str) else None
    result = {
        "app_id": app_id, "name": data["name"].strip(), "header_image": image_url(data.get("header_image")),
        "genres": list(dict.fromkeys(genres)), "release_date": release_date(raw_date, coming_soon),
        "release_date_raw": raw_date, "coming_soon": coming_soon,
        "store_url": f"https://store.steampowered.com/app/{app_id}/",
        "short_description": data.get("short_description") if isinstance(data.get("short_description"), str) else None,
        "developers": string_list(data.get("developers")), "publishers": string_list(data.get("publishers")),
        "is_free": data.get("is_free") if type(data.get("is_free")) is bool else None,
        "game_type": data.get("type") if isinstance(data.get("type"), str) else None,
        "supported_languages": data.get("supported_languages") if isinstance(data.get("supported_languages"), str) else None,
    }
    missing = [key for key in ("header_image", "genres", "release_date", "game_type") if not result[key]]
    result.update(missing_fields=missing, metadata_status="partial" if missing else "complete")
    return result


class GameDetails:
    def __init__(self, root, *, client=None, ttl_seconds=86400, clock=time.time):
        self.directory = root / "data/game_details"
        self.client = client or PublicSteamClient()
        self.ttl_seconds, self.clock = ttl_seconds, clock

    def get(self, app_id, refresh=False):
        require_app_id(app_id)
        path = self.directory / f"{app_id}.json"
        with writer_lock(self.directory):
            cached = read_json(path)
            age = max(0, self.clock() - cached["fetched_at"]) if cached else None
            stale = age is None or age >= self.ttl_seconds
            if cached and not stale and not refresh:
                return {**cached, "cache_used": True, "cache_stale": False, "cache_age_seconds": age, "error": None}
            url = DETAILS_ENDPOINT + "?" + urlencode({"appids": app_id, "l": "english", "cc": "us"})
            try:
                result = {
                    **parse_details(self.client.get(url), app_id),
                    "source": "Steam Store public appdetails (undocumented contract)",
                    "source_url": url, "response_language": "english", "region": "us",
                    "fetched_at": self.clock(), "fetched_at_utc": now(),
                    "cache_used": False, "cache_stale": False, "cache_age_seconds": 0, "error": None,
                }
                write_json(path, result)
                return result
            except CollectionError as exc:
                if cached:
                    return {**cached, "cache_used": True, "cache_stale": stale,
                            "cache_age_seconds": age, "error": str(exc)}
                return {
                    "app_id": app_id, "name": None, "header_image": None, "genres": [],
                    "release_date": None, "release_date_raw": None, "coming_soon": None,
                    "store_url": f"https://store.steampowered.com/app/{app_id}/", "game_type": None,
                    "source": "Steam Store public appdetails (undocumented contract)", "source_url": url,
                    "fetched_at_utc": None, "cache_used": False, "cache_stale": None,
                    "metadata_status": "unavailable", "missing_fields": ["name", "header_image", "genres", "release_date"],
                    "error": str(exc),
                }

    def batch(self, app_ids, refresh=False):
        identifiers = list(dict.fromkeys(app_ids))
        if len(identifiers) > 100:
            raise ValueError("At most 100 distinct games per batch")
        return [self.get(require_app_id(identifier), refresh) for identifier in identifiers]
