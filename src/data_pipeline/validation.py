"""Verify the canonical in-memory schema and read back exported CSV files."""
import csv

from .schema import (
    BOOLEAN_FIELDS, COLUMNS, INTEGER_FIELDS, TIME_FIELDS,
    app_id, boolean, finite_float, language_code, review_id, timestamp, uint,
)

TEXT_FIELDS = ("review_text", "review_clean", "language", "review_id", "source")
NUMERIC_FIELDS = (*INTEGER_FIELDS, "app_id", "sentiment", "text_length", "word_count")


def validate_records(records, columns=COLUMNS):
    def valid_row(row):
        return (
            set(row) == set(COLUMNS)
            and row["source"] in {"api", "csv"}
            and all(isinstance(row[field], str) and row[field].strip() for field in TEXT_FIELDS)
            and type(row["app_id"]) is int and app_id(row["app_id"]) == row["app_id"]
            and review_id(row["review_id"]) == row["review_id"]
            and language_code(row["language"]) == row["language"] != "unknown"
            and type(row["voted_up"]) is bool
            and type(row["sentiment"]) is int and row["sentiment"] == int(row["voted_up"])
            and all(row[field] is None or type(row[field]) is bool for field in BOOLEAN_FIELDS)
            and all(row[field] is None or type(row[field]) is int and uint(row[field]) is not None
                    for field in INTEGER_FIELDS)
            and all(row[field] is None or timestamp(row[field]) == row[field] for field in TIME_FIELDS)
            and (row["game_name"] is None or isinstance(row["game_name"], str))
            and (row["weighted_vote_score"] is None or type(row["weighted_vote_score"]) is float
                 and finite_float(row["weighted_vote_score"]) is not None)
            and type(row["text_length"]) is int and row["text_length"] == len(row["review_clean"])
            and type(row["word_count"]) is int and row["word_count"] == len(row["review_clean"].split())
        )

    def utf8(row):
        try:
            for value in row.values():
                if isinstance(value, str):
                    value.encode("utf-8")
            return True
        except UnicodeEncodeError:
            return False

    keys = [(row.get("app_id"), row.get("review_id")) for row in records]
    return {
        "columns_match": tuple(columns) == COLUMNS,
        "types_and_values_match": all(map(valid_row, records)),
        "unique_app_review_ids": len(set(keys)) == len(keys),
        "utf8_encodable": all(map(utf8, records)),
    }


def read_export(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, strict=True)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("CSV headers do not match the standard schema")
        records = []
        for row in reader:
            if None in row or None in row.values():
                raise ValueError("Invalid exported CSV row width")
            for field in (*NUMERIC_FIELDS, *BOOLEAN_FIELDS, "voted_up", "weighted_vote_score",
                          *TIME_FIELDS, "game_name"):
                value = row[field]
                if not value:
                    row[field] = None
                elif field in NUMERIC_FIELDS:
                    row[field] = uint(value)
                elif field in (*BOOLEAN_FIELDS, "voted_up"):
                    row[field] = boolean(value)
                elif field == "weighted_vote_score":
                    row[field] = finite_float(value)
                if value and row[field] is None:
                    raise ValueError(f"Invalid value in exported CSV column {field}")
            records.append(row)
        return records
