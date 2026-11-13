from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .clustering import cluster_reviews, summarize_clusters
from .config import AnalysisConfig
from .exceptions import InputValidationError
from .issue_detection import add_issue_types, annotate_cluster_types
from .positive_aspects import add_positive_aspects, summarize_positive_aspects
from .priority import calculate_priorities
from .sentiment import analyze_sentiment
from .tfidf import vectorize_reviews

REQUIRED_COLUMNS = {"review_text", "review_clean", "voted_up"}


def analyze_reviews(df: pd.DataFrame, config: AnalysisConfig | None = None,
                    metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the in-memory analysis pipeline and return JSON-safe built-in values."""
    config = config or AnalysisConfig()
    _validate(df)
    working = df.reset_index(drop=True).copy()
    working = analyze_sentiment(working, config.sentiment)
    vectors, vectorizer = vectorize_reviews(working, config.tfidf)
    labels, model, silhouette, warnings = cluster_reviews(vectors, config.clustering)
    working["cluster_id"] = labels
    working = add_issue_types(working)
    working = add_positive_aspects(working)
    clusters = summarize_clusters(working, vectors, vectorizer, model, config.clustering)
    annotate_cluster_types(clusters, working)
    priorities = calculate_priorities(working, config.priority_weights, config.clustering.representative_reviews,
                                      config.min_priority_reviews)
    positive_aspects = summarize_positive_aspects(working, config.clustering.representative_reviews)

    voted = working["voted_up"].astype(bool)
    labels_count = working["sentiment_label"].value_counts()
    first = working.iloc[0]
    meta = metadata or {}
    result = {
        "game": {"app_id": _native(meta.get("app_id", first.get("app_id"))),
                 "name": meta.get("game_name", first.get("game_name"))},
        "summary": {"review_count": int(len(working)), "positive_ratio": float(voted.mean()),
                    "negative_ratio": float((~voted).mean())},
        "sentiment": {"positive": int(labels_count.get("Positive", 0)),
                      "neutral": int(labels_count.get("Neutral", 0)),
                      "negative": int(labels_count.get("Negative", 0)),
                      "average_compound": float(working["sentiment_score"].mean())},
        "clustering": {"requested_k": config.clustering.k, "formed_clusters": len(clusters),
                       "silhouette_score": silhouette},
        "clusters": clusters,
        "priorities": priorities,
        "positive_aspects": positive_aspects,
        "metadata": {"analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
                     "data_source": meta.get("data_source", "in_memory_dataframe"),
                     "cache_used": bool(meta.get("cache_used", False)),
                     "sample_mode": meta.get("sample_mode", "recent"),
                     "sampling": meta.get("sampling"), "config": config.to_dict()},
        "warnings": warnings + [
            "VADER may misread sarcasm, game-domain terminology, and context.",
            "Issue labels and priority scores are explainable heuristics, not objective defect severity.",
        ],
    }
    return result


def _validate(df: pd.DataFrame) -> None:
    if not isinstance(df, pd.DataFrame):
        raise InputValidationError("Input must be a pandas DataFrame")
    if df.empty:
        raise InputValidationError("Input DataFrame is empty")
    missing = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise InputValidationError(f"Required columns missing: {', '.join(missing)}")
    # astype(bool) turns any non-empty string (e.g. "False") into True, so require a real bool column.
    if not pd.api.types.is_bool_dtype(df["voted_up"]):
        raise InputValidationError(f"voted_up must be a boolean column, got dtype {df['voted_up'].dtype}")


def _native(value: Any) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value
