"""All mock API and CSV tests use isolated, synthetic data."""
import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.data_pipeline.collector import SteamClient
from src.data_pipeline.service import ReviewPipeline


def review(number=1, text="Not good at 60 FPS", **fields):
    return {
        "recommendationid": str(number), "review": text, "language": "english",
        "voted_up": False, "timestamp_created": 1700000000, "timestamp_updated": 1700000001,
        "author": {"steamid": "76561198000000000", "playtime_at_review": 10, "playtime_forever": 45},
        **fields,
    }


def page(*reviews, cursor="next"):
    return {"response": {"reviews": list(reviews), "cursor": cursor,
                         "query_summary": {"num_reviews": len(reviews)}, "total_matching": len(reviews)}}


class Responses:
    def __init__(self):
        self.queue = []
        self.requests = []
        self.sleeps = []

    def open(self, request, timeout):
        params = parse_qs(urlsplit(request.full_url).query)
        self.requests.append((params, dict(request.header_items())))
        response = self.queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        return io.BytesIO(response if isinstance(response, bytes) else json.dumps(response).encode())

    def client(self, **kwargs):
        return SteamClient(opener=self.open, sleep=self.sleeps.append, delay=0.25, **kwargs)


@pytest.fixture
def transport():
    return Responses()


@pytest.fixture
def pipeline(tmp_path, transport):
    return ReviewPipeline(tmp_path, client_factory=transport.client)
