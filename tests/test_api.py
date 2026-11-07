from fastapi.testclient import TestClient

from backend.data_adapter import UnavailableDataAdapter, create_default_adapter
from backend.main import app, create_app
from src.data_pipeline import ReviewPipeline


class MockAdapter:
    def __init__(self, frame):
        self.frame = frame

    def search_games(self, query):
        return [{"app_id": 999, "name": "Fixture Game"}]

    def get_reviews(self, app_id, limit, refresh, sample_mode="recent"):
        return self.frame.head(limit), {"game_name": "Fixture Game", "cache_used": not refresh,
                                        "data_source": "mock", "sample_mode": sample_mode,
                                        "sampling": ({"mode": "balanced", "is_population_representative": False}
                                                     if sample_mode == "balanced" else None)}


def test_health():
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["status"] == "ok"


def test_search_and_analyze(reviews_df):
    with TestClient(create_app(MockAdapter(reviews_df))) as client:
        assert client.get("/api/games/search", params={"query": "fixture"}).status_code == 200
        response = client.post("/api/analyze", json={"app_id": 999, "limit": 12, "k": 4, "refresh": False})
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["cache_used"] is True


def test_analyze_accepts_balanced_sample_mode(reviews_df):
    with TestClient(create_app(MockAdapter(reviews_df))) as client:
        response = client.post(
            "/api/analyze",
            json={"app_id": 999, "limit": 12, "k": 4, "sample_mode": "balanced"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["sample_mode"] == "balanced"
    assert response.json()["metadata"]["sampling"]["is_population_representative"] is False


def test_invalid_app_id():
    with TestClient(create_app()) as client:
        assert client.post("/api/analyze", json={"app_id": 0}).status_code == 422


def test_unconnected_adapter_and_status():
    with TestClient(create_app(UnavailableDataAdapter())) as client:
        assert client.get("/api/games/search", params={"query": "game"}).status_code == 503
        assert client.post("/api/analyze", json={"app_id": 10}).status_code == 503
        assert client.get("/api/analyze/status/not-real").status_code == 501


def test_default_app_uses_data_pipeline_for_game_search():
    assert create_default_adapter().__class__ is ReviewPipeline
    with TestClient(app) as client:
        response = client.get("/api/games/search", params={"query": "portal"})
        assert response.status_code == 200
        assert response.json()["games"] == [
            {"app_id": 400, "name": "Portal"},
            {"app_id": 620, "name": "Portal 2"},
        ]


def test_preprocessed_reviews_flow_through_fastapi_analysis(tmp_path, reviews_df):
    source = tmp_path / "reviews.csv"
    reviews_df.assign(app_id=620, game_name="Portal 2").to_csv(source, index=False)
    pipeline = ReviewPipeline(tmp_path)
    result = pipeline.preprocess_csv(source)
    assert result["clean_rows"] == len(reviews_df)

    with TestClient(create_app(pipeline)) as client:
        response = client.post(
            "/api/analyze",
            json={"app_id": 620, "limit": len(reviews_df), "k": 4, "refresh": False},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["review_count"] == len(reviews_df)
    assert payload["metadata"]["data_source"] == "csv"
    assert payload["clustering"]["requested_k"] == 4
