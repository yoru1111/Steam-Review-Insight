"""Steam GetAppReviews transport and resumable, per-game collection."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import json
import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from .schema import language_code, timestamp, uint
from .storage import now, read_json, write_json

ENDPOINT = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"
LOG = logging.getLogger(__name__)
RETRYABLE = {429, 500, 502, 503, 504}
REVIEW_TYPES = {0: "all", 1: "positive", 2: "negative"}


class CollectionError(RuntimeError):
    """A collection error with a safe, URL-free message."""


def request_parameters(app_id, language="english", sort=1, cursor="*", page_size=100, review_type=0):
    return {"input_json": json.dumps({
        "appid": app_id, "filter": sort, "languages": [language], "review_type": review_type,
        "purchase_type": 1, "num_per_page": page_size, "cursor": cursor,
    }, separators=(",", ":"))}


def active_run(state, review_type=0):
    """Read old all-review state and new label-filtered state without migrating files."""
    if review_type == 0:
        return state.get("active")
    return (state.get("active_by_review_type") or {}).get(str(review_type))


def parse_page(payload):
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        raise CollectionError("Missing Steam response object")
    reviews = response.get("reviews")
    # Steam may omit empty repeated fields. Accept this only with explicit zero-page metadata.
    summary = response.get("query_summary")
    if summary is not None and not isinstance(summary, dict):
        raise CollectionError("Invalid Steam query_summary")
    if reviews is None and isinstance(summary, dict) and summary.get("num_reviews") == 0:
        reviews = []
    if not isinstance(reviews, list) or any(not isinstance(row, dict) for row in reviews):
        raise CollectionError("Invalid Steam reviews list")
    if isinstance(summary, dict) and "num_reviews" in summary:
        if uint(summary["num_reviews"]) != len(reviews):
            raise CollectionError("Steam query_summary disagrees with page length")
    total = response.get("total_matching")
    if total is not None and uint(total) is None:
        raise CollectionError("Invalid Steam total_matching")
    cursor = response.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise CollectionError("Invalid Steam cursor type")
    return reviews, cursor, summary, uint(total)


def retry_delay(value, attempt):
    if value:
        try:
            return max(0, int(value))
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                return max(0, (date - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return min(2**attempt, 30)


class SteamClient:
    def __init__(self, *, opener=urlopen, sleep=time.sleep, delay=1.0,
                 retries=3, timeout=15, max_requests=2000, use_key=False):
        self.opener = opener
        self.sleep = sleep
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.max_requests = max_requests
        self.key = os.environ.get("STEAM_WEB_API_KEY", "").strip() if use_key else ""
        self.requests = 0

    def page(self, app_id, language, sort, cursor, page_size, review_type=0):
        params = request_parameters(app_id, language, sort, cursor, page_size, review_type)
        attempt = 0
        while True:
            if self.requests >= self.max_requests:
                raise CollectionError("Request budget exhausted")
            if self.requests:
                self.sleep(self.delay)
            self.requests += 1
            request = Request(ENDPOINT + "?" + urlencode(params))
            if self.key:
                request.add_unredirected_header("x-webapi-key", self.key)
            retry_after = None
            try:
                with self.opener(request, timeout=self.timeout) as result:
                    return json.load(result)
            except HTTPError as exc:
                code = exc.code
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                exc.close()
                if self.key and code in {400, 401, 403}:
                    LOG.warning("App %s: publisher key request returned HTTP %s; trying public access", app_id, code)
                    self.key = ""
                    continue
                message = f"Steam HTTP {code}"
                retryable = code in RETRYABLE
            except (TimeoutError, URLError, OSError, http.client.HTTPException) as exc:
                message = f"Steam network error ({type(getattr(exc, 'reason', exc)).__name__})"
                retryable = True
            except (ValueError, RecursionError):
                LOG.warning("App %s: Steam returned invalid JSON", app_id)
                raise CollectionError("Steam returned invalid JSON") from None
            LOG.warning("App %s: %s (request %s)", app_id, message, self.requests)
            if not retryable or attempt >= self.retries or self.requests >= self.max_requests:
                raise CollectionError(message)
            wait = retry_delay(retry_after, attempt)
            if wait > 120:
                raise CollectionError(f"{message}; Retry-After exceeds 120 seconds")
            self.sleep(wait)
            attempt += 1


def raw_pages(directory, run):
    for number in range(run["pages"]):
        yield read_json(directory / run["run_id"] / f"{number:06}.json")


def review_versions(reviews):
    return frozenset(
        (identifier, timestamp(row.get("timestamp_updated")) or "")
        for row in reviews if (identifier := uint(row.get("recommendationid")))
    )


def collect(directory, state, client, game_id, limit, language, sort, *, resume, known_game, review_type=0):
    old = state.get("attempt")
    options = {"limit": limit, "language": language, "sort": sort, "review_type": review_type}
    if (resume and old and old["status"] in {"partial", "running", "failed"}
            and old.get("resumable", True)
            and all(old.get(k, 0 if k == "review_type" else None) == v for k, v in options.items())):
        run = {**old, "status": "running", "error": None, "finished_at_utc": None}
    else:
        run = {
            **options, "run_id": uuid4().hex, "status": "running", "error": None,
            "started_at_utc": now(), "finished_at_utc": None, "last_page_at_utc": None,
            "cursor": "*", "seen_cursors": [], "pages": 0, "requests": 0, "raw_count": 0,
            "review_count": 0, "total_matching": None, "query_summary": None, "resumable": True,
        }

    def save(snapshot):
        write_json(directory / "state.json", snapshot)

    state = {**state, "attempt": run}
    save(state)
    previous_requests = run["requests"]
    identifiers = set()
    signatures = set()
    for page in raw_pages(directory, run):
        reviews, _, _, _ = parse_page(page)
        signature = review_versions(reviews)
        signatures.add(signature)
        identifiers.update(identifier for identifier, _ in signature)

    try:
        while True:
            cursor = run["cursor"]
            page_size = min(100, max(1, limit - len(identifiers)))
            payload = client.page(game_id, language, sort, cursor, page_size, review_type)
            reviews, next_cursor, summary, total = parse_page(payload)
            if len(reviews) > page_size:
                raise CollectionError("Steam returned more reviews than requested")

            signature = review_versions(reviews)
            seen = [*run["seen_cursors"], cursor]
            duplicate = bool(signature) and signature in signatures
            signatures.add(signature)
            identifiers.update(identifier for identifier, _ in signature)
            checkpoint = {
                **run, "pages": run["pages"] + 1, "raw_count": run["raw_count"] + len(reviews),
                "review_count": len(identifiers), "cursor": next_cursor, "seen_cursors": seen,
                "last_page_at_utc": now(), "requests": previous_requests + client.requests,
                "total_matching": total if not run["pages"] and total is not None else run["total_matching"],
                "query_summary": summary if not run["pages"] else run["query_summary"],
            }
            if not reviews and not run["pages"] and not known_game:
                checkpoint.update(status="failed", error="Empty response for an unverified App ID", resumable=False)
            elif len(identifiers) >= limit:
                checkpoint.update(status="complete", stop_reason="limit")
            elif not reviews:
                checkpoint.update(status="complete", stop_reason="exhausted")
            elif duplicate or not next_cursor or next_cursor in seen:
                reason = "duplicate page" if duplicate else "missing or repeated next cursor"
                checkpoint.update(status="partial", error=f"Steam pagination stopped: {reason}", resumable=False)

            write_json(directory / run["run_id"] / f"{run['pages']:06}.json", payload)
            if checkpoint["status"] != "running":
                checkpoint["finished_at_utc"] = now()
            next_state = {**state, "attempt": checkpoint}
            # An empty refresh never displaces a nonempty raw snapshot.
            if checkpoint["status"] == "complete" and (identifiers or not active_run(state, review_type)):
                if review_type == 0:
                    next_state["active"] = checkpoint
                else:
                    next_state["active_by_review_type"] = {
                        **(state.get("active_by_review_type") or {}), str(review_type): checkpoint,
                    }
            save(next_state)
            state, run = next_state, checkpoint
            if run["status"] != "running":
                if run["error"]:
                    LOG.warning("App %s: %s", game_id, run["error"])
                return state
    except (CollectionError, KeyboardInterrupt) as exc:
        error = str(exc) if isinstance(exc, CollectionError) else "Interrupted by user"
        LOG.warning("App %s: %s", game_id, error)
        # An interrupt can arrive just after an atomic commit, so reload the committed checkpoint.
        committed = read_json(directory / "state.json")
        run = committed["attempt"]
        if run["status"] == "running":
            run.update(
                status="partial" if run["raw_count"] else "failed", error=error,
                requests=previous_requests + client.requests, finished_at_utc=now(),
            )
            save(committed)
        if isinstance(exc, KeyboardInterrupt):
            raise
        return committed
