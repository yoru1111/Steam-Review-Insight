"""The live command is tested with synthetic data here. Network access is opt-in."""
import json

from src.data_pipeline.live_validation import validate_games
from .conftest import page, review
from .test_game_details import PublicResponses, details_payload
from .test_rankings import PLAYERS


def test_twenty_game_command_and_general_cache_preservation(pipeline, transport):
    identifiers = list(range(1000, 1020))
    table = "<table>" + "".join(
        f'<tr><td>{rank}</td><td><a href="https://store.steampowered.com/app/{identifier}/">Mock game {rank}</a></td>'
        "<td>Free</td><td>0</td><td>1</td></tr>"
        for rank, identifier in enumerate(identifiers, start=1)
    ) + "</table>"
    replies = PublicResponses(table, PLAYERS)
    for identifier in identifiers:
        replies.responses += [details_payload(identifier, name=f"Mock game {identifier}"), b""]
    pipeline.public_client = replies.client()
    transport.queue += [page(review(number)) for number in identifiers[:-1]] + [page()]
    existing = pipeline.root / "data/raw/steam/620/state.json"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"Existing general-cache marker")
    report = validate_games(pipeline)
    assert report["test_type"] == "live_steam"  # Command mode, transport is synthetic in this test.
    assert report["metadata_successes"] == report["review_api_successes"] == 20
    assert report["games_with_reviews"] == 19 and report["valid_images"] == 20
    assert report["complete_details"] == 20
    assert len(transport.requests) == 20
    assert existing.read_bytes() == b"Existing general-cache marker"
    report_text = (pipeline.root / "reports/game_metadata_20_validation.json").read_text(encoding="utf-8")
    assert "steamid" not in report_text and "review_text" not in report_text
    assert len(list((pipeline.root / "data/raw/connection_validation").glob("*/*.json"))) == 20
    json.dumps(report, allow_nan=False)
