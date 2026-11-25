"""Calendar, API-boundary and isolated snapshot regression tests using synthetic reviews."""
from datetime import datetime, timezone
import json
from urllib.error import HTTPError

import pytest

from src.data_pipeline.collector import ENDPOINT, request_parameters
from src.data_pipeline.comparison import comparison_windows, utc_second
from .conftest import page, review


def at(identifier, value, **kwargs):
    seconds = int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
    return review(identifier, timestamp_created=seconds, **kwargs)


@pytest.mark.parametrize("day,days", [
    ("2026-11-01", 7), ("2026-11-01", 14), ("2026-11-01", 30),
    ("2026-01-01", 7), ("2024-03-01", 1), ("2026-02-01", 14),
])
def test_calendar_and_timezone(day, days):
    start, boundary, end = comparison_windows(day, days)
    assert (boundary - start).days == (end - boundary).days == days
    assert boundary.hour == 15
    assert boundary.tzinfo == timezone.utc
    if day == "2024-03-01":
        assert start.isoformat().startswith("2024-02-28T15")


@pytest.mark.parametrize("day,zone", [("bad", "Asia/Seoul"), ("2026-02-30", "UTC"),
                                     ("2026-01-01", "Unknown/Nowhere")])
def test_bad_calendar(day, zone):
    with pytest.raises(ValueError):
        comparison_windows(day, timezone=zone)


@pytest.mark.parametrize("value", ["2026-01-01", "2026-01-01T00:00:00.5Z", None, -1])
def test_bad_utc_boundary(value):
    with pytest.raises(ValueError):
        utc_second(value)


def test_inclusive_api_end():
    params = json.loads(request_parameters(620, period=(100, 200))["input_json"])
    assert params["date_range_start"] == 100 and params["date_range_end"] == 199


def test_comparison_success_and_query_cache_isolation(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30"), at(2, "2026-10-31")),
                        page(at(3, "2026-11-02"), at(4, "2026-11-03"))]
    result = pipeline.get_comparison_reviews(620, "2026-11-01", window_days=7,
                                             limit_per_period=2, minimum_required_count=2)
    assert result.status == "complete" and result.comparison_ready and result.comparable_conditions
    assert not set(result.before.frame.review_id) & set(result.after.frame.review_id)
    assert result.before.metadata["query_hash"] != result.after.metadata["query_hash"]
    assert not (pipeline.root / "data/raw/steam/620/state.json").exists()
    assert not (pipeline.root / "data/processed/games/620/current.json").exists()
    for params, _ in transport.requests:
        request = json.loads(params["input_json"][0])
        assert request["languages"] == ["english"] and request["filter"] == 1
        assert request["date_range_start"] < request["date_range_end"]
    reused = pipeline.get_comparison_reviews(620, "2026-11-01", window_days=7,
                                             limit_per_period=2, minimum_required_count=2)
    assert reused.before.metadata["cache_used"] and reused.after.metadata["cache_used"]
    assert len(transport.requests) == 2
    json.dumps(result.summary(), allow_nan=False)


def test_period_postvalidates_dates_language_and_app(pipeline, transport):
    transport.queue += [page(
        at(1, "2026-10-31"), at(2, "2026-11-01"),
        review(3, timestamp_created=None), at(4, "2026-10-30", language="french"),
        at(5, "2026-10-30", appid=400),
    )]
    result = pipeline.collect_reviews_by_period(
        620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z", limit=5, minimum_required_count=1,
    )
    assert result.frame.review_id.tolist() == ["1"]
    removed = result.metadata["data_quality"]["preprocessing_excluded_by_reason"]
    assert removed == {"outside_requested_period": 1, "invalid_timestamp_for_period": 1,
                       "other_language": 1, "invalid_app_id": 1}
    assert result.metadata["status"] == "partial" and not result.metadata["comparison_ready"]


@pytest.mark.parametrize("amount,minimum,expected", [(0, 1, "empty"), (1, 2, "insufficient_data"), (2, 2, "complete")])
def test_shortages(pipeline, transport, amount, minimum, expected):
    transport.queue.append(page(*(at(n + 1, "2026-10-30") for n in range(amount))))
    if amount == 1:
        transport.queue.append(page())
    result = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z",
                                                limit=2, minimum_required_count=minimum)
    assert result.metadata["status"] == expected
    assert result.metadata["missing_count"] == 2 - amount
    assert result.metadata["comparison_ready"] == (expected == "complete")


def test_future_period_is_not_marked_complete(pipeline, transport):
    transport.queue.append(page(at(1, "2090-01-01"), at(2, "2090-01-02")))
    result = pipeline.collect_reviews_by_period(620, "2090-01-01T00:00:00Z", "2090-02-01T00:00:00Z",
                                                limit=2, minimum_required_count=1)
    assert result.metadata["status"] == "period_incomplete"
    assert not result.metadata["comparison_ready"]


@pytest.mark.parametrize("code", [429, 500])
def test_partial_and_retry(pipeline, transport, code):
    transport.queue += [page(at(1, "2026-10-30"))]
    transport.queue += [HTTPError(ENDPOINT, code, "test", {"Retry-After": "0"}, None) for _ in range(4)]
    result = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z",
                                                limit=2, minimum_required_count=1)
    assert len(result.frame) == 1 and result.metadata["status"] == "partial"
    assert not result.metadata["comparison_ready"]


def test_balanced_period_and_distinct_mode_cache(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30", voted_up=True)), page(at(2, "2026-10-30"))]
    result = pipeline.collect_reviews_by_period(
        620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z",
        limit=2, sample_mode="balanced", minimum_required_count=2,
    )
    assert result.metadata["status"] == "complete"
    assert result.metadata["sampling"]["selected_counts"] == {"positive": 1, "negative": 1}
    requests = [json.loads(params["input_json"][0]) for params, _ in transport.requests]
    assert [item["review_type"] for item in requests] == [1, 2]
    assert requests[0]["date_range_start"] == requests[1]["date_range_start"]
    transport.queue += [page(at(3, "2026-10-30"), at(4, "2026-10-30"))]
    recent = pipeline.collect_reviews_by_period(
        620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z", limit=2, minimum_required_count=2,
    )
    assert result.metadata["query_hash"] != recent.metadata["query_hash"]


def test_refresh_failure_preserves_period_cache(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30"), at(2, "2026-10-30"))]
    options = dict(limit=2, minimum_required_count=1)
    first = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z", **options)
    transport.queue += [HTTPError(ENDPOINT, 404, "test", None, None)]
    stale = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z",
                                              refresh=True, **options)
    assert stale.frame.equals(first.frame) and stale.metadata["cache_used"]
    assert stale.metadata["status"] == "partial"
    assert stale.metadata["collection_finished_at_utc"] == first.metadata["collection_finished_at_utc"]

def test_cross_period_conflicting_ids_are_removed(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30"), at(2, "2026-10-30")),
                        page(at(1, "2026-11-02"), at(3, "2026-11-02"))]
    result = pipeline.get_comparison_reviews(620, "2026-11-01", window_days=7,
                                             limit_per_period=2, minimum_required_count=1)
    assert result.status == "partial" and not result.comparison_ready
    assert result.before.frame.review_id.tolist() == ["2"]
    assert result.after.frame.review_id.tolist() == ["3"]
    for side in (result.before, result.after):
        assert side.metadata["data_quality"]["comparison_excluded_count"] == 1
        assert side.metadata["data_quality"]["analyzed_review_count"] == 1
        assert not side.metadata["comparable_conditions"]


def test_fulfilled_target_below_minimum_is_insufficient(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30"), at(2, "2026-10-30"))]
    result = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z", limit=2)
    assert result.metadata["status"] == "insufficient_data"
    assert not result.metadata["comparison_ready"]
    assert result.metadata["minimum_missing_count"] == 28


def test_same_calendar_days_across_dst_are_flagged(pipeline, transport):
    transport.queue += [page(), page()]
    result = pipeline.get_comparison_reviews(620, "2026-03-08", window_days=1,
                                             timezone="America/New_York", limit_per_period=2)
    assert not result.conditions["equal_elapsed_duration"]
    assert not result.comparable_conditions and not result.comparison_ready
    assert result.status == "partial"


def test_limited_comparison_can_be_ready(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30")), page(),
                        page(at(2, "2026-11-02")), page()]
    result = pipeline.get_comparison_reviews(620, "2026-11-01", window_days=7,
                                             limit_per_period=2, minimum_required_count=1)
    assert result.status == "insufficient_data" and result.comparison_ready
    assert result.before.metadata["missing_count"] == result.after.metadata["missing_count"] == 1


def test_failed_period_has_no_invented_counts(pipeline, transport):
    transport.queue += [HTTPError(ENDPOINT, 404, "test", None, None)]
    result = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z", limit=2)
    assert result.frame.empty and result.metadata["status"] == "failed"
    assert result.metadata["data_quality"] is None and result.metadata["collected_count"] is None


def test_query_count_language_and_policy_are_isolated(pipeline):
    from src.data_pipeline.comparison import PeriodPipeline
    start, _, end = comparison_windows("2026-11-01", 7)
    queries = [PeriodPipeline(pipeline, 620, start, end, language, count, mode)
               for language, count, mode in [("english", 10, "recent"), ("english", 20, "recent"),
                                              ("english", 10, "balanced"), ("german", 10, "recent")]]
    assert len({query.query_hash for query in queries}) == 4
    assert all(query.query["preprocessing_policy_version"] for query in queries)


def test_balanced_one_label_failure_keeps_other_label_data(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30", voted_up=True), at(2, "2026-10-30", voted_up=True)),
                        HTTPError(ENDPOINT, 404, "test", None, None)]
    result = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z",
                                                limit=4, sample_mode="balanced", minimum_required_count=1)
    assert result.metadata["status"] == "partial" and len(result.frame) == 2
    assert result.metadata["sampling"]["matching_population"] is None
    assert result.metadata["data_quality"]["accounting_verified"]
    assert result.metadata["data_quality"]["raw_received_count"] == 2


def test_balanced_partial_label_survives_next_label_checkpoint(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30", voted_up=True)), HTTPError(ENDPOINT, 404, "test", None, None),
                        page(at(2, "2026-10-30"), at(3, "2026-10-30"))]
    result = pipeline.collect_reviews_by_period(620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z",
                                                limit=4, sample_mode="balanced", minimum_required_count=1)
    assert result.metadata["status"] == "partial" and len(result.frame) == 3
    assert result.metadata["sampling"]["selected_counts"] == {"positive": 1, "negative": 2}
    assert result.metadata["data_quality"]["accounting_verified"]


def test_balanced_invalid_text_refresh_keeps_previous_snapshot(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30", voted_up=True)), page(at(2, "2026-10-30"))]
    args = (620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z")
    options = dict(limit=2, sample_mode="balanced", minimum_required_count=1)
    original = pipeline.collect_reviews_by_period(*args, **options)
    transport.queue += [page(at(3, "2026-10-30", voted_up=True, text="")),
                        page(at(4, "2026-10-30", text=""))]
    refreshed = pipeline.collect_reviews_by_period(*args, refresh=True, **options)
    assert refreshed.frame.equals(original.frame) and refreshed.metadata["cache_used"]
    assert refreshed.metadata["status"] == "partial" and not refreshed.metadata["preprocessing_success"]
    assert refreshed.metadata["data_quality"] == original.metadata["data_quality"]


def test_resumed_balanced_run_reprocesses_added_pages(pipeline, transport):
    transport.queue += [page(at(1, "2026-10-30", voted_up=True)), HTTPError(ENDPOINT, 404, "test", None, None),
                        page(at(2, "2026-10-30"), at(3, "2026-10-30"))]
    args = (620, "2026-10-25T00:00:00Z", "2026-11-01T00:00:00Z")
    options = dict(limit=4, sample_mode="balanced", minimum_required_count=1)
    partial = pipeline.collect_reviews_by_period(*args, **options)
    transport.queue += [page(at(4, "2026-10-30", voted_up=True))]
    resumed = pipeline.collect_reviews_by_period(*args, **options)
    assert len(partial.frame) == 3 and len(resumed.frame) == 4
    assert resumed.metadata["status"] == "complete"
    assert partial.metadata["query_hash"] == resumed.metadata["query_hash"]
    assert json.loads(transport.requests[-1][0]["input_json"][0])["cursor"] == "next"
    assert len(transport.requests) == 4
