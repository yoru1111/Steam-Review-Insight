"""Privacy-aware, deterministic text cleaning and review selection."""
from collections import Counter
from html import unescape
from html.parser import HTMLParser
import logging
import re
import unicodedata

from .schema import (
    BOOLEAN_FIELDS, INTEGER_FIELDS, TIME_FIELDS, app_id, boolean, finite_float,
    language_code, review_id, timestamp, uint,
)

LOG = logging.getLogger(__name__)
EMAIL = re.compile(r"[\w.+%-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)
URL = re.compile(r"(?:https?://|ftp://|www\.|steamcommunity\.com/(?:id|profiles)/)[^\s<>]+", re.IGNORECASE)
STEAM_ID = re.compile(r"\b7656119[0-9]{10}\b|\bSTEAM_[0-5]:[01]:[0-9]+\b|\[U:1:[0-9]+\]", re.IGNORECASE)
IP = re.compile(r"\b(?:(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]?|0)\.){3}"
                r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]?|0)\b")
PHONE = re.compile(
    r"(?<!\w)(?:\+[1-9][0-9]{0,2}[ -]?)?(?:\([0-9]{3}\)|[0-9]{3})[ -][0-9]{3}[ -][0-9]{4}(?!\w)"
    r"|(?<!\w)(?:\+82[ -]?10|010)[ -]?[0-9]{4}[ -]?[0-9]{4}(?!\w)"
)


class ReviewHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.hidden = None

    def handle_starttag(self, tag, attrs):
        if not self.hidden:
            if tag in {"script", "style"}:
                self.hidden = tag
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None
        if not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def mask(text):
    for pattern, placeholder in (
        (URL, "[URL]"), (EMAIL, "[EMAIL]"), (STEAM_ID, "[STEAM_ID]"),
        (PHONE, "[PHONE]"), (IP, "[IP]"),
    ):
        text = pattern.sub(placeholder, text)
    return text


def normalize(text):
    canonical = unicodedata.normalize("NFKC", unescape(text))
    parser = ReviewHTML()
    parser.feed(canonical)
    parser.close()
    visible = "".join(parser.parts)
    # Retain zero-width joiners for compound emoji, while removing bidi/control characters.
    visible = "".join(
        " " if char.isspace() else char
        for char in visible
        if char.isspace() or char == "\u200d" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )
    original = " ".join(mask(visible).split())
    clean = original.lower().replace("’", "'").replace("‘", "'")
    return original, clean


def prepare(rows, catalog, *, language="english"):
    stats = Counter()
    removed = Counter()
    languages = Counter()
    selected = {}
    for raw in rows:
        stats["input_rows"] += 1
        code = language_code(raw.get("language"))
        languages[code] += 1
        game = app_id(raw.get("app_id"))
        identifier = review_id(raw.get("review_id"))
        dates = {field: timestamp(raw.get(field)) for field in TIME_FIELDS}
        for field in TIME_FIELDS:
            if raw.get(field) in (None, ""):
                stats["missing_" + field] += 1
            elif dates[field] is None:
                stats["invalid_" + field] += 1
        if all(dates.values()) and dates[TIME_FIELDS[1]] < dates[TIME_FIELDS[0]]:
            stats["updated_before_created"] += 1
        if game is None:
            stats["invalid_app_id"] += 1
        if identifier is None:
            stats["invalid_review_id"] += 1
        if raw.get("generated_id"):
            stats["generated_review_id"] += 1
        if game is None or identifier is None:
            removed["invalid_app_id" if game is None else "invalid_review_id"] += 1
            continue

        key = game, identifier
        updated = dates[TIME_FIELDS[1]] or ""
        if existing := selected.get(key):
            removed["duplicate_id"] += 1
            if existing[0].get("review_text") != raw.get("review_text"):
                stats["duplicate_text_conflicts"] += 1
                LOG.info(
                    "App %s duplicate review at input row %s: %s",
                    game, stats["input_rows"],
                    "kept newer update" if updated > existing[1] else "kept previous version",
                )
            if updated <= existing[1]:
                continue
        selected[key] = raw, updated, dates, code

    records = []
    examples = []
    for (game, identifier), (raw, _, dates, code) in selected.items():
        text = raw.get("review_text")
        vote = boolean(raw.get("voted_up"))
        if text is None or isinstance(text, str) and not text.strip():
            removed["missing_text"] += 1
            continue
        if not isinstance(text, str):
            removed["invalid_text_type"] += 1
            continue
        original, clean = normalize(text)
        if not clean:
            removed["empty_after_normalization"] += 1
            continue
        if vote is None:
            removed["missing_label" if raw.get("voted_up") in (None, "") else "invalid_label"] += 1
            continue
        if code == "unknown" or language != "all" and code != language:
            removed["unknown_language" if code == "unknown" else "other_language"] += 1
            continue

        raw_name = raw.get("game_name")
        game_name = catalog.get(game)
        if game_name is None and isinstance(raw_name, str):
            game_name = normalize(raw_name)[0] or None
        if len(examples) < 3:
            examples.append({"review_text": original[:160], "review_clean": clean[:160]})
        records.append({
            "source": raw["source"], "app_id": game, "review_id": identifier,
            "review_text": original, "review_clean": clean, "language": code,
            "voted_up": vote, "sentiment": int(vote), **dates, "text_length": len(clean),
            "word_count": len(clean.split()), "game_name": game_name,
            **{field: uint(raw.get(field)) for field in INTEGER_FIELDS},
            **{field: boolean(raw.get(field)) for field in BOOLEAN_FIELDS},
            "weighted_vote_score": finite_float(raw.get("weighted_vote_score")),
        })
    return records, dict(stats), dict(removed), dict(languages), examples
