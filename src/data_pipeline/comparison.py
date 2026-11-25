"""UTC half-open review windows with query-isolated raw and processed snapshots."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as utc_timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from .collector import CollectionError
from .schema import COLUMNS
from .service import ReviewPipeline, require_app_id, select_language
from .storage import now
from .metadata import review_period

POLICY_VERSION = "2"


def utc_second(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.microsecond:
            raise ValueError
        parsed = parsed.astimezone(utc_timezone.utc)
        if not 0 <= parsed.timestamp() <= 2**32 - 1:
            raise ValueError
        return parsed
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError("Period boundaries must be timezone-aware UTC-convertible whole seconds") from None


def comparison_windows(reference_date, window_days=14, timezone="Asia/Seoul"):
    if type(window_days) is not int or not 1 <= window_days <= 365:
        raise ValueError("window_days must be between 1 and 365")
    try:
        day = date.fromisoformat(reference_date) if isinstance(reference_date, str) else reference_date
        if type(day) is not date:
            raise ValueError
        zone = ZoneInfo(timezone)
        boundary = datetime.combine(day, datetime.min.time(), zone)
        before = datetime.combine(day - timedelta(days=window_days), datetime.min.time(), zone)
        after = datetime.combine(day + timedelta(days=window_days), datetime.min.time(), zone)
    except (TypeError, ValueError, ZoneInfoNotFoundError, OverflowError):
        raise ValueError("Invalid reference date or IANA timezone") from None
    return tuple(moment.astimezone(utc_timezone.utc) for moment in (before, boundary, after))


@dataclass
class PeriodReviews:
    frame: pd.DataFrame
    metadata: dict

    def summary(self):
        return self.metadata


@dataclass
class ComparisonReviews:
    before: PeriodReviews
    after: PeriodReviews
    conditions: dict
    status: str
    comparison_ready: bool
    comparable_conditions: bool
    warnings: list[str]

    def summary(self):
        return {
            "before": self.before.summary(), "after": self.after.summary(), "conditions": self.conditions,
            "status": self.status, "comparison_ready": self.comparison_ready,
            "comparable_conditions": self.comparable_conditions, "warnings": self.warnings,
        }


class PeriodPipeline(ReviewPipeline):
    def __init__(self, parent, game, start, end, language, limit, mode):
        super().__init__(parent.root, catalog_path=parent.catalog_path, steam_catalog=parent.steam_catalog)
        self.period = (start.isoformat(timespec="microseconds"), end.isoformat(timespec="microseconds"))
        self.language = language
        self.query = {
            "app_id": game, "start_utc": self.period[0], "end_exclusive_utc": self.period[1],
            "language": language, "sample_mode": mode, "requested_count": limit,
            "review_type": [1, 2] if mode == "balanced" else [0], "purchase_type": 1,
            "sort": 1, "off_topic_filter": True, "preprocessing_policy_version": POLICY_VERSION,
            "max_requests_per_label": 100, "retries": 3,
        }
        self.query_hash = sha256(json.dumps(self.query, sort_keys=True).encode()).hexdigest()
        def client_factory(**kwargs):
            client = parent.client_factory(**kwargs)
            client.period = (int(start.timestamp()), int(end.timestamp()))
            return client
        self.client_factory = client_factory

    def _raw(self, game):
        return self.root / "data/raw/comparisons" / str(require_app_id(game)) / self.query_hash

    def _processed(self, game):
        return self.root / "data/processed/comparisons" / str(require_app_id(game)) / self.query_hash

    def collect_reviews(self, app_id, limit=1000, **kwargs):
        kwargs.update(language=self.language, sort=1, max_requests=100)
        return super().collect_reviews(app_id, limit, **kwargs)


def collect_reviews_by_period(pipeline, app_id, start_utc, end_exclusive_utc, language="english",
                              limit=1000, sample_mode="recent", refresh=False, minimum_required_count=30):
    require_app_id(app_id)
    start, end = utc_second(start_utc), utc_second(end_exclusive_utc)
    if start >= end:
        raise ValueError("Period end must be later than start")
    if type(limit) is not int or not 2 <= limit <= 50000:
        raise ValueError("limit must be between 2 and 50000")
    if type(minimum_required_count) is not int or minimum_required_count < 1:
        raise ValueError("minimum_required_count must be positive")
    if sample_mode not in {"recent", "balanced"}:
        raise ValueError("sample_mode must be recent or balanced")
    language = select_language(language)
    isolated = PeriodPipeline(pipeline, app_id, start, end, language, limit, sample_mode)
    frame = pd.DataFrame(columns=COLUMNS).astype({"voted_up": bool})
    future = end > datetime.fromisoformat(now())
    try:
        frame, metadata = isolated.get_reviews(app_id, limit, refresh, sample_mode)
        excluded = metadata["data_quality"].get("preprocessing_excluded_by_reason") or {}
        invalid = sum(excluded.get(key, 0) for key in ("outside_requested_period", "invalid_timestamp_for_period",
                                                     "other_language", "unknown_language", "invalid_app_id"))
        mismatches = metadata["data_quality"].get("filter_mismatch_count") or 0
        verified = not invalid and not mismatches
        if metadata["collection_status"] != "complete" or not verified or not metadata["preprocessing_success"]:
            status = "partial"
        elif not len(frame):
            status = "empty"
        elif len(frame) < limit or len(frame) < minimum_required_count:
            status = "insufficient_data"
        else:
            status = "complete"
    except CollectionError as exc:
        metadata = {
            "app_id": app_id, "language": language, "sample_mode": sample_mode, "error": str(exc),
            "game_name": pipeline.catalog().get(app_id), "source": "api", "data_source": "api",
            "collection_status": "failed", "cache_used": False, "cache_age_seconds": None,
            "cache_stale": None, "processed_at_utc": None, "collection_started_at_utc": None,
            "collection_finished_at_utc": None, "warnings": [], "data_quality": None,
            "review_period": review_period(frame, isolated.period[0], isolated.period[1]),
            "sampling": {"mode": sample_mode, "matching_population": None, "selected_counts": {
                "positive": 0, "negative": 0,
            }, "selected_ratios": {"positive": None, "negative": None}, "is_population_representative": False},
        }
        status, verified = "failed", False
    if future:
        status = "period_incomplete"
    enough = len(frame) >= minimum_required_count
    reason = None if status == "complete" else (
        "Comparison window has not ended" if future else metadata.get("error") or status
    )
    if status == "insufficient_data" and not enough:
        reason = "Below the project's minimum required review count"
    metadata.update(
        status=status, requested_count=limit,
        collected_count=(metadata.get("data_quality") or {}).get("unique_collected_count"),
        processed_count=len(frame), minimum_required_count=minimum_required_count,
        missing_count=max(0, limit - len(frame)), shortage_reason=reason,
        minimum_missing_count=max(0, minimum_required_count - len(frame)),
        comparison_ready=enough and verified and not future and status not in {"failed", "partial"},
        conditions_verified=verified, comparable_conditions=verified,
        query=isolated.query, query_hash=isolated.query_hash,
        requested_period_start_utc=isolated.period[0],
        requested_period_end_exclusive_utc=isolated.period[1],
    )
    return PeriodReviews(frame, metadata)


def get_comparison_reviews(pipeline, app_id, reference_date, window_days=14, limit_per_period=1000,
                           language="english", sample_mode="recent", timezone="Asia/Seoul",
                           refresh=False, minimum_required_count=30):
    start, boundary, end = comparison_windows(reference_date, window_days, timezone)
    options = dict(language=language, limit=limit_per_period, sample_mode=sample_mode,
                   refresh=refresh, minimum_required_count=minimum_required_count)
    before = collect_reviews_by_period(pipeline, app_id, start, boundary, **options)
    after = collect_reviews_by_period(pipeline, app_id, boundary, end, **options)
    common = set(before.frame["review_id"]) & set(after.frame["review_id"])
    warnings = []
    same_duration = boundary - start == end - boundary
    comparable = (before.metadata["conditions_verified"] and after.metadata["conditions_verified"]
                  and not common and same_duration)
    if not same_duration:
        warnings.append("The timezone transition gives the calendar windows different elapsed UTC durations.")
    if common:
        warnings.append("The same review ID was returned for both windows; comparison is not ready.")
        for period in (before, after):
            period.frame = period.frame[~period.frame["review_id"].isin(common)].copy()
            metadata = period.metadata
            metadata.update(comparison_ready=False, cross_period_duplicate_count=len(common),
                            processed_count=len(period.frame), missing_count=max(0, limit_per_period - len(period.frame)),
                            processed_rows=len(period.frame),
                            minimum_missing_count=max(0, minimum_required_count - len(period.frame)),
                            status="partial", conditions_verified=False, comparable_conditions=False,
                            shortage_reason="Conflicting review IDs were excluded from both windows")
            positive = int(period.frame["voted_up"].sum())
            metadata["sampling"]["selected_counts"] = {"positive": positive, "negative": len(period.frame) - positive}
            metadata["sampling"]["selected_ratios"] = {
                "positive": positive / len(period.frame) if len(period.frame) else None,
                "negative": (len(period.frame) - positive) / len(period.frame) if len(period.frame) else None,
            }
            quality = metadata.get("data_quality")
            if quality:
                quality["comparison_excluded_count"] = len(common)
                quality["comparison_excluded_by_reason"] = {"cross_period_duplicate_id": len(common)}
                quality["analyzed_review_count"] = len(period.frame)
                if quality["excluded_total_count"] is not None:
                    quality["excluded_total_count"] += len(common)
            previous = metadata.get("review_period", {})
            metadata["review_period"] = review_period(
                period.frame, previous.get("requested_start_utc"), previous.get("requested_end_exclusive_utc"),
            )
    statuses = [before.metadata["status"], after.metadata["status"]]
    if "period_incomplete" in statuses:
        status = "period_incomplete"
    elif all(item == "failed" for item in statuses):
        status = "failed"
    elif "failed" in statuses or "partial" in statuses or common or not same_duration:
        status = "partial"
    elif all(item == "empty" for item in statuses):
        status = "empty"
    elif "insufficient_data" in statuses or "empty" in statuses:
        status = "insufficient_data"
    else:
        status = "complete"
    conditions = {**before.metadata["query"], "reference_date": str(reference_date),
                  "timezone": timezone, "window_days": window_days,
                  "equal_elapsed_duration": same_duration,
                  "before_start_utc": start.isoformat(), "reference_utc": boundary.isoformat(),
                  "after_end_exclusive_utc": end.isoformat()}
    conditions.pop("start_utc")
    conditions.pop("end_exclusive_utc")
    ready = comparable and all(period.metadata["comparison_ready"] for period in (before, after))
    return ComparisonReviews(before, after, conditions, status, ready, comparable, warnings)
