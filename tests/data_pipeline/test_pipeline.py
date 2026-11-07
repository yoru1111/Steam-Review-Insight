from pathlib import Path
from urllib.error import HTTPError

import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from src.data_pipeline.cli import main
from src.data_pipeline.collector import ENDPOINT
from src.data_pipeline.schema import COLUMNS
from src.data_pipeline.service import EXPORT
from src.data_pipeline.storage import read_json

from .conftest import page, review

FIXTURES = Path(__file__).parent / "fixtures"


def test_csv_cli_mapping_and_reproducible_output(tmp_path):
    argv = ["--root", str(tmp_path), "preprocess", "--input", str(FIXTURES / "mock_reviews.csv"),
            "--mapping", str(FIXTURES / "mock_mapping.json"), "--dataset", "SYNTHETIC TEST ONLY"]
    assert main(argv) == 0
    path = tmp_path / "data/processed" / EXPORT
    before = path.read_bytes()
    assert before.startswith(b"\xef\xbb\xbf")
    report = read_json(tmp_path / "reports/quality_report.json")
    assert report["context"]["source"] == "csv" and report["steam_api"] is None
    assert report["passed"]
    assert report["input_rows"] == 8 and report["clean_rows"] == 3 and report["removed_rows"] == 5
    assert report["by_game"] == {"620": 2, "400": 1}
    assert report["labels"]["positive"] == 2 and report["labels"]["negative"] == 1
    assert report["removed_by_reason"] == {
        "duplicate_id": 1, "unknown_language": 1, "other_language": 1, "missing_text": 1, "missing_label": 1,
    }
    assert "Masked examples" in (tmp_path / "reports/quality_report.md").read_text(encoding="utf-8")
    assert main(argv) == 0 and path.read_bytes() == before
    assert main(["--root", str(tmp_path), "validate"]) == 0
    df = pd.read_csv(path)
    assert tuple(df.columns) == COLUMNS and df.shape == (3, len(COLUMNS))
    assert df["sentiment"].tolist() == [0, 1, 1]
    assert df.iloc[0]["created_at_utc"] == "2026-01-01T00:00:00.000000+00:00"
    assert df.iloc[0]["playtime_at_review_minutes"] == 15
    assert df.iloc[0]["playtime_forever_minutes"] == 90
    assert TfidfVectorizer().fit_transform(df["review_clean"]).shape[0] == 3


def test_missing_columns_and_csv_rows_without_ids(pipeline, tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("text,vote\nGood game,yes\nGood game,yes\n", encoding="utf-8")
    mapping = {"review_text": "text", "voted_up": "vote"}
    with pytest.raises(ValueError, match="Missing required CSV fields: app_id"):
        pipeline.preprocess_csv(input_path, mapping)
    result = pipeline.preprocess_csv(input_path, mapping, game_id=7)
    assert result["clean_rows"] == 0
    assert result["raw_language_counts"] == {"unknown": 2}
    pipeline.preprocess_csv(input_path, mapping, game_id=7, declared_language="en")
    rows = pipeline.get_processed_reviews(7)
    assert rows["game_name"].isna().all()
    assert rows["review_id"].str.startswith("csv-").all()
    assert rows["review_id"].nunique() == 2


def test_game_search_selection_separation_and_cache(pipeline, transport):
    assert pipeline.search_games("pOrTaL") == [{"app_id": 400, "name": "Portal"},
                                               {"app_id": 620, "name": "Portal 2"}]
    assert pipeline.search_games("imaginary title") == []
    transport.queue += [page(review(1, "a bug that causes lag")), page(review(1, "balance fix"))]
    first, second = pipeline.search_games("portal")
    df, fresh = pipeline.get_reviews(first["app_id"], 1, False)
    other, _ = pipeline.get_reviews(second["app_id"], 1, False)
    assert df["app_id"].tolist() == [400] and other["app_id"].tolist() == [620]
    assert len(df[df["review_clean"].str.contains("bug", regex=False)]) == 1
    assert not other["review_clean"].str.contains("bug", regex=False).any()
    assert not fresh["cache_used"] and fresh["preprocessing_success"]
    assert fresh["data_source"] == fresh["source"] == "api"
    reused, metadata = pipeline.get_reviews(400, 1, False)
    assert reused.equals(df) and metadata["cache_used"]
    assert len(transport.requests) == 2
    assert tuple(other.columns) == tuple(df.columns) == COLUMNS


def test_refresh_failure_and_empty_refresh_keep_known_data(pipeline, transport):
    transport.queue += [page(review()), HTTPError(ENDPOINT, 404, "test", None, None), page()]
    first, status = pipeline.get_reviews(620, 1, False)
    stale, fallback = pipeline.get_reviews(620, 1, True)
    assert stale.equals(first) and fallback["cache_used"]
    assert fallback["run_id"] == status["run_id"]
    assert fallback["collection_status"] == "failed" and fallback["error"] == "Steam HTTP 404"
    still_available, empty_attempt = pipeline.get_reviews(620, 1, True)
    assert still_available.equals(first) and empty_attempt["cache_used"]
    assert pipeline.get_collection_status(620)["last_attempt"]["review_count"] == 0


def test_offline_csv_fallback_is_typed(pipeline, transport):
    pipeline.preprocess_csv(FIXTURES / "mock_reviews.csv", read_json(FIXTURES / "mock_mapping.json"))
    cached, status = pipeline.get_reviews(620, 2, False)
    assert status["source"] == "csv" and status["cache_used"] and not transport.requests
    transport.queue += [HTTPError(ENDPOINT, 404, "test", None, None)]
    frame, result = pipeline.get_reviews(620, 5, True)
    assert frame.equals(cached) and tuple(frame.columns) == COLUMNS
    assert result["data_source"] == result["source"] == "csv" and result["cache_used"]
    assert result["error"] == "Steam HTTP 404"
    assert frame["steam_purchase"].isna().all()
