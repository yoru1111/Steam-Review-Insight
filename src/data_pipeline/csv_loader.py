"""Read UTF-8 CSV input with explicit schema mapping and provenance."""
import csv
from hashlib import sha256
import json

from .schema import BOOLEAN_FIELDS, INTEGER_FIELDS, TIME_FIELDS

ALIASES = {
    "review_text": ("review_text", "review"),
    "voted_up": ("voted_up", "recommended"),
    "app_id": ("app_id", "appid"),
    "review_id": ("review_id", "recommendationid"),
    "language": ("language",),
    "game_name": ("game_name",),
    TIME_FIELDS[0]: (TIME_FIELDS[0], "timestamp_created"),
    TIME_FIELDS[1]: (TIME_FIELDS[1], "timestamp_updated"),
    INTEGER_FIELDS[0]: (INTEGER_FIELDS[0], "playtime_at_review"),
    INTEGER_FIELDS[1]: (INTEGER_FIELDS[1], "playtime_forever"),
    **{field: (field,) for field in (*INTEGER_FIELDS[2:], *BOOLEAN_FIELDS, "weighted_vote_score")},
}


def csv_rows(path, mapping=None, *, game_id=None, declared_language=None):
    mapping = {} if mapping is None else mapping
    if not isinstance(mapping, dict) or any(
        key not in ALIASES or not isinstance(value, str) for key, value in mapping.items()
    ):
        raise ValueError("Column map must use standard field names as keys and CSV headers as values")

    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        headers = reader.fieldnames or []
        if len(set(headers)) != len(headers):
            raise ValueError("Duplicate CSV headers")
        columns = {}
        for field, aliases in ALIASES.items():
            candidates = [alias for alias in aliases if alias in headers]
            if field in mapping:
                if mapping[field] not in headers:
                    raise ValueError(f"Mapped CSV column for {field} does not exist")
                columns[field] = mapping[field]
            elif len(candidates) > 1:
                raise ValueError(f"Ambiguous CSV columns for {field}; provide --mapping")
            elif candidates:
                columns[field] = candidates[0]

        required = {"review_text", "voted_up"}
        if game_id is None:
            required.add("app_id")
        if missing := required - columns.keys():
            raise ValueError("Missing required CSV fields: " + ", ".join(sorted(missing))
                             + ". Available headers: " + ", ".join(headers))

        for position, row in enumerate(reader, start=1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV field count mismatch at record {position}")
            standard = {field: row[header] for field, header in columns.items()}
            if "app_id" not in columns:
                standard["app_id"] = game_id
            if not standard.get("language", "").strip() and declared_language:
                standard["language"] = declared_language
            if not standard.get("review_id", "").strip():
                # Ordinal distinguishes reviewers even when every available field is identical.
                identity = json.dumps([position, standard], sort_keys=True, ensure_ascii=True)
                standard["review_id"] = "csv-" + sha256(identity.encode()).hexdigest()
                standard["generated_id"] = True
            yield {**standard, "source": "csv"}
