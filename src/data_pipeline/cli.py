"""Command-line entry points for Steam collection and offline preprocessing."""
import argparse
import csv
from hashlib import file_digest
import json
import logging
from pathlib import Path
import sys

from .collector import CollectionError
from .service import EXPORT, ReviewPipeline
from .storage import ROOT, read_json, writer_lock
from .validation import read_export, validate_records


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, default=ROOT, help="Root for local data and reports")
    cli.add_argument("--verbose", action="store_true", help="Log duplicate resolution decisions")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("search").add_argument("query")
    commands.add_parser("status").add_argument("--appid", type=int, required=True)
    commands.add_parser("validate").add_argument("--input", type=Path)

    for command in ("collect", "preprocess", "pipeline"):
        options = commands.add_parser(command)
        options.add_argument("--appid", type=int, required=command == "collect")
        options.add_argument("--language", default="english")
        if command != "preprocess":
            options.add_argument("--limit", type=int, default=1000)
            options.add_argument("--sample-mode", choices=("recent", "balanced"), default="recent")
            options.add_argument("--sort", choices=(1, 2), type=int, default=1)
            options.add_argument("--max-requests", type=int, default=2000)
            options.add_argument("--refresh", action="store_true")
            options.add_argument("--restart", action="store_true", help="Discard resume cursor for this attempt")
            options.add_argument("--use-key", action="store_true")
        if command != "collect":
            options.add_argument("--source", choices=("api", "csv", "cache"))
            options.add_argument("--input", type=Path)
            options.add_argument("--mapping", type=Path, help="JSON mapping of standard fields to CSV headers")
            options.add_argument("--csv-language", help="Explicitly declare the language of CSV rows without a language")
            options.add_argument("--dataset", help="Dataset name or source URL for the quality report")
            options.add_argument("--encoding", choices=("utf-8", "utf-8-sig"), default="utf-8-sig")
    return cli


def emit(result):
    print(json.dumps(result, ensure_ascii=True, indent=2))


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    pipeline = ReviewPipeline(args.root)
    try:
        if args.command == "search":
            emit(pipeline.search_games(args.query))
            return 0
        if args.command == "status":
            emit(pipeline.get_collection_status(args.appid))
            return 0
        if args.command == "validate":
            output = pipeline.root / "data/processed"
            if args.input:
                rows = read_export(args.input)
                checks = validate_records(rows)
            else:
                with writer_lock(output):
                    rows = read_export(output / EXPORT)
                    checks = validate_records(rows)
                    report = read_json(pipeline.root / "reports/quality_report.json")
                    if report is not None:
                        checks["report_row_count_matches"] = len(rows) == report["clean_rows"]
                        checks["report_accounting_passed"] = report["passed"]
                        if "export_sha256" in report:
                            with (output / EXPORT).open("rb") as file:
                                checks["report_export_hash_matches"] = (
                                    file_digest(file, "sha256").hexdigest() == report["export_sha256"]
                                )
            emit({"rows": len(rows), "checks": checks})
            return 0 if all(checks.values()) else 1

        default = "csv" if args.command != "collect" and args.input else (
            "cache" if args.command == "preprocess" else "api"
        )
        source = getattr(args, "source", None) or default
        if source == "csv":
            if not args.input:
                raise ValueError("--input is required for the CSV source")
            if args.mapping and not args.mapping.is_file():
                raise ValueError("CSV column mapping file does not exist")
            report = pipeline.preprocess_csv(
                args.input, read_json(args.mapping) if args.mapping else None,
                game_id=args.appid, language=args.language, declared_language=args.csv_language,
                encoding=args.encoding, dataset=args.dataset,
            )
            emit({key: value for key, value in report.items() if key != "examples"})
            return 0
        if args.appid is None:
            raise ValueError("--appid is required for API and cache sources")
        if getattr(args, "input", None):
            raise ValueError("--input requires the CSV source")
        if source == "api" and args.command == "preprocess":
            raise ValueError("Use pipeline --source api to collect and preprocess")
        collection = None
        if source == "api":
            if args.sample_mode == "balanced":
                positive_target = args.limit // 2
                collection = pipeline.collect_balanced_reviews(
                    args.appid, positive_target, args.limit - positive_target,
                    language=args.language, sort=args.sort, refresh=args.refresh or args.restart,
                    max_requests=args.max_requests, use_key=args.use_key,
                )
            else:
                collection = pipeline.collect_reviews(
                    args.appid, args.limit, language=args.language, sort=args.sort,
                    refresh=args.refresh or args.restart, resume=not args.restart,
                    max_requests=args.max_requests, use_key=args.use_key,
                )
        if args.command == "collect":
            emit(collection)
            return 2 if collection["collection_status"] != "complete" else 0

        result = (
            pipeline.preprocess_balanced_reviews(args.appid, collection, encoding=args.encoding)
            if collection and collection.get("sample_mode") == "balanced"
            else pipeline.preprocess_reviews(args.appid, collection=collection, encoding=args.encoding)
        )
        exported = pipeline.export_game(result, args.encoding)
        emit({"collection": collection or pipeline.get_collection_status(args.appid),
              "processed": result, "exported_default": exported})
        return 2 if collection and collection["collection_status"] != "complete" else 0
    except KeyboardInterrupt:
        logging.error("Interrupted by user")
        return 130
    except (CollectionError, OSError, ValueError, csv.Error, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
