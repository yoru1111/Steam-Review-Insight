import io
import json
from urllib.error import HTTPError
from urllib.error import URLError

from src.data_pipeline.catalog import SteamCatalog
from src.data_pipeline.service import ReviewPipeline


class Responses:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        payload = self.payloads.pop(0)
        if isinstance(payload, BaseException):
            raise payload
        return io.BytesIO(json.dumps(payload).encode())


def store_payload(*apps):
    return {"response": {"apps": list(apps)}}


def test_catalog_download_is_cached_and_not_requested_again(tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_WEB_API_KEY", "test-key")
    responses = Responses(store_payload(
        {"appid": 1245620, "name": "ELDEN RING"},
        {"appid": 105600, "name": "Terraria"},
    ))
    catalog = SteamCatalog(tmp_path / "catalog.json", opener=responses, clock=lambda: 1000)

    assert catalog.games() == {1245620: "ELDEN RING", 105600: "Terraria"}
    assert catalog.games() == {1245620: "ELDEN RING", 105600: "Terraria"}
    assert len(responses.requests) == 1
    request = responses.requests[0]
    assert request.host == "api.steampowered.com"
    assert "key=" not in request.full_url
    assert request.get_header("X-webapi-key") == "test-key"


def test_authentication_errors_are_safe_and_actionable(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("STEAM_WEB_API_KEY", "secret-test-key")
    cases = ((401, "authentication failed (HTTP 401)"),
             (403, "access denied (HTTP 403)"))
    for status, message in cases:
        error = HTTPError("https://api.steampowered.com/redacted", status, "Auth error", {}, None)
        catalog = SteamCatalog(tmp_path / f"catalog-{status}.json", opener=Responses(error))
        assert catalog.games() == {}
        assert message in caplog.text
    assert "secret-test-key" not in caplog.text


def test_stale_cache_survives_refresh_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_WEB_API_KEY", "test-key")
    cache = tmp_path / "catalog.json"
    first = SteamCatalog(cache, opener=Responses(store_payload(
        {"appid": 413150, "name": "Stardew Valley"},
    )), clock=lambda: 1000)
    first.games()
    failing = SteamCatalog(cache, opener=Responses(URLError("offline")), clock=lambda: 100_000,
                           ttl_seconds=10)

    assert failing.games() == {413150: "Stardew Valley"}


def test_search_falls_back_to_bundled_catalog_when_download_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("STEAM_WEB_API_KEY", "test-key")
    catalog = SteamCatalog(tmp_path / "catalog.json", opener=Responses(URLError("offline")))
    pipeline = ReviewPipeline(tmp_path, steam_catalog=catalog)

    assert pipeline.search_games("Cyberpunk") == [
        {"app_id": 1091500, "name": "Cyberpunk 2077"},
    ]


def test_search_prioritizes_exact_then_prefix_then_partial(tmp_path):
    class Catalog:
        def games(self):
            return {
                1: "Ring", 2: "Ring of Pain", 4: "The Ringed City",
                105600: "Terraria", 413150: "Stardew Valley", 1245620: "ELDEN RING",
            }

    pipeline = ReviewPipeline(tmp_path, steam_catalog=Catalog())
    results = pipeline.search_games("ring")

    assert [game["name"] for game in results] == [
        "Ring", "Ring of Pain", "ELDEN RING", "The Ringed City",
    ]
    assert pipeline.search_games("terraria")[0]["app_id"] == 105600
    assert pipeline.search_games("stardew valley")[0]["app_id"] == 413150
    assert pipeline.search_games("elden ring")[0]["app_id"] == 1245620
