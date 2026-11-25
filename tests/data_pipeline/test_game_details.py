import io
import json
from urllib.error import HTTPError, URLError

import pytest

from src.data_pipeline.game_details import GameDetails, image_url, parse_details, release_date
from src.data_pipeline.public_steam import PublicSteamClient


def details_payload(identifier=620, **fields):
    return {str(identifier): {"success": True, "data": {
        "steam_appid": identifier, "name": "Portal 2", "type": "game",
        "header_image": "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/620/header.jpg",
        "genres": [{"description": "Action"}, {"description": "Action"}, {"description": "Adventure"}],
        "release_date": {"date": "18 Apr, 2011", "coming_soon": False}, **fields,
    }}}


class PublicResponses:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.sleeps = []

    def open(self, request, timeout):
        self.calls.append(request.full_url)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        if not isinstance(value, (bytes, str)):
            value = json.dumps(value).encode()
        return io.BytesIO(value.encode() if isinstance(value, str) else value)

    def client(self, **kwargs):
        return PublicSteamClient(opener=self.open, sleep=self.sleeps.append, **kwargs)


def test_details_and_cache(tmp_path):
    replies = PublicResponses(details_payload())
    service = GameDetails(tmp_path, client=replies.client())
    result = service.get(620)
    assert result["metadata_status"] == "complete"
    assert result["release_date"] == "2011-04-18" and result["genres"] == ["Action", "Adventure"]
    assert service.get(620)["cache_used"] and len(replies.calls) == 1
    assert result["source_url"].startswith("https://store.steampowered.com/api/appdetails")
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("raw,soon,parsed", [
    ("18 Apr, 2011", False, "2011-04-18"), ("Apr 18, 2011", False, "2011-04-18"),
    ("2026", False, None), ("Q4 2026", True, None), ("Nov 2026", False, None),
    ("2024-02-29", False, "2024-02-29"), ("Feb 30, 2024", False, None),
])
def test_release_dates(raw, soon, parsed):
    assert release_date(raw, soon) == parsed


def test_missing_fields_and_unverified_image():
    result = parse_details(details_payload(header_image="https://example.test/image.jpg", genres=[]), 620)
    assert result["metadata_status"] == "partial" and result["header_image"] is None
    assert result["missing_fields"] == ["header_image", "genres"]
    assert image_url("http://shared.fastly.steamstatic.com/a.jpg") is None


def test_stale_and_invalid_app(tmp_path):
    clock = [100]
    replies = PublicResponses(details_payload(), {"620": {"success": False}}, {"999": {"success": False}})
    service = GameDetails(tmp_path, client=replies.client(), ttl_seconds=10, clock=lambda: clock[0])
    original = service.get(620)
    clock[0] = 200
    fallback = service.get(620)
    assert fallback["cache_used"] and fallback["cache_stale"] and fallback["error"]
    assert fallback["fetched_at_utc"] == original["fetched_at_utc"]
    assert service.get(999)["metadata_status"] == "unavailable"
    with pytest.raises(ValueError):
        service.get(-1)


@pytest.mark.parametrize("failure", [
    lambda: HTTPError("https://store.steampowered.com/", 429, "test", {"Retry-After": "0"}, None),
    lambda: URLError("offline"),
])
def test_public_retries(failure):
    replies = PublicResponses(failure(), failure(), details_payload())
    assert replies.client().get("https://store.steampowered.com/api/appdetails?appids=620")["620"]["success"]
    assert len(replies.calls) == 3


def test_bad_id_and_arbitrary_host():
    with pytest.raises(Exception, match="mismatch"):
        parse_details(details_payload(steam_appid=400), 620)
    with pytest.raises(ValueError, match="Only fixed"):
        PublicResponses().client().get("https://example.test/private")


def test_details_batch_and_cached_game_search(pipeline):
    replies = PublicResponses(details_payload(12345, name="Mock Test Game"))
    pipeline.public_client = replies.client()
    results = pipeline.get_game_details_batch([12345, 12345])
    assert len(results) == 1
    assert pipeline.search_games("Mock Test") == [{"app_id": 12345, "name": "Mock Test Game"}]
    assert pipeline.get_game_details_batch([12345])[0]["cache_used"]
