from fastapi.testclient import TestClient

from backend.data_adapter import UnavailableDataAdapter
from backend.main import create_app


class MockAdapter:
    def __init__(self, frame):
        self.frame = frame

    def search_games(self, query):
        return [{"app_id": 999, "name": "Fixture Game"}]

    def get_reviews(self, app_id, limit, refresh):
        return self.frame.head(limit), {"game_name": "Fixture Game", "cache_used": not refresh,
                                        "data_source": "mock"}


def test_health():
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["status"] == "ok"


def test_search_and_analyze(reviews_df):
    with TestClient(create_app(MockAdapter(reviews_df))) as client:
        assert client.get("/api/games/search", params={"query": "fixture"}).status_code == 200
        response = client.post("/api/analyze", json={"app_id": 999, "limit": 12, "k": 4, "refresh": False})
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["cache_used"] is True


def test_invalid_app_id():
    with TestClient(create_app()) as client:
        assert client.post("/api/analyze", json={"app_id": 0}).status_code == 422


def test_unconnected_adapter_and_status():
    with TestClient(create_app(UnavailableDataAdapter())) as client:
        assert client.get("/api/games/search", params={"query": "game"}).status_code == 503
        assert client.post("/api/analyze", json={"app_id": 10}).status_code == 503
        assert client.get("/api/analyze/status/not-real").status_code == 501


def test_frontend_served_without_shadowing_api():
    with TestClient(create_app()) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Steam Review Insight" in page.text
        assert client.get("/app.js").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/docs").status_code == 200
