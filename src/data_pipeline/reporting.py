"""Create shareable metrics and local, privacy-masked quality reports."""
from collections import Counter
from html import escape
import platform
from statistics import mean

from .collector import ENDPOINT
from .preprocessing import normalize
from .storage import atomic_text, now, write_json
from .validation import validate_records

RULES = [
    "Decode HTML entities, remove markup and hidden script/style content, apply Unicode NFKC.",
    "Normalize whitespace and remove control characters while retaining emoji and emoticons.",
    "Mask URLs, email, Steam IDs and recognizable phone/IP formats.",
    "Lowercase review_clean and standardize curly apostrophes. Retain negation and technical tokens.",
    "Deduplicate by app_id and review_id, preferring the newest valid updated timestamp.",
    "Exclude invalid IDs, blank text, missing or invalid labels and reviews outside the language filter.",
]
LIMITATIONS = [
    "Steam recommendations define the labels. Text sentiment requires a separate analysis step.",
    "Unknown language is excluded from analysis and counted. Language is based on source metadata.",
    "Privacy masking is pattern-based and cannot identify every name, contact or other personal detail.",
    "Absent and invalid times remain blank. Naive CSV timestamps are interpreted as UTC.",
    "Recent reviews and Steam's default off-topic filter may affect representativeness.",
    "Inspect source terms and masked examples before sharing this report or the exports.",
]


def build_report(records, stats, removed, languages, examples, context):
    count = len(records)
    input_rows = stats.get("input_rows", 0)
    positive = sum(row["voted_up"] for row in records)
    lengths = [row["text_length"] for row in records]
    dates = [row["created_at_utc"] for row in records if row["created_at_utc"]]
    bands = {"1-49": 0, "50-149": 0, "150-499": 0, "500+": 0}
    for length in lengths:
        band = "1-49" if length < 50 else "50-149" if length < 150 else "150-499" if length < 500 else "500+"
        bands[band] += 1
    checks = validate_records(records)
    checks["accounting_matches"] = count + sum(removed.values()) == input_rows == sum(languages.values())
    checks["negation_preserved"] = normalize("Not good. I can’t, won't and don't. No, never.")[1] == (
        "not good. i can't, won't and don't. no, never."
    )
    warnings = []
    if count < 100:
        warnings.append("Fewer than 100 analysis-ready reviews.")
    if count and max(positive, count - positive) / count >= 0.9:
        warnings.append("One recommendation label accounts for at least 90% of retained reviews.")
    if removed:
        warnings.append("Some rows were excluded. See removal reasons.")
    if any(value for key, value in stats.items() if key != "input_rows"):
        warnings.append("Review source diagnostics for missing fields, generated IDs and other anomalies.")
    if context.get("collection_status") in {"partial", "failed", "running"}:
        warnings.append("Latest collection attempt did not complete. See source metadata.")
    if context.get("error"):
        warnings.append("Latest collection or refresh reported an error. See source metadata.")
    return {
        "generated_at_utc": now(), "context": context,
        "environment": {"python": platform.python_version(), "platform": platform.system()},
        "steam_api": ENDPOINT if context["source"] == "api" else None,
        "rules": RULES, "limitations": LIMITATIONS,
        "input_rows": input_rows, "clean_rows": count, "removed_rows": sum(removed.values()),
        "removed_ratio": sum(removed.values()) / input_rows if input_rows else None,
        "removed_by_reason": removed, "source_diagnostics": stats, "raw_language_counts": languages,
        "removed_categories": {
            "missing_text": removed.get("missing_text", 0),
            "duplicate_id": removed.get("duplicate_id", 0),
            "language_exclusions": removed.get("unknown_language", 0) + removed.get("other_language", 0),
            "missing_label": removed.get("missing_label", 0),
        },
        "labels": {"positive": positive, "negative": count - positive,
                   "positive_ratio": positive / count if count else None,
                   "negative_ratio": (count - positive) / count if count else None},
        "by_game": dict(Counter(str(row["app_id"]) for row in records)),
        "by_source": dict(Counter(row["source"] for row in records)),
        "length": {"mean": mean(lengths) if lengths else None, "min": min(lengths, default=None),
                   "max": max(lengths, default=None), "bands": bands},
        "mean_word_count": mean(row["word_count"] for row in records) if count else None,
        "created_at_range_utc": [min(dates, default=None), max(dates, default=None)],
        "examples": examples, "checks": checks, "passed": all(checks.values()), "warnings": warnings,
    }


def table(values):
    lines = ["| Metric | Value |", "| --- | --- |"]
    for label, value in values.items():
        cell = lambda item: escape(str(item)).replace("|", "&#124;").replace("\n", " ")
        lines.append(f"| {cell(label)} | {cell(value)} |")
    return "\n".join(lines)


def bars(values):
    largest = max(values.values(), default=0)
    return table({
        label: f"{'█' * max(1, round(20 * count / largest)) if count else ''} {count}"
        for label, count in values.items()
    })


def save_report(directory, report):
    write_json(directory / "quality_report.json", report)
    sections = [
        ("Source and execution", {**report["context"], **report["environment"], "api": report["steam_api"],
                                  "generated_at_utc": report["generated_at_utc"]}),
        ("Rows", {key: report[key] for key in ("input_rows", "clean_rows", "removed_rows", "removed_ratio")}),
        ("Removal reasons", {**report["removed_categories"], **report["removed_by_reason"]}),
        ("Source diagnostics", report["source_diagnostics"]),
        ("Raw languages", report["raw_language_counts"]),
        ("Recommendation distribution", report["labels"]),
        ("Game distribution", report["by_game"]),
        ("Retained sources", report["by_source"]),
        ("Length distribution", {**report["length"]["bands"],
                                 **{key: report["length"][key] for key in ("mean", "min", "max")},
                                 "mean_word_count": report["mean_word_count"],
                                 "created_at_range_utc": report["created_at_range_utc"]}),
        ("Validation", report["checks"]),
    ]
    with atomic_text(directory / "quality_report.md") as output:
        output.write("# Steam review quality report\n")
        for title, values in sections:
            output.write(f"\n## {title}\n\n{table(values)}\n")
        for title, counts in (
            ("Recommendation counts", {key: report["labels"][key] for key in ("positive", "negative")}),
            ("Review counts by App ID", report["by_game"]),
            ("Review counts by length", report["length"]["bands"]),
        ):
            output.write(f"\n## {title}\n\n{bars(counts)}\n")
        for title, lines in (("Preprocessing", RULES), ("Warnings", report["warnings"]),
                             ("Limitations and analysis handoff", LIMITATIONS)):
            output.write(f"\n## {title}\n\n" + "".join(f"- {line}\n" for line in lines))
        output.write("\n## Masked examples\n\n")
        for example in report["examples"]:
            output.write(table(example) + "\n\n")
