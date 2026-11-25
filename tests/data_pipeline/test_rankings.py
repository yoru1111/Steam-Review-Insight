from copy import deepcopy

import pytest

from src.data_pipeline.rankings import CHARTS, Rankings, parse_chart
from .test_game_details import PublicResponses

SELLERS = '<table><tr><td>1</td><td><a href="https://store.steampowered.com/app/620/">Portal 2</a></td><td>$10</td><td>2</td><td>8</td></tr></table>'
PLAYERS = '<table><tr><td>1</td><td><a href="https://store.steampowered.com/app/400/">Portal</a></td><td>$10</td><td>1,234</td><td>2,345</td></tr></table>'


def snapshot(kind="top_sellers"):
    url, metric, _, _ = CHARTS[kind]
    return {
        "ranking_type": kind, "ranking_metric": metric, "ranking_scope": "global",
        "source_url": url, "fetched_at_utc": "2026-01-01T00:00:00Z",
        "games": [{"rank": 1, "app_id": 620, "name": "Portal 2", "current_players": 5}],
    }


def test_chart_types_and_cache(tmp_path):
    replies = PublicResponses(SELLERS, PLAYERS)
    service = Rankings(tmp_path, client=replies.client())
    sellers = service.get("top_sellers", include_details=False)
    players = service.get("most_played", include_details=False)
    assert sellers["ranking_metric"] == "revenue"
    assert players["ranking_metric"] == "current_concurrent_players"
    assert sellers["games"][0]["current_players"] is None
    assert players["games"][0]["current_players"] == 1234
    assert players["games"][0]["peak_today_players"] == 2345
    assert players["source_url"] != sellers["source_url"]
    assert players["ranking_scope"] == sellers["ranking_scope"] == "global"
    assert service.get("top_sellers", include_details=False)["cache_used"]
    assert len(replies.calls) == 2


def test_stale_failure_preserves_time(tmp_path):
    clock = [0]
    replies = PublicResponses(SELLERS, "format has changed", "")
    service = Rankings(tmp_path, client=replies.client(), ttl_seconds={"top_sellers": 10},
                       clock=lambda: clock[0])
    first = service.get("top_sellers", include_details=False)
    clock[0] = 100
    stale = service.get("top_sellers", include_details=False)
    assert stale["status"] == "stale" and stale["cache_used"] and stale["cache_stale"]
    assert stale["fetched_at_utc"] == first["fetched_at_utc"]
    assert service.get("most_played", include_details=False)["status"] == "unavailable"


@pytest.mark.parametrize("mutation", ["scope", "metric", "duplicate_id", "duplicate_rank", "time", "source", "negative"])
def test_invalid_snapshot(tmp_path, mutation):
    payload = snapshot()
    if mutation == "scope":
        payload["ranking_scope"] = "candidates_20"
    elif mutation == "metric":
        payload["ranking_metric"] = "sales_units"
    elif mutation == "duplicate_id":
        payload["games"].append({**payload["games"][0], "rank": 2})
    elif mutation == "duplicate_rank":
        payload["games"].append({**payload["games"][0], "app_id": 400})
    elif mutation == "time":
        payload["fetched_at_utc"] = "2090-01-01T00:00:00Z"
    elif mutation == "source":
        payload["source_url"] = "https://example.test/chart"
    else:
        payload["games"][0]["rank"] = -1
    with pytest.raises(ValueError):
        Rankings(tmp_path).import_snapshot(payload)


def test_snapshot_fallback_and_current_counts(tmp_path):
    replies = PublicResponses("changed")
    service = Rankings(tmp_path, client=replies.client())
    imported = service.import_snapshot(snapshot("most_played"))
    result = service.get("most_played", include_details=False)
    assert result["cache_used"] and result["status"] == "stale"
    assert result["acquisition_method"] == "imported_official_chart_snapshot"
    assert result["fetched_at_utc"] == imported["fetched_at_utc"]


def test_changed_or_duplicate_html_rejected():
    with pytest.raises((ValueError, RuntimeError)):
        parse_chart("<html>Login required</html>", "top_sellers")
    with pytest.raises((ValueError, RuntimeError)):
        parse_chart(SELLERS + SELLERS, "top_sellers")
