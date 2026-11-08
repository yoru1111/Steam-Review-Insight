import pytest

from src.data_pipeline.preprocessing import normalize, prepare
from src.data_pipeline.schema import api_row, boolean, timestamp
from src.data_pipeline.validation import validate_records

from .conftest import review


def test_normalization_and_privacy():
    original, clean = normalize(
        "<b>Ｎｏｔ good</b> &amp; I can’t, won’t, and don't. Never! No. "
        "\nRTX 3070 / 60 FPS / 1.2.3, bug, crash, lag, stutter, balance, pay to win 😃 :D "
        "https://example.test/a user@example.test 76561198000000000 010-1234-5678 "
        "\x00 &lt;script&gt;ignore me&lt;/script&gt;"
    )
    assert "Not good & I can’t" in original
    assert "not good & i can't, won't, and don't. never! no." in clean
    assert "rtx 3070 / 60 fps / 1.2.3, bug, crash, lag, stutter, balance, pay to win 😃 :d" in clean
    assert "[url] [email] [steam_id] [phone]" in clean
    assert all(token not in original for token in ("example.test", "76561198000000000", "ignore me", "<b>"))


@pytest.mark.parametrize("token,expected", [
    (True, True), (False, False), ("TRUE", True), ("False", False), (1, True), (0, False),
    ("recommended", True), ("not recommended", False), ("2", None), (None, None), (0.0, None),
])
def test_boolean(token, expected):
    assert boolean(token) is expected


def test_utc_timestamp():
    assert timestamp(1700000000) == "2023-11-14T22:13:20.000000+00:00"
    assert timestamp("2026-01-01T09:00:00+09:00") == "2026-01-01T00:00:00.000000+00:00"
    assert timestamp("2026-01-01") == "2026-01-01T00:00:00.000000+00:00"
    assert timestamp("2026-02-31") is timestamp(None) is None


def test_removal_reasons_and_no_text_only_dedup():
    rows = [api_row(item, 620, None) for item in (
        review(1, None), review(2, "   "), review(3, 10), review(4, "<br>"),
        review(5, "no label", voted_up=None), review(6, "bad label", voted_up="maybe"),
        review(7, language=None), review(8, language="german"), review(9, timestamp_created="wrong"),
        review(10), review(0),
    )]
    rows.append(api_row(review(10), 400, None))
    records, stats, removed, languages, _ = prepare(rows, {})
    assert [r["review_id"] for r in records] == ["9", "10", "10"]
    assert records[0]["created_at_utc"] is None
    assert stats["invalid_created_at_utc"] == stats["invalid_review_id"] == 1
    assert removed == {
        "missing_text": 2, "invalid_text_type": 1, "empty_after_normalization": 1,
        "missing_label": 1, "invalid_label": 1, "unknown_language": 1, "other_language": 1,
        "invalid_review_id": 1,
    }
    assert languages == {"english": 10, "german": 1, "unknown": 1}
    assert all(validate_records(records).values())
