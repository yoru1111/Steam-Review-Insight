import json

import pandas as pd
import pytest

from src.analysis.clustering import cluster_reviews
from src.analysis.config import AnalysisConfig, ClusteringConfig, PriorityWeights, TfidfConfig
from src.analysis.exceptions import ClusteringError, EmptyVocabularyError, InputValidationError
from src.analysis.issue_detection import classify_text
from src.analysis.pipeline import analyze_reviews
from src.analysis.priority import calculate_priorities
from src.analysis.sentiment import analyze_sentiment
from src.analysis.tfidf import vectorize_reviews


def test_tfidf_normal(reviews_df):
    vectors, vectorizer = vectorize_reviews(reviews_df, TfidfConfig(ngram_range=(1, 2)))
    assert vectors.shape[0] == len(reviews_df)
    assert "crash" in vectorizer.get_feature_names_out()


def test_tfidf_preserves_negation():
    df = pd.DataFrame({"review_clean": ["not good game", "never bad game"]})
    _, vectorizer = vectorize_reviews(df)
    assert {"not", "never"} <= set(vectorizer.get_feature_names_out())


def test_tfidf_small_collection():
    df = pd.DataFrame({"review_clean": ["great game", "bad crash"]})
    vectors, _ = vectorize_reviews(df)
    assert vectors.shape[0] == 2


def test_empty_vocabulary():
    with pytest.raises(EmptyVocabularyError):
        vectorize_reviews(pd.DataFrame({"review_clean": ["", None, "the and"]}))


def test_missing_column_and_empty_frame(reviews_df):
    with pytest.raises(InputValidationError):
        analyze_reviews(reviews_df.drop(columns=["review_text"]))
    with pytest.raises(InputValidationError):
        analyze_reviews(reviews_df.iloc[0:0])


def test_voted_up_must_be_boolean(reviews_df):
    as_strings = reviews_df.assign(voted_up=reviews_df["voted_up"].map(str))
    with pytest.raises(InputValidationError, match="voted_up"):
        analyze_reviews(as_strings)


def test_k_greater_than_reviews(reviews_df):
    vectors, _ = vectorize_reviews(reviews_df.head(2))
    with pytest.raises(ClusteringError):
        cluster_reviews(vectors, ClusteringConfig(k=3))


def test_cluster_count_and_assignments(reviews_df):
    vectors, _ = vectorize_reviews(reviews_df)
    labels, _, _, _ = cluster_reviews(vectors, ClusteringConfig(k=4))
    assert len(labels) == len(reviews_df)
    assert 1 < len(set(labels)) <= 4


def test_sentiment_does_not_overwrite_steam_label(reviews_df):
    original = reviews_df["sentiment"].copy()
    result = analyze_sentiment(reviews_df)
    assert result["sentiment"].equals(original)
    assert result.loc[3, "sentiment_score"] > 0
    assert result.loc[0, "sentiment_label"] == "Negative"


def test_issue_multilabel_and_unclassified():
    assert classify_text("Crash and low FPS performance") == ["Bugs / Crashes", "Performance / Optimization"]
    assert classify_text("A poetic adventure") == ["Other / Unclassified"]


def test_pipeline_result_and_json(reviews_df):
    config = AnalysisConfig()
    config.clustering.k = 4
    result = analyze_reviews(reviews_df, config)
    assert result["summary"]["review_count"] == len(reviews_df)
    assert sum(c["review_count"] for c in result["clusters"]) == len(reviews_df)
    assert all(c["keywords"] and c["representative_reviews"] for c in result["clusters"])
    assert json.loads(json.dumps(result))["game"]["app_id"] == 999


def test_priorities_range_and_order(reviews_df):
    frame = analyze_sentiment(reviews_df)
    from src.analysis.issue_detection import add_issue_types
    priorities = calculate_priorities(add_issue_types(frame))
    scores = [p["priority_score"] for p in priorities]
    assert all(0 <= score <= 1 for score in scores)
    assert scores == sorted(scores, reverse=True)
    assert all("score_basis" in item for item in priorities)


def test_invalid_priority_weights():
    with pytest.raises(ValueError):
        PriorityWeights(0.5, 0.5, 0.5).validate()
