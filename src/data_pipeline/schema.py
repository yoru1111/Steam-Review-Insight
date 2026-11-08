"""Types and normalization shared by Steam and offline CSV records."""
from datetime import datetime, timezone
import math
import re

INTEGER_FIELDS = (
    "playtime_at_review_minutes", "playtime_forever_minutes", "votes_up", "votes_funny"
)
BOOLEAN_FIELDS = ("steam_purchase", "received_for_free", "written_during_early_access", "refunded")
TIME_FIELDS = ("created_at_utc", "updated_at_utc")
COLUMNS = (
    "source", "app_id", "review_id", "review_text", "review_clean", "language", "voted_up",
    "sentiment", *TIME_FIELDS, "text_length", "word_count", "game_name",
    *INTEGER_FIELDS, "weighted_vote_score", *BOOLEAN_FIELDS,
)


def uint(value, maximum=2**64 - 1):
    if type(value) is int:
        return value if 0 <= value <= maximum else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value.strip()):
        return uint(int(value), maximum)
    return None


def app_id(value):
    return uint(value, 2**32 - 1) or None


def review_id(value):
    if number := uint(value):
        return str(number)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value.strip()):
        if not value.strip().isdecimal():
            return value.strip()
    return None


def boolean(value):
    if type(value) is bool:
        return value
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        token = str(value).strip().casefold()
        if token in {"true", "1", "yes", "recommended"}:
            return True
        if token in {"false", "0", "no", "not recommended"}:
            return False
    return None


def timestamp(value):
    try:
        if (seconds := uint(value, 2**32 - 1)) is not None:
            parsed = datetime.fromtimestamp(seconds, timezone.utc)
        elif isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value.strip()):
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            return None
        return (parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
                .astimezone(timezone.utc).isoformat(timespec="microseconds"))
    except (ValueError, OverflowError, OSError):
        return None


def finite_float(value):
    try:
        number = float(value) if not isinstance(value, bool) else None
        return number if number is not None and math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def language_code(value):
    if isinstance(value, str):
        value = value.strip().casefold()
        if value in {"en", "en-us", "en-gb"}:
            return "english"
        if re.fullmatch(r"[a-z]{2,24}(?:[-_][a-z]{2,12})?", value):
            return value
    return "unknown"


def api_row(review, game_id, game_name):
    author = review.get("author")
    author = author if isinstance(author, dict) else {}
    return {
        "source": "api", "app_id": game_id, "game_name": game_name,
        "review_id": review.get("recommendationid"), "review_text": review.get("review"),
        "language": review.get("language"), "voted_up": review.get("voted_up"),
        "created_at_utc": review.get("timestamp_created"),
        "updated_at_utc": review.get("timestamp_updated"),
        "playtime_at_review_minutes": author.get("playtime_at_review"),
        "playtime_forever_minutes": author.get("playtime_forever"),
        **{field: review.get(field) for field in (*INTEGER_FIELDS[2:], "weighted_vote_score", *BOOLEAN_FIELDS)},
    }
