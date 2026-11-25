"""Snapshot-based sampling and quality metadata. Ratios are fractions from zero to one."""
from datetime import datetime
import math

from .schema import uint
from .storage import now, read_json


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def source_revision(run):
    return {key: run.get(key) for key in ("run_id", "pages", "raw_count", "status")} if run else None


def population(runs, balanced=False):
    warnings = []
    timestamps = [run.get("population_observed_at_utc") for run in runs]
    result = None
    if balanced and len(runs) == 2:
        counts = [uint(run.get("total_matching")) for run in runs]
        if all(count is not None and count >= run.get("review_count", 0) for count, run in zip(counts, runs)):
            positive, negative = counts
            result = {"positive": positive, "negative": negative, "total": positive + negative}
            warnings.append("Label totals were observed in separate API calls and may change between calls.")
        else:
            warnings.append("One or both filtered population counts are missing or inconsistent.")
    elif not balanced and len(runs) == 1:
        run = runs[0]
        summary = run.get("query_summary") or {}
        counts = [uint(summary.get(key)) for key in ("total_positive", "total_negative", "total_reviews")]
        if all(count is not None for count in counts):
            positive, negative, total = counts
            # Score summaries may have a different scope from language/date query matching counts.
            if (positive + negative == total == uint(run.get("total_matching"))
                    and total >= run.get("review_count", 0)):
                result = {"positive": positive, "negative": negative, "total": total}
            else:
                warnings.append("Steam score summary does not match the filtered total; population is unknown.")
    if balanced and len(runs) != 2:
        warnings.append("Both filtered population observations are required.")
    if result is not None:
        total = result["total"]
        result.update(positive_ratio=result["positive"] / total if total else None,
                      negative_ratio=result["negative"] / total if total else None)
    return result, timestamps, warnings


def review_period(frame, start=None, end=None):
    dates = [value for value in frame["created_at_utc"] if isinstance(value, str)]
    return {
        "requested_start_utc": start, "requested_end_exclusive_utc": end,
        "actual_start_utc": min(dates, default=None), "actual_end_utc": max(dates, default=None),
    }


def enrich(frame, metadata, result, requested, *, runs=(), report=None):
    """Use only the report and raw runs that produced the returned immutable generation."""
    if report is None and result.get("report_path"):
        from pathlib import Path
        report = read_json(Path(result["report_path"]))
    if report and "source_runs" in report.get("context", {}):
        runs = report["context"]["source_runs"]
    context = (report or {}).get("context", {})
    mode = (result.get("sampling") or {}).get("mode", "recent")
    positive = int(frame["voted_up"].sum())
    sampling = dict(result.get("sampling") or {})
    matching, observed, warnings = population(list(runs), mode == "balanced")
    if result["source"] == "csv":
        warnings.append("Original CSV sampling conditions and population are unknown.")
    if not result["preprocessing_success"]:
        warnings.append("Preprocessing retained an earlier valid snapshot.")
    mismatches = sum((sampling.get("filter_label_mismatches") or {}).values())
    if not report:
        mismatches = None
    quality = {
        "language": result.get("language"), "requested_review_count": requested,
        "raw_received_count": sum(run["raw_count"] for run in runs) if runs else None,
        "unique_collected_count": context.get("unique_collected_count", (
            runs[0]["review_count"] if len(runs) == 1 else None
        )),
        # Existing collector retains pages verbatim; duplicates are removed by prepare().
        "collection_duplicate_count": 0 if runs else None,
        "filter_mismatch_count": mismatches,
        "preprocessing_input_count": report["input_rows"] if report else None,
        "preprocessing_excluded_count": report["removed_rows"] if report else None,
        "preprocessing_excluded_by_reason": report["removed_by_reason"] if report else None,
        "processed_review_count": result["clean_rows"], "analyzed_review_count": len(frame),
        "analysis_limit_excluded_count": result["clean_rows"] - len(frame),
        "excluded_total_count": (
            mismatches + report["removed_rows"] + result["clean_rows"] - len(frame)
            if report and mismatches is not None else None
        ),
        "accounting_verified": bool(report and result["clean_rows"] == report["clean_rows"]
                                    and report["passed"]),
    }
    if quality["raw_received_count"] is not None and report:
        quality["accounting_verified"] = bool(
            quality["accounting_verified"]
            and quality["raw_received_count"] == report["input_rows"] + mismatches
            and report["input_rows"] == report["removed_rows"] + result["clean_rows"]
        )
    sampling.update(
        mode=mode, matching_population=matching,
        population_conditions={
            "app_id": metadata["app_id"], "language": result.get("language"),
            "start_utc": context.get("requested_start_utc"),
            "end_exclusive_utc": context.get("requested_end_exclusive_utc"),
            "purchase_type": 1 if result["source"] == "api" else None,
            "off_topic_filter": True if result["source"] == "api" else None,
            "sort": context.get("sort"),
            "review_type": ([1, 2] if mode == "balanced" else [0]) if result["source"] == "api" else None,
        },
        sampling_method_known=result["source"] == "api",
        population_observed_at_utc=observed,
        sample_collected_at_utc=[run.get("finished_at_utc") for run in runs],
        selected_counts={"positive": positive, "negative": len(frame) - positive},
        selected_ratios={"positive": positive / len(frame) if len(frame) else None,
                         "negative": (len(frame) - positive) / len(frame) if len(frame) else None},
        is_population_representative=False,
    )
    period = review_period(frame, context.get("requested_start_utc"), context.get("requested_end_exclusive_utc"))
    started = [run["started_at_utc"] for run in runs]
    finished = [run["finished_at_utc"] for run in runs if run.get("finished_at_utc")]
    last = max(finished, default=None)
    age = max(0, (datetime.fromisoformat(now()) - datetime.fromisoformat(last)).total_seconds()) if last else None
    metadata.update(
        source=result["source"], data_source=result["source"], sample_mode=mode,
        sampling=sampling, data_quality=quality, review_period=period,
        collection_started_at_utc=min(started, default=None), collection_finished_at_utc=last,
        cache_age_seconds=age, cache_stale=age >= 86400 if age is not None else None,
        warnings=list(dict.fromkeys([*(report or {}).get("warnings", []), *warnings])),
        latest_attempt=metadata.get("latest_attempt", metadata.get("last_attempt")),
        snapshot_run_id=result.get("raw_run_id"),
        shortage_reason="Fewer processed reviews than requested" if len(frame) < requested else None,
    )
    return json_safe(metadata)


def snapshot_runs(pipeline, app_id, result):
    if result["source"] != "api":
        return []
    state = read_json(pipeline._raw(app_id) / "state.json", {})
    candidates = [state.get("active"), state.get("attempt"),
                  *(state.get("active_by_review_type") or {}).values()]
    identifiers = (result.get("sampling") or {}).get("source_run_ids")
    identifiers = list(identifiers.values()) if identifiers else [result["raw_run_id"]]
    runs = []
    for identifier in identifiers:
        found = next((run for run in candidates if run and run["run_id"] == identifier), None)
        if found is None:
            return []
        runs.append(found)
    return runs
