"""Synthetic provenance tests, independent of live Steam state."""
import json

import numpy as np
import pandas as pd
import pytest

from src.data_pipeline.metadata import json_safe, population
from src.data_pipeline.storage import read_json
from .conftest import page, review


def test_recent_sample_population_and_accounting(pipeline, transport):
    payload = page(review(1, voted_up=True), review(2), review(3, text=""))
    payload["response"].update(total_matching=100)
    payload["response"]["query_summary"].update(total_positive=80, total_negative=20, total_reviews=100)
    transport.queue.append(payload)
    frame, meta = pipeline.get_reviews(620, 3, False)
    assert len(frame) == 2
    assert meta["sampling"]["selected_ratios"]["positive"] == 0.5
    assert meta["sampling"]["matching_population"]["positive_ratio"] == 0.8
    assert not meta["sampling"]["is_population_representative"]
    quality = meta["data_quality"]
    assert quality["raw_received_count"] == quality["preprocessing_input_count"] == 3
    assert quality["preprocessing_excluded_count"] == quality["excluded_total_count"] == 1
    assert quality["preprocessing_excluded_by_reason"] == {"missing_text": 1}
    assert meta["review_period"]["actual_start_utc"].startswith("2023-11-14")
    assert meta["collection_finished_at_utc"] != meta["review_period"]["actual_start_utc"]
    json.dumps(meta, allow_nan=False)


@pytest.mark.parametrize("totals,expected", [
    ((80, 20, 100, 100), 0.8), ((0, 0, 0, 0), None),
    ((80, 20, 100, 90), None), ((80, None, 100, 100), None),
    ((80, 20, 101, 101), None),
])
def test_population_invalid_or_zero(totals, expected):
    positive, negative, total, matching = totals
    result, _, _ = population([{"total_matching": matching, "query_summary": {
        "total_positive": positive, "total_negative": negative, "total_reviews": total,
    }}])
    assert (result or {}).get("positive_ratio") == expected


def test_balanced_filter_mismatch_counts(pipeline, transport):
    positive = page(review(1, voted_up=True), review(2))
    negative = page(review(3), review(4))
    positive["response"]["total_matching"] = 800
    negative["response"]["total_matching"] = 200
    transport.queue += [positive, negative]
    frame, meta = pipeline.get_reviews(620, 4, False, "balanced")
    assert len(frame) == 3
    assert meta["sampling"]["selected_ratios"]["positive"] == pytest.approx(1 / 3)
    assert meta["sampling"]["matching_population"]["positive_ratio"] == 0.8
    quality = meta["data_quality"]
    assert quality["raw_received_count"] == 4
    assert quality["filter_mismatch_count"] == 1
    assert quality["preprocessing_input_count"] == 3
    assert quality["preprocessing_excluded_count"] == 0
    assert quality["excluded_total_count"] == 1
    before = meta["collection_finished_at_utc"]
    frame2, reused = pipeline.get_reviews(620, 4, False, "balanced")
    assert frame2.equals(frame) and reused["cache_used"]
    assert reused["collection_finished_at_utc"] == before


def test_duplicates_are_counted_at_the_stage_that_removes_them(pipeline, transport):
    transport.queue += [page(review(1), cursor="a"),
                        page(review(1, text="updated", timestamp_updated=1700000100), cursor="b"),
                        page(review(2))]
    frame, meta = pipeline.get_reviews(620, 2, False)
    quality = meta["data_quality"]
    assert len(frame) == 2
    assert quality["raw_received_count"] == quality["preprocessing_input_count"] == 3
    assert quality["unique_collected_count"] == 2
    assert quality["collection_duplicate_count"] == 0
    assert quality["preprocessing_excluded_by_reason"] == {"duplicate_id": 1}


def test_csv_does_not_invent_population_or_unknown_counts(pipeline, tmp_path):
    source = tmp_path / "source.csv"
    pd.DataFrame({"app_id": [620, 620], "review_text": ["Good game", "Not good"],
                  "voted_up": [True, False], "language": ["english"] * 2}).to_csv(source, index=False)
    pipeline.preprocess_csv(source)
    frame, meta = pipeline.get_reviews(620, 2, False)
    assert meta["sampling"]["matching_population"] is None
    assert meta["data_quality"]["raw_received_count"] is None
    assert meta["data_quality"]["preprocessing_excluded_count"] is None
    assert meta["source"] == "csv" and meta["cache_used"]


def test_json_safe_nested_non_native_types():
    assert json_safe({"a": np.int64(8), "b": [np.nan, np.inf, np.float64(0.25)]}) == {
        "a": 8, "b": [None, None, 0.25],
    }


def test_failed_refresh_metadata_refers_to_preserved_snapshot(pipeline, transport):
    from urllib.error import HTTPError
    from src.data_pipeline.collector import ENDPOINT
    transport.queue += [page(review(1), review(2)), HTTPError(ENDPOINT, 404, "test", None, None)]
    first, original = pipeline.get_reviews(620, 2, False)
    frame, meta = pipeline.get_reviews(620, 2, True)
    assert frame.equals(first)
    assert meta["collection_status"] == "failed" and meta["cache_used"]
    assert meta["data_quality"] == original["data_quality"]
    assert meta["collection_finished_at_utc"] == original["collection_finished_at_utc"]
    assert meta["latest_attempt"]["status"] == "failed"

def test_cross_label_ids_are_counted_once_in_unique_count(pipeline, transport):
    transport.queue += [page(review(1, voted_up=True)),
                        page(review(1, voted_up=False, timestamp_updated=1700000100))]
    frame, meta = pipeline.get_reviews(620, 2, False, "balanced")
    quality = meta["data_quality"]
    assert quality["raw_received_count"] == 2 and quality["unique_collected_count"] == 1
    assert quality["preprocessing_excluded_by_reason"] == {"duplicate_id": 1}
    assert quality["accounting_verified"] and len(frame) == 1
