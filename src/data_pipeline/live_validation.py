"""Explicit opt-in live validation. Reports contain public game metadata and counts only."""
import json
from uuid import uuid4

from .collector import CollectionError, parse_page
from .public_steam import PublicSteamClient
from .rankings import Rankings
from .storage import atomic_text, now, write_json

# These are connection-test candidates, not an inferred popularity ranking.
CANDIDATES = [400, 620, 105600, 413150, 1245620, 1091500, 730, 570, 578080, 1172470,
              440, 230410, 550, 1145360, 252490, 892970, 1086940, 271590, 108600, 346110]


def validate_games(pipeline, limit=20):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Live validation limit must be between 1 and 20")
    client = pipeline.public_client or PublicSteamClient()
    charts = Rankings(pipeline.root, client=client, details=pipeline._details())
    sellers = charts.get("top_sellers", limit=40, include_details=False)
    players = charts.get("most_played", limit=20, include_details=False)
    identifiers = list(dict.fromkeys([row["app_id"] for row in sellers["games"]] + CANDIDATES))
    rows = []
    for identifier in identifiers:
        details = pipeline.get_game_details(identifier)
        if details.get("game_type") not in (None, "game"):
            continue
        image_valid, image_error = False, None
        if details.get("header_image"):
            try:
                image_valid = client.get(details["header_image"], method="HEAD")
            except CollectionError as exc:
                image_error = str(exc)
        review_success, review_count, error = False, 0, None
        review_http_success = False
        review_checked_at = None
        try:
            review_client = pipeline.client_factory(max_requests=3, use_key=False)
            payload = review_client.page(identifier, "english", 1, "*", 1, 0)
            review_http_success = True
            reviews, _, _, total = parse_page(payload)
            if len(reviews) > 1:
                raise CollectionError("Steam returned more than one validation review")
            review_checked_at = now()
            write_json(pipeline.root / "data/raw/connection_validation" / str(identifier) / f"{uuid4().hex}.json",
                       payload)
            if not reviews and total is not None and total > 0:
                raise CollectionError("Empty first page conflicts with total_matching")
            review_success, review_count = True, len(reviews)
        except CollectionError as exc:
            error = str(exc)
        cached = pipeline.get_game_details(identifier) if details["metadata_status"] != "unavailable" else None
        rows.append({
            "app_id": identifier, "name": details["name"], "metadata_success": details["metadata_status"] != "unavailable",
            "metadata_complete": details["metadata_status"] == "complete", "header_image": details["header_image"],
            "image_valid": image_valid, "image_error": image_error, "genres": details["genres"],
            "release_date": details["release_date"], "release_date_raw": details["release_date_raw"],
            "store_url": details["store_url"], "game_type": details.get("game_type"),
            "review_api_success": review_success, "actual_review_count": review_count,
            "review_http_success": review_http_success,
            "details_cache_reused": bool(cached and cached["cache_used"]),
            "source": details["source"], "source_url": details["source_url"],
            "details_fetched_at_utc": details["fetched_at_utc"],
            "review_checked_at_utc": review_checked_at,
            "last_checked_at_utc": now(), "missing_fields": details["missing_fields"],
            "errors": [message for message in (details.get("error"), error, image_error) if message],
        })
        if len(rows) == limit:
            break
    report = {
        "test_type": "live_steam", "generated_at_utc": now(), "requested_games": limit,
        "metadata_successes": sum(row["metadata_success"] for row in rows),
        "complete_details": sum(row["metadata_complete"] for row in rows),
        "review_api_successes": sum(row["review_api_success"] for row in rows),
        "review_http_successes": sum(row["review_http_success"] for row in rows),
        "games_with_reviews": sum(row["actual_review_count"] > 0 for row in rows),
        "valid_images": sum(row["image_valid"] for row in rows),
        "selection": "Official Top Sellers candidates with appdetails type=game; verified-store fallback candidates",
        "rankings": {
            kind: {key: result[key] for key in ("status", "source_url", "fetched_at_utc", "cache_used", "error")}
            for kind, result in (("top_sellers", sellers), ("most_played", players))
        }, "games": rows,
    }
    json.dumps(report, allow_nan=False)
    directory = pipeline.root / "reports"
    write_json(directory / "game_metadata_20_validation.json", report)
    with atomic_text(directory / "game_metadata_20_validation.md") as output:
        output.write("# Live Steam game validation\n\n")
        output.write(f"Observed {report['generated_at_utc']}. Test type is live_steam.\n\n")
        output.write("| App ID | Name | Details complete | Image verified | Review API | Reviews | Cache reused |\n")
        output.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for row in rows:
            name = (row["name"] or "Unavailable").replace("|", " ")
            output.write(f"| {row['app_id']} | {name} | {row['metadata_complete']} | {row['image_valid']} | "
                         f"{row['review_api_success']} | {row['actual_review_count']} | {row['details_cache_reused']} |\n")
        output.write("\nFull provenance, missing fields, errors and chart timestamps are recorded in the JSON report.\n")
        output.write("\n## Sources and diagnostics\n")
        for row in rows:
            output.write(f"\n### App {row['app_id']}\n\n")
            output.write(f"- Source {row['source_url']}\n")
            output.write(f"- Store {row['store_url']}\n")
            output.write(f"- Type {row['game_type']}, genres {', '.join(row['genres'])}\n")
            output.write(f"- Release date {row['release_date']}, raw display {row['release_date_raw']}\n")
            output.write(f"- Details observed {row['details_fetched_at_utc']}\n")
            output.write(f"- Reviews checked {row['review_checked_at_utc']}\n")
            output.write(f"- Missing fields {', '.join(row['missing_fields']) or 'none'}\n")
            output.write(f"- Errors {' | '.join(row['errors']) or 'none'}\n")
    return report
