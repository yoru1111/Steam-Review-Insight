import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .config import SentimentConfig
from .exceptions import InputValidationError


def analyze_sentiment(df: pd.DataFrame, config: SentimentConfig | None = None) -> pd.DataFrame:
    config = config or SentimentConfig()
    if "review_text" not in df:
        raise InputValidationError("Required column missing: review_text")
    analyzer = SentimentIntensityAnalyzer()
    result = df.copy()
    scores = result["review_text"].fillna("").astype(str).map(
        lambda text: float(analyzer.polarity_scores(text)["compound"])
    )
    result["sentiment_score"] = scores
    result["sentiment_label"] = scores.map(
        lambda x: "Positive" if x >= config.positive_threshold else "Negative" if x <= config.negative_threshold else "Neutral"
    )
    return result
