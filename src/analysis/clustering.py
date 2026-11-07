from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

from .config import ClusteringConfig
from .exceptions import ClusteringError


def cluster_reviews(vectors: csr_matrix, config: ClusteringConfig | None = None):
    config = config or ClusteringConfig()
    count = vectors.shape[0]
    if config.k < 2:
        raise ClusteringError("k must be at least 2")
    if count < config.k:
        raise ClusteringError(f"Review count ({count}) is smaller than k ({config.k})")
    model_cls = MiniBatchKMeans if count >= config.minibatch_threshold else KMeans
    kwargs: dict[str, Any] = {"n_clusters": config.k, "random_state": config.random_state, "n_init": 10}
    if model_cls is MiniBatchKMeans:
        kwargs["batch_size"] = min(1024, count)
    model = model_cls(**kwargs)
    labels = model.fit_predict(vectors).astype(int)
    warnings: list[str] = []
    unique = np.unique(labels)
    if len(unique) < config.k:
        warnings.append(f"Requested {config.k} clusters, but only {len(unique)} distinct clusters formed.")
    score = None
    if 1 < len(unique) < count:
        sample_size = min(config.silhouette_sample_size, count)
        score = float(silhouette_score(vectors, labels, sample_size=sample_size if sample_size < count else None,
                                       random_state=config.random_state))
        if score < 0.05:
            warnings.append("Silhouette score is very low; cluster separation may be weak.")
    else:
        warnings.append("Silhouette score is unavailable because distinct clusters did not form.")
    return labels, model, score, warnings


def summarize_clusters(df: pd.DataFrame, vectors: csr_matrix, vectorizer: TfidfVectorizer,
                       model: KMeans | MiniBatchKMeans, config: ClusteringConfig | None = None) -> list[dict[str, Any]]:
    config = config or ClusteringConfig()
    features = np.asarray(vectorizer.get_feature_names_out())
    summaries = []
    for cluster_id in sorted(df["cluster_id"].unique()):
        positions = np.flatnonzero(df["cluster_id"].to_numpy() == cluster_id)
        group = df.iloc[positions]
        center = model.cluster_centers_[cluster_id]
        keywords = features[np.argsort(center)[::-1][:config.top_keywords]].tolist()
        similarities = np.asarray(vectors[positions].dot(center)).ravel()
        chosen = positions[np.argsort(similarities)[::-1][:config.representative_reviews]]
        reviews = [{"review_id": _native(df.iloc[pos].get("review_id")), "text": str(df.iloc[pos]["review_text"])}
                   for pos in chosen]
        voted = group["voted_up"].astype(bool)
        summaries.append({
            "cluster_id": int(cluster_id), "review_count": int(len(group)), "keywords": keywords,
            "positive_ratio": float(voted.mean()), "negative_ratio": float((~voted).mean()),
            "average_sentiment_score": float(group["sentiment_score"].mean()),
            "negative_sentiment_ratio": float((group["sentiment_label"] == "Negative").mean()),
            "representative_reviews": reviews,
        })
    return summaries


def _native(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value
