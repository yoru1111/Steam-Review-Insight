import json

from fastapi.testclient import TestClient

from backend.main import create_app
from src.analysis import AnalysisConfig, analyze_reviews
from .conftest import page, review
from .test_game_details import PublicResponses, details_payload


def test_details_api_and_existing_search(pipeline):
    pipeline.public_client = PublicResponses(details_payload()).client()
    with TestClient(create_app(pipeline)) as client:
        response = client.get("/api/games/details/620")
        assert response.status_code == 200 and response.json()["name"] == "Portal 2"
        assert client.get("/api/games/details/-1").status_code == 422
        assert client.get("/api/games/search", params={"query": "portal"}).status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/app.js").status_code == 200
        assert client.get("/api/health").status_code == 200


def test_compare_api_returns_only_summary(pipeline, transport):
    from .test_comparison import at
    transport.queue += [page(at(1, "2026-10-30"), at(2, "2026-10-31")),
                        page(at(3, "2026-11-02"), at(4, "2026-11-03"))]
    with TestClient(create_app(pipeline)) as client:
        result = client.post("/api/reviews/compare", json={
            "app_id": 620, "reference_date": "2026-11-01", "window_days": 7,
            "limit_per_period": 2, "minimum_required_count": 2,
        })
        assert result.status_code == 200, result.text
        assert result.json()["comparison_ready"]
        assert "frame" not in result.json()["before"]
        assert "review_text" not in result.text
        assert client.post("/api/reviews/compare", json={
            "app_id": 620, "reference_date": "2026-02-30",
        }).status_code == 422
        assert client.post("/api/reviews/compare", json={
            "app_id": 620, "reference_date": "2026-11-01", "timezone": "Invalid/Zone",
        }).status_code == 422


def test_popular_api(pipeline):
    from .test_rankings import SELLERS
    pipeline.public_client = PublicResponses(SELLERS, details_payload()).client()
    with TestClient(create_app(pipeline)) as client:
        response = client.get("/api/games/popular", params={"type": "top_sellers", "limit": 1})
        assert response.status_code == 200
        assert response.json()["games"][0]["header_image"]
        assert response.json()["ranking_metric"] == "revenue"
        assert client.get("/api/games/popular", params={"type": "sales_units"}).status_code == 422


def test_analysis_forwards_metadata_without_changing_outputs(reviews_df):
    metadata = {
        "sample_mode": "balanced", "sampling": {"selected_ratios": {"positive": 0.5},
        "matching_population": {"positive_ratio": 0.8}, "is_population_representative": False},
        "data_quality": {"analyzed_review_count": len(reviews_df), "preprocessing_excluded_count": 3},
        "review_period": {"requested_start_utc": None, "actual_start_utc": "2026-01-01"},
        "warnings": ["Synthetic provenance warning"],
    }
    result = analyze_reviews(reviews_df, metadata=metadata)
    assert result["metadata"]["data_quality"] == metadata["data_quality"]
    assert result["metadata"]["sampling"]["matching_population"]["positive_ratio"] == 0.8
    assert "Synthetic provenance warning" in result["warnings"]
    assert {"summary", "sentiment", "clustering", "clusters", "priorities", "positive_aspects"} <= result.keys()
    json.dumps(result, allow_nan=False)
