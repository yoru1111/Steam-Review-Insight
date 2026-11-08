"""Search, collection and typed review access for UI and analysis callers."""
from datetime import datetime
import csv
from hashlib import file_digest
import logging
from pathlib import Path
from uuid import uuid4

from .catalog import SteamCatalog
from .collector import (
    REVIEW_TYPES, CollectionError, SteamClient, active_run, collect, parse_page, raw_pages,
)
from .csv_loader import csv_rows
from .preprocessing import prepare
from .reporting import build_report, save_report
from .schema import BOOLEAN_FIELDS, COLUMNS, INTEGER_FIELDS, api_row, app_id, language_code
from .storage import ROOT, atomic_text, now, read_json, write_json, writer_lock
from .validation import read_export

EXPORT = "steam_reviews_clean.csv"
LOG = logging.getLogger(__name__)


def write_csv(path, records, encoding):
    with atomic_text(path, encoding) as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def require_app_id(value):
    if type(value) is not int or app_id(value) is None:
        raise ValueError("app_id must be a positive 32-bit integer")
    return value


def select_language(value):
    code = language_code(value)
    if code == "unknown":
        raise ValueError("Specify a Steam language code such as english, or all")
    return code


def interleave_labels(records):
    """Keep balanced exports balanced even when downstream callers take a prefix."""
    positive = [row for row in records if row["voted_up"]]
    negative = [row for row in records if not row["voted_up"]]
    combined = []
    for position in range(max(len(positive), len(negative))):
        if position < len(positive):
            combined.append(positive[position])
        if position < len(negative):
            combined.append(negative[position])
    return combined


class ReviewPipeline:
    def __init__(self, root=ROOT, *, catalog_path=None, client_factory=SteamClient,
                 steam_catalog=None):
        self.root = Path(root).resolve()
        self.catalog_path = Path(catalog_path) if catalog_path is not None else self.root / "data/catalog.local.json"
        self.client_factory = client_factory
        self.steam_catalog = steam_catalog or SteamCatalog(self.root / "data/catalog.steam.json")

    def catalog(self):
        games = {}
        for path in (ROOT / "config/games.json", self.catalog_path):
            entries = read_json(path, {})
            if not isinstance(entries, dict):
                raise ValueError("Game catalog must be a JSON object mapping App IDs to names")
            for key, name in entries.items():
                if app_id(key) is None or not isinstance(name, str) or not name.strip():
                    raise ValueError("Invalid entry in game catalog")
                games[app_id(key)] = name.strip()
        return games

    def search_games(self, query: str) -> list[dict]:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        query = query.strip().casefold()
        if not query:
            return []
        games = self.catalog()
        games.update(self.steam_catalog.games())
        matches = [{"app_id": key, "name": name} for key, name in games.items()
                   if query in name.casefold()]
        return sorted(matches, key=lambda game: (
            game["name"].casefold() != query,
            not game["name"].casefold().startswith(query),
            game["name"].casefold(), game["app_id"],
        ))

    def _raw(self, game):
        return self.root / "data/raw/steam" / str(require_app_id(game))

    def _processed(self, game):
        return self.root / "data/processed/games" / str(require_app_id(game))

    def _status(self, game, state, *, cached=False, selected=None):
        attempt = state.get("attempt") or {}
        selected_type = (selected or {}).get("review_type", 0)
        attempt_type = attempt.get("review_type", 0)
        status_run = attempt if not selected or attempt_type == selected_type else selected
        processed = read_json(self._processed(game) / "current.json")
        when = selected["finished_at_utc"] if selected else None
        age = (datetime.fromisoformat(now()) - datetime.fromisoformat(when)).total_seconds() if when else None
        return {
            "app_id": game, "game_name": self.catalog().get(game) or (processed or {}).get("game_name"),
            "collection_status": status_run.get("status", "not_started"),
            "data_status": selected["status"] if selected else ("processed_cache" if processed else "unavailable"),
            "source": "api" if selected else (processed or {}).get("source"),
            "language": selected["language"] if selected else (processed or {}).get("language"),
            "cache_used": cached, "run_id": selected["run_id"] if selected else None,
            "review_count": selected["review_count"] if selected else (processed or {}).get("clean_rows", 0),
            "raw_count": selected["raw_count"] if selected else None,
            "review_type": selected_type, "review_type_name": REVIEW_TYPES[selected_type],
            "total_matching": selected.get("total_matching") if selected else None,
            "last_collected_at_utc": when, "cache_age_seconds": age,
            "cache_stale": age >= 86400 if age is not None else None,
            "last_attempt": {key: value for key, value in status_run.items()
                             if key not in {"cursor", "seen_cursors"}},
            "preprocessing_success": processed is not None,
            "processed_matches_raw": bool(selected and processed and selected["run_id"] == processed["raw_run_id"]),
            "processed_rows": (processed or {}).get("clean_rows"),
            "processed_at_utc": (processed or {}).get("processed_at_utc"),
            "error": status_run.get("error"),
        }

    def get_collection_status(self, app_id: int, review_type=0) -> dict:
        state = read_json(self._raw(app_id) / "state.json", {})
        selected = active_run(state, review_type)
        attempt = state.get("attempt") or {}
        if (not selected and attempt.get("raw_count")
                and attempt.get("review_type", 0) == review_type):
            selected = state["attempt"]
        return self._status(app_id, state, selected=selected)

    def collect_reviews(self, app_id: int, limit: int = 1000, *, refresh=False, resume=True,
                        language="english", sort=1, max_requests=2000, use_key=False,
                        review_type=0) -> dict:
        directory = self._raw(app_id)
        if type(limit) is not int or not 1 <= limit <= 50000:
            raise ValueError("limit must be between 1 and 50000")
        if type(max_requests) is not int or max_requests < 1 or type(sort) is not int or sort not in {1, 2}:
            raise ValueError("max_requests must be positive and sort must be 1 (Recent) or 2 (Updated)")
        if type(review_type) is not int or review_type not in REVIEW_TYPES:
            raise ValueError("review_type must be 0 (all), 1 (positive), or 2 (negative)")
        language = select_language(language)
        with writer_lock(directory):
            state = read_json(directory / "state.json", {})
            active = active_run(state, review_type)

            def compatible(run):
                return bool(run and run["language"] == language and run["sort"] == sort
                            and run.get("review_type", 0) == review_type)

            if not refresh and compatible(active) and (
                active["review_count"] == limit
                or active.get("stop_reason") == "exhausted" and active["review_count"] <= limit
            ):
                return self._status(app_id, state, cached=True, selected=active)

            processed = read_json(self._processed(app_id) / "current.json")
            fallback = bool(review_type == 0 and processed and processed["language"] == language)
            if not refresh and fallback and processed["source"] == "csv" and processed["clean_rows"] >= limit:
                return self._status(app_id, state, cached=True)

            state = collect(directory, state, self.client_factory(max_requests=max_requests, use_key=use_key),
                            app_id, limit, language, sort, resume=resume, known_game=(
                                app_id in self.catalog() or bool(active and active["review_count"])
                            ), review_type=review_type)
            attempt = state["attempt"]
            active = active_run(state, review_type)
            selected = active if compatible(active) else None
            if selected is None and attempt["raw_count"] and not fallback:
                selected = attempt
            if selected is None and not fallback:
                raise CollectionError(attempt["error"] or "No reviews are available")
            return self._status(app_id, state, cached=bool(
                selected and selected["run_id"] != attempt["run_id"] or selected is None and processed
            ), selected=selected)

    def _publish_game(self, game, records, context, encoding, report=None):
        directory = self._processed(game)
        current = read_json(directory / "current.json")
        if not records and current and current["clean_rows"]:
            return {**current, "preserved": True, "preprocessing_success": False}
        run = uuid4().hex
        snapshot = directory / run
        write_csv(snapshot / EXPORT, records, encoding)
        if report is not None:
            save_report(snapshot, report)
        result = {
            "source": context["source"], "raw_run_id": context.get("run_id"),
            "language": context["language"], "clean_rows": len(records), "processed_at_utc": now(),
            "game_name": records[0]["game_name"] if records else self.catalog().get(game),
            "csv_path": str(snapshot / EXPORT), "report_path": str(snapshot / "quality_report.json") if report else None,
            "generation": run, "preserved": False, "preprocessing_success": True,
        }
        if context.get("sampling") is not None:
            result["sampling"] = context["sampling"]
        # Persist a relative generation reference so a data directory can be moved.
        write_json(directory / "current.json", {
            key: value for key, value in result.items() if key not in {"csv_path", "report_path"}
        })
        return result

    def preprocess_reviews(self, app_id: int, *, collection=None, encoding="utf-8-sig") -> dict:
        directory = self._raw(app_id)
        with writer_lock(directory):
            state = read_json(directory / "state.json", {})
            active, attempt = active_run(state, 0), state.get("attempt")
            if collection and collection["app_id"] != app_id:
                raise ValueError("Collection belongs to a different app")
            target = collection["run_id"] if collection is not None else None
            if collection is not None:
                run = next((item for item in (active, attempt) if item and item["run_id"] == target), None)
                if target and not run:
                    raise CollectionError("Collection changed. Read its latest status and retry.")
            else:
                run = active or attempt
            if not run or not run["pages"] or run["status"] == "failed":
                return self._cached_processed(app_id)
            current = read_json(self._processed(app_id) / "current.json")
            if (run["status"] != "complete" and current and current["clean_rows"]
                    and current["language"] == run["language"]):
                return self._cached_processed(app_id)
            catalog = self.catalog()
            raw = (api_row(row, app_id, catalog.get(app_id)) for page in raw_pages(directory, run)
                   for row in parse_page(page)[0])
            context = {
                "source": "api", "app_id": app_id, "run_id": run["run_id"], "language": run["language"],
                "data_status": run["status"],
                "collection_status": (attempt["status"] if attempt
                                      and attempt.get("review_type", 0) == 0 else run["status"]),
                "collected_at_utc": run["finished_at_utc"], "sort": run["sort"], "limit": run["limit"],
                "cache_used": collection["cache_used"] if collection else True,
                "error": (attempt.get("error") if attempt and attempt.get("review_type", 0) == 0 else run.get("error")),
            }
            prepared = prepare(raw, catalog, language=run["language"])
            records = prepared[0]
            report = build_report(*prepared, context)
            if not report["passed"]:
                raise ValueError("Quality validation failed; no output was published")
            for warning in report["warnings"]:
                LOG.warning("App %s: %s", app_id, warning)
            result = self._publish_game(app_id, records, context, encoding, report)
            if result["preserved"]:
                save_report(self._processed(app_id) / "rejected" / run["run_id"], report)
                return {**self._cached_processed(app_id), "preserved": True, "preprocessing_success": False}
            return result

    @staticmethod
    def _shortage(status, target):
        available = status["review_count"]
        if available >= target:
            return None
        if status.get("total_matching") is not None and status["total_matching"] < target:
            return f"Steam reports only {status['total_matching']} matching reviews"
        if status["collection_status"] != "complete":
            return status.get("error") or f"collection ended with {status['collection_status']} status"
        return "the filtered Steam result was exhausted before the target"

    def collect_balanced_reviews(self, app_id: int, positive_limit=500, negative_limit=500, *,
                                 refresh=False, language="english", sort=1,
                                 max_requests=2000, use_key=False) -> dict:
        """Collect independent positive/negative API runs without changing Recent cache semantics."""
        for label, value in (("positive_limit", positive_limit), ("negative_limit", negative_limit)):
            if type(value) is not int or not 1 <= value <= 25000:
                raise ValueError(f"{label} must be between 1 and 25000")
        positive = self.collect_reviews(
            app_id, positive_limit, refresh=refresh, resume=not refresh, language=language,
            sort=sort, max_requests=max_requests, use_key=use_key, review_type=1,
        )
        negative = self.collect_reviews(
            app_id, negative_limit, refresh=refresh, resume=not refresh, language=language,
            sort=sort, max_requests=max_requests, use_key=use_key, review_type=2,
        )
        matching_positive = positive.get("total_matching")
        matching_negative = negative.get("total_matching")
        matching_total = (
            matching_positive + matching_negative
            if matching_positive is not None and matching_negative is not None else None
        )
        errors = [item.get("error") for item in (positive, negative) if item.get("error")]
        shortages = {
            "positive": self._shortage(positive, positive_limit),
            "negative": self._shortage(negative, negative_limit),
        }
        shortages = {key: value for key, value in shortages.items() if value}
        request_count = sum(
            0 if item["cache_used"] else item.get("last_attempt", {}).get("requests", 0)
            for item in (positive, negative)
        )
        source_requests = sum(item.get("last_attempt", {}).get("requests", 0)
                              for item in (positive, negative))
        return {
            "app_id": app_id, "game_name": positive.get("game_name") or negative.get("game_name"),
            "sample_mode": "balanced", "source": "api", "language": language, "sort": sort,
            "collection_status": ("complete" if all(item["collection_status"] == "complete"
                                                       for item in (positive, negative)) else "partial"),
            "cache_used": positive["cache_used"] and negative["cache_used"],
            "target_counts": {"positive": positive_limit, "negative": negative_limit},
            "collected_counts": {"positive": positive["review_count"], "negative": negative["review_count"]},
            "raw_counts": {"positive": positive["raw_count"], "negative": negative["raw_count"]},
            "source_run_ids": {"positive": positive["run_id"], "negative": negative["run_id"]},
            "matching_population": {
                "positive": matching_positive, "negative": matching_negative, "total": matching_total,
                "positive_ratio": (matching_positive / matching_total if matching_total else None),
                "negative_ratio": (matching_negative / matching_total if matching_total else None),
            },
            "requests": request_count, "source_requests": source_requests,
            "duplicates_removed_during_collection": sum(
                (item["raw_count"] or 0) - item["review_count"] for item in (positive, negative)
            ),
            "shortages": shortages, "error": "; ".join(errors) or None,
            "api_limit_error": any("429" in error for error in errors),
            "positive_collection": positive, "negative_collection": negative,
        }

    def preprocess_balanced_reviews(self, app_id: int, collection, encoding="utf-8-sig") -> dict:
        directory = self._raw(app_id)
        with writer_lock(directory):
            state = read_json(directory / "state.json", {})
            run_ids = collection["source_run_ids"]
            runs = {name: active_run(state, review_type) for name, review_type in
                    (("positive", 1), ("negative", 2))}
            if any(not run or run["run_id"] != run_ids[name] for name, run in runs.items()):
                raise CollectionError("Balanced source collections changed. Read their latest status and retry.")
            catalog = self.catalog()
            raw_rows = []
            label_mismatches = {"positive": 0, "negative": 0}
            for name, run in runs.items():
                expected = name == "positive"
                for page in raw_pages(directory, run):
                    for row in parse_page(page)[0]:
                        if row.get("voted_up") is not expected:
                            label_mismatches[name] += 1
                            continue
                        raw_rows.append(api_row(row, app_id, catalog.get(app_id)))
            prepared = prepare(raw_rows, catalog, language=collection["language"])
            records = interleave_labels(prepared[0])
            positive = sum(row["voted_up"] for row in records)
            selected = {"positive": positive, "negative": len(records) - positive}
            targets = collection["target_counts"]
            shortages = dict(collection["shortages"])
            for name in ("positive", "negative"):
                if selected[name] < targets[name] and name not in shortages:
                    missing = targets[name] - selected[name]
                    reasons = []
                    if label_mismatches[name]:
                        reasons.append(
                            f"{label_mismatches[name]} Steam {name} filter rows had mismatched voted_up labels"
                        )
                    preprocessing_removed = missing - label_mismatches[name]
                    if preprocessing_removed:
                        reasons.append(f"{preprocessing_removed} reviews were removed during preprocessing")
                    shortages[name] = "; ".join(reasons)
            sampling = {
                "mode": "balanced", "target_counts": targets,
                "raw_collected_counts": collection["collected_counts"],
                "selected_counts": selected,
                "selected_ratios": {
                    "positive": positive / len(records) if records else None,
                    "negative": (len(records) - positive) / len(records) if records else None,
                },
                "matching_population": collection["matching_population"],
                "source_run_ids": run_ids, "requests": collection["source_requests"],
                "requests_this_call": collection["requests"],
                "duplicates_removed": prepared[2].get("duplicate_id", 0),
                "filter_label_mismatches": label_mismatches,
                "shortages": shortages,
                "is_population_representative": False,
                "note": ("The balanced sample ratio is an analysis design choice and must not be "
                         "interpreted as the Steam population recommendation ratio."),
            }
            run_id = f"balanced:{run_ids['positive']}:{run_ids['negative']}"
            context = {
                "source": "api", "app_id": app_id, "run_id": run_id,
                "language": collection["language"], "data_status": collection["collection_status"],
                "collection_status": collection["collection_status"], "collected_at_utc": now(),
                "sort": collection["sort"], "limit": sum(targets.values()),
                "cache_used": collection["cache_used"], "error": collection["error"],
                "sampling": sampling,
            }
            report = build_report(records, prepared[1], prepared[2], prepared[3], prepared[4], context)
            if not report["passed"]:
                raise ValueError("Quality validation failed; no balanced output was published")
            for warning in report["warnings"]:
                LOG.warning("App %s balanced sample: %s", app_id, warning)
            return self._publish_game(app_id, records, context, encoding, report)

    def _cached_processed(self, game):
        directory = self._processed(game)
        current = read_json(directory / "current.json")
        if not current:
            raise CollectionError("No processed data is available for this app")
        snapshot = directory / current["generation"]
        report = snapshot / "quality_report.json"
        return {**current, "csv_path": str(snapshot / EXPORT),
                "report_path": str(report) if report.exists() else None, "cache_used": True}

    def get_processed_reviews(self, app_id: int):
        """Return a pandas DataFrame with stable review IDs and nullable metadata types."""
        return self._read_processed(self._cached_processed(app_id))

    @staticmethod
    def _read_processed(result):
        import pandas as pd

        rows = read_export(Path(result["csv_path"]))
        types = {
            "review_id": "string", "voted_up": "bool", "app_id": "uint32", "sentiment": "int8",
            "text_length": "int64", "word_count": "int64", "weighted_vote_score": "Float64",
            **dict.fromkeys(INTEGER_FIELDS, "UInt64"), **dict.fromkeys(BOOLEAN_FIELDS, "boolean"),
        }
        return pd.DataFrame({
            field: pd.Series([row[field] for row in rows], dtype=types.get(field, "object"))
            for field in COLUMNS
        })

    def get_reviews(self, app_id: int, limit: int, refresh: bool, sample_mode="recent"):
        """Adapter for the analysis team's ReviewDataAdapter protocol."""
        if sample_mode == "balanced":
            return self.get_balanced_reviews(app_id, limit, refresh)
        if sample_mode != "recent":
            raise ValueError("sample_mode must be recent or balanced")
        collection = self.collect_reviews(app_id, limit, refresh=refresh, resume=not refresh)
        current = read_json(self._processed(app_id) / "current.json")
        if not current or collection["run_id"] != current["raw_run_id"]:
            result = self.preprocess_reviews(app_id, collection=collection)
        else:
            result = self._cached_processed(app_id)
        if result["language"] != collection["language"]:
            raise CollectionError("No compatible processed data is available for the requested language")
        frame = self._read_processed(result).head(limit)
        metadata = {
            **collection, "source": result["source"], "data_source": result["source"],
            "processed_rows": len(frame),
            "cache_used": collection["cache_used"] or result.get("cache_used", False),
            "preprocessing_success": result["preprocessing_success"],
            "processed_matches_raw": bool(collection["run_id"] and collection["run_id"] == result["raw_run_id"]),
            "processed_at_utc": result["processed_at_utc"], "processed_run_id": result["raw_run_id"],
        }
        return frame, metadata

    def get_balanced_reviews(self, app_id: int, limit=1000, refresh=False):
        """Return an approximately 50:50 analysis sample with explicit population metadata."""
        if type(limit) is not int or not 2 <= limit <= 50000:
            raise ValueError("balanced limit must be between 2 and 50000")
        positive_target = limit // 2
        negative_target = limit - positive_target
        collection = self.collect_balanced_reviews(
            app_id, positive_target, negative_target, refresh=refresh,
        )
        current = read_json(self._processed(app_id) / "current.json")
        current_sampling = (current or {}).get("sampling") or {}
        if (not current or current_sampling.get("mode") != "balanced"
                or current_sampling.get("target_counts") != collection["target_counts"]
                or current_sampling.get("source_run_ids") != collection["source_run_ids"]):
            result = self.preprocess_balanced_reviews(app_id, collection)
        else:
            result = self._cached_processed(app_id)
        frame = self._read_processed(result).head(limit)
        sampling = result["sampling"]
        run_id = f"balanced:{collection['source_run_ids']['positive']}:{collection['source_run_ids']['negative']}"
        metadata = {
            "app_id": app_id, "game_name": collection["game_name"], "source": "api", "data_source": "api",
            "sample_mode": "balanced", "collection_status": collection["collection_status"],
            "data_status": collection["collection_status"], "language": collection["language"],
            "cache_used": collection["cache_used"] or result.get("cache_used", False),
            "run_id": run_id, "review_count": sum(collection["collected_counts"].values()),
            "raw_count": sum((value or 0) for value in collection["raw_counts"].values()),
            "processed_rows": len(frame), "preprocessing_success": result["preprocessing_success"],
            "processed_matches_raw": sampling["source_run_ids"] == collection["source_run_ids"],
            "processed_at_utc": result["processed_at_utc"], "processed_run_id": result["raw_run_id"],
            "sampling": sampling, "requests": collection["requests"],
            "api_limit_error": collection["api_limit_error"], "error": collection["error"],
        }
        return frame, metadata

    def preprocess_csv(self, path, mapping=None, *, game_id=None, language="english",
                       declared_language=None, encoding="utf-8-sig", dataset=None):
        if game_id is not None:
            require_app_id(game_id)
        language = select_language(language)
        if declared_language is not None:
            declared_language = select_language(declared_language)
            if declared_language == "all":
                raise ValueError("Declared CSV language must be one language")
        path = Path(path)
        context = {"source": "csv", "dataset": dataset or path.name, "language": language,
                   "declared_language": declared_language, "cache_used": False}
        catalog = self.catalog()
        prepared = prepare(csv_rows(path, mapping, game_id=game_id, declared_language=declared_language),
                           catalog, language=language)
        records = prepared[0]
        report = build_report(*prepared, context)
        if not report["passed"]:
            raise ValueError("Quality validation failed; no output was published")
        for warning in report["warnings"]:
            LOG.warning("CSV: %s", warning)
        exported = self.export(records, report, encoding)
        groups = {}
        for row in records:
            groups.setdefault(row["app_id"], []).append(row)
        for game, group in groups.items():
            with writer_lock(self._raw(game)):
                self._publish_game(game, group, context, encoding)
        return {**report, "exported_default": exported}

    def export(self, records, report, encoding="utf-8-sig"):
        directory = self.root / "data/processed"
        destination = directory / EXPORT
        with writer_lock(directory):
            if not records and destination.exists() and read_export(destination):
                save_report(self.root / "reports/rejected" / uuid4().hex, report)
                return False
            write_csv(destination, records, encoding)
            with destination.open("rb") as file:
                digest = file_digest(file, "sha256").hexdigest()
            save_report(self.root / "reports", {**report, "export_sha256": digest})
        return True

    def export_game(self, result, encoding):
        if not result["report_path"]:
            return False
        records = read_export(Path(result["csv_path"]))
        report = read_json(Path(result["report_path"]))
        return self.export(records, report, encoding)


_default = ReviewPipeline()
search_games = _default.search_games
collect_reviews = _default.collect_reviews
preprocess_reviews = _default.preprocess_reviews
get_processed_reviews = _default.get_processed_reviews
get_collection_status = _default.get_collection_status
get_reviews = _default.get_reviews
get_balanced_reviews = _default.get_balanced_reviews
