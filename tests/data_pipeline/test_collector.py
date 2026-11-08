import json
from urllib.error import HTTPError, URLError

import pytest

from src.data_pipeline.collector import ENDPOINT, CollectionError, parse_page
from src.data_pipeline.storage import read_json

from .conftest import page, review


def http(code, headers=None):
    return HTTPError(ENDPOINT, code, "test", headers, None)


def test_public_input_json_and_cursor(pipeline, transport, monkeypatch):
    monkeypatch.setenv("STEAM_WEB_API_KEY", "test-secret")
    transport.queue += [page(review(1), cursor="x+/="), page(review(2))]
    status = pipeline.collect_reviews(620, limit=2)
    assert status["review_count"] == 2
    assert status["last_attempt"]["pages"] == 2
    first, headers = transport.requests[0]
    assert set(first) == {"input_json"} and not headers
    assert json.loads(first["input_json"][0]) == {
        "appid": 620, "filter": 1, "languages": ["english"], "review_type": 0,
        "purchase_type": 1, "num_per_page": 2, "cursor": "*",
    }
    assert json.loads(transport.requests[1][0]["input_json"][0])["cursor"] == "x+/="
    path = pipeline.root / "data/raw/steam/620" / status["run_id"] / "000000.json"
    assert read_json(path) == page(review(1), cursor="x+/=")
    assert parse_page(read_json(path))[0][0]["recommendationid"] == "1"


def test_positive_and_negative_filters_have_independent_caches(pipeline, transport):
    transport.queue += [
        page(review(1, voted_up=True), cursor="positive-next"),
        page(review(2, voted_up=False), cursor="negative-next"),
    ]
    positive = pipeline.collect_reviews(620, limit=1, review_type=1)
    negative = pipeline.collect_reviews(620, limit=1, review_type=2)

    assert positive["review_type_name"] == "positive"
    assert negative["review_type_name"] == "negative"
    request_types = [json.loads(params["input_json"][0])["review_type"]
                     for params, _ in transport.requests]
    assert request_types == [1, 2]
    state = read_json(pipeline.root / "data/raw/steam/620/state.json")
    assert state["active_by_review_type"]["1"]["run_id"] == positive["run_id"]
    assert state["active_by_review_type"]["2"]["run_id"] == negative["run_id"]

    assert pipeline.collect_reviews(620, limit=1, review_type=1)["cache_used"]
    assert pipeline.collect_reviews(620, limit=1, review_type=2)["cache_used"]
    assert len(transport.requests) == 2


def test_opt_in_key_falls_back(pipeline, transport, monkeypatch, caplog):
    monkeypatch.setenv("STEAM_WEB_API_KEY", "test-secret")
    transport.queue += [http(403), page(review())]
    assert pipeline.collect_reviews(620, limit=1, use_key=True)["review_count"] == 1
    assert transport.requests[0][1]["X-webapi-key"] == "test-secret"
    assert not transport.requests[1][1]
    assert "test-secret" not in caplog.text


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_retry_and_retry_after(pipeline, transport, code):
    transport.queue += [http(code, {"Retry-After": "3"}), page(review())]
    assert pipeline.collect_reviews(620, limit=1)["last_attempt"]["requests"] == 2
    assert transport.sleeps == [3, 0.25]


@pytest.mark.parametrize("failure", [TimeoutError, lambda: URLError("offline"), lambda: http(429)])
def test_exhausted_retries(pipeline, transport, failure):
    transport.queue += [failure() for _ in range(4)]
    with pytest.raises(CollectionError):
        pipeline.collect_reviews(620)
    assert len(transport.requests) == 4
    assert pipeline.get_collection_status(620)["collection_status"] == "failed"
    assert transport.sleeps[::2] == [1, 2, 4]


@pytest.mark.parametrize("response", [b"not JSON", {}, {"response": {"reviews": [None]}}])
def test_bad_json_and_structure(pipeline, transport, response):
    transport.queue.append(response)
    with pytest.raises(CollectionError):
        pipeline.collect_reviews(620)
    assert pipeline.get_collection_status(620)["review_count"] == 0


def test_empty_game_and_invalid_app(pipeline, transport):
    transport.queue += [page(), page()]
    assert pipeline.collect_reviews(620)["review_count"] == 0
    assert pipeline.preprocess_reviews(620)["clean_rows"] == 0
    assert pipeline.get_processed_reviews(620).empty
    with pytest.raises(CollectionError, match="unverified"):
        pipeline.collect_reviews(99999)
    with pytest.raises(ValueError, match="positive"):
        pipeline.collect_reviews(-1)


@pytest.mark.parametrize("second,reason", [
    (page(review(2), cursor="next"), "repeated"),
    (page(review(2), cursor=None), "missing"),
    (page(review(), cursor="different"), "duplicate"),
])
def test_anomalous_pages_are_partial(pipeline, transport, second, reason):
    transport.queue += [page(review()), second]
    result = pipeline.collect_reviews(620, limit=3)
    assert result["collection_status"] == "partial"
    assert reason in result["error"]


def test_request_budget_checkpoints_and_resumes(pipeline, transport):
    transport.queue += [page(review(), cursor="save"), page(review(2))]
    first = pipeline.collect_reviews(620, limit=2, max_requests=1)
    assert first["collection_status"] == "partial"
    assert "budget" in first["error"]
    second = pipeline.collect_reviews(620, limit=2, max_requests=1)
    assert second["run_id"] == first["run_id"]
    assert second["collection_status"] == "complete"
    assert second["last_attempt"]["requests"] == 2
    assert json.loads(transport.requests[1][0]["input_json"][0])["cursor"] == "save"


def test_interrupt_keeps_checkpoint(pipeline, transport):
    transport.queue += [page(review()), KeyboardInterrupt(), page(review(2))]
    with pytest.raises(KeyboardInterrupt):
        pipeline.collect_reviews(620, limit=2)
    assert pipeline.get_collection_status(620)["collection_status"] == "partial"
    assert pipeline.collect_reviews(620, limit=2)["review_count"] == 2


def test_updated_duplicate_counts_only_once(pipeline, transport):
    transport.queue += [
        page(review(1, "old")), page(review(1, "new", timestamp_updated=1700000100), cursor="more"),
        page(review(2), cursor="tail"),
    ]
    result = pipeline.collect_reviews(620, limit=2)
    assert result["review_count"] == 2 and result["raw_count"] == 3
    pipeline.preprocess_reviews(620)
    frame = pipeline.get_processed_reviews(620)
    assert frame.loc[frame.review_id == "1", "review_text"].item() == "new"
