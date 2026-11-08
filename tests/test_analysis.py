import json

import pandas as pd
import pytest

from src.analysis.clustering import cluster_reviews
from src.analysis.config import AnalysisConfig, ClusteringConfig, PriorityWeights, TfidfConfig
from src.analysis.exceptions import ClusteringError, EmptyVocabularyError, InputValidationError
from src.analysis.issue_detection import add_issue_types, classify_text, detect_complaint
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
    assert classify_text("A poetic adventure") == []


@pytest.mark.parametrize(("text", "complaint", "issues"), [
    ("I love the gameplay", False, []),
    ("I haven't encountered any bugs", False, []),
    ("Great game, but it still has bugs", True, ["Bugs / Crashes"]),
    ("I cannot finish the quest", True, ["Bugs / Crashes", "Gameplay"]),
    ("The game runs slowly even on low settings", True, ["Performance / Optimization"]),
])
def test_complaint_context_rules(text, complaint, issues):
    assert detect_complaint(text) is complaint
    assert classify_text(text) == issues


@pytest.mark.parametrize(("text", "complaint", "issues"), [
    ("Combat feels responsive and fun", False, []),
    ("No crashes anymore and performance is great", False, []),
    ("The inventory menu is confusing", True, ["UI / Usability"]),
    ("The quest is stuck and I cannot progress", True, ["Bugs / Crashes", "Gameplay"]),
    ("It is overpriced and not worth the money", True, ["Monetization"]),
])
def test_complaint_rules_on_holdout_synthetic_phrases(text, complaint, issues):
    assert detect_complaint(text) is complaint
    assert classify_text(text) == issues


@pytest.mark.parametrize(("text", "issue"), [
    ("The game won't launch after the loading screen", "Bugs / Crashes"),
    ("The game doesnt even start after the patch", "Bugs / Crashes"),
    ("Enemy AI is dumb and ruins combat", "Gameplay"),
    ("Enemy AI still has major flaws", "Gameplay"),
    ("The HUD is confusing", "UI / Usability"),
    ("Key rebinding issues make the controls frustrating", "UI / Usability"),
    ("Hardware compatibility issues make it unplayable on older GPUs", "Performance / Optimization"),
    ("The update is unplayable if you use an old graphics card", "Performance / Optimization"),
    ("This edition costs too much", "Monetization"),
    ("The story is poorly written", "Story / Narrative"),
    ("Story choices rarely matter", "Story / Narrative"),
    ("There is too much dialogue", "Story / Dialogue Length"),
    ("There is too much unnecessary text", "Story / Dialogue Length"),
    ("Exploration is limited and the open world feels lifeless", "Content / Open World"),
    ("Character customization is disappointing", "Customization"),
    ("Character customization is quite limited", "Customization"),
    ("I wish we could customize vehicles", "Customization"),
    ("There is no developer communication", "Developer Support"),
    ("The developers do not seem to fix reported problems", "Developer Support"),
    ("They don't even seem to address reported issues", "Developer Support"),
    ("Quest design is confusing", "Quest / Progression Design"),
    ("Waiting forever to trigger new missions is frustrating", "Quest / Progression Design"),
])
def test_high_confidence_issue_expressions(text, issue):
    assert detect_complaint(text) is True
    assert issue in classify_text(text)


@pytest.mark.parametrize("text", [
    "The game launches quickly and loading is smooth",
    "Enemy AI is smart and combat is fun",
    "The HUD and inventory are easy to use",
    "It runs well on my older graphics card",
    "The price is fair and worth the money",
    "The story and writing are excellent",
    "The dialogue is concise and enjoyable",
    "The open world is beautiful and exploration is rewarding",
    "Character customization is excellent",
    "The developers communicate and release useful fixes",
    "Quest design and mission pacing are great",
])
def test_issue_nouns_in_praise_are_not_issues(text):
    assert detect_complaint(text) is False
    assert classify_text(text) == []


@pytest.mark.parametrize("text", ["The game is not interesting", "This game sux"])
def test_clear_short_complaints_remain_unclassified_issues(text):
    assert detect_complaint(text) is True
    assert classify_text(text) == ["Other / Unclassified"]


@pytest.mark.parametrize("text", [
    "The black screen was fixed",
    "The HUD is not confusing",
    "The missions aren't repetitive",
    "The price isn't expensive",
    "The story isn't bad",
    "The dialogue is not too long",
    "Exploration is not limited",
    "Customization is not disappointing",
])
def test_negated_or_resolved_quality_problems_are_not_issues(text):
    assert detect_complaint(text) is False
    assert classify_text(text) == []


def test_add_issue_types_separates_complaint_from_steam_vote():
    frame = pd.DataFrame({
        "review_clean": ["great game but it still has bugs", "i love the gameplay"],
        "voted_up": [True, False],
    })
    result = add_issue_types(frame)
    assert result["is_complaint"].tolist() == [True, False]
    assert result["issue_types"].tolist() == [["Bugs / Crashes"], []]


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
    priorities = calculate_priorities(add_issue_types(frame))
    scores = [p["priority_score"] for p in priorities]
    assert all(0 <= score <= 1 for score in scores)
    assert scores == sorted(scores, reverse=True)
    assert all("score_basis" in item for item in priorities)


def test_new_issue_categories_flow_to_priorities_with_representative_reviews():
    frame = pd.DataFrame([
        {"review_id": 1, "review_text": "The story is poorly written", "review_clean": "the story is poorly written", "voted_up": False},
        {"review_id": 2, "review_text": "Character customization is limited", "review_clean": "character customization is limited", "voted_up": False},
        {"review_id": 3, "review_text": "The story is excellent", "review_clean": "the story is excellent", "voted_up": True},
    ])
    priorities = calculate_priorities(add_issue_types(analyze_sentiment(frame)))
    by_type = {item["issue_type"]: item for item in priorities}

    assert by_type["Story / Narrative"]["review_count"] == 1
    assert by_type["Customization"]["review_count"] == 1
    assert by_type["Story / Narrative"]["representative_reviews"][0]["review_id"] == 1
    assert by_type["Customization"]["representative_reviews"][0]["review_id"] == 2
    assert all(item["issue_type"] != "Other / Unclassified" for item in priorities)


def test_invalid_priority_weights():
    with pytest.raises(ValueError):
        PriorityWeights(0.5, 0.5, 0.5).validate()
