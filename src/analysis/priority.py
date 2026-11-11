from typing import Any

import pandas as pd

from .config import PriorityWeights
from .issue_detection import group_by_issue


def calculate_priorities(df: pd.DataFrame, weights: PriorityWeights | None = None,
                         representative_count: int = 3, min_reviews: int = 3) -> list[dict[str, Any]]:
    weights = weights or PriorityWeights()
    weights.validate()
    total = len(df)
    priorities = []
    for issue, positions in group_by_issue(df).items():
        group = df.iloc[positions]
        count = len(group)
        frequency = count / total  # multi-label: issue counts can sum to more than total
        negative_ratio = float((~group["voted_up"].astype(bool)).mean())
        negative_severity = float((-group["sentiment_score"].clip(upper=0)).mean())
        score = weights.frequency * frequency + weights.negative_ratio * negative_ratio + weights.negative_severity * negative_severity
        worst = group.sort_values("sentiment_score").head(representative_count)
        examples = [{"review_id": _native(row.get("review_id")), "text": str(row["review_text"])} for _, row in worst.iterrows()]
        priorities.append({
            "issue_type": issue, "review_count": int(count), "review_ratio": float(frequency),
            "negative_ratio": negative_ratio, "average_sentiment_score": float(group["sentiment_score"].mean()),
            "negative_sentiment_severity": negative_severity, "priority_score": float(min(1.0, max(0.0, score))),
            "sufficient_evidence": bool(count >= min_reviews),
            "representative_reviews": examples,
            "score_basis": {"frequency_score": float(frequency), "negative_review_ratio": negative_ratio,
                            "negative_sentiment_severity": negative_severity,
                            "weights": {"frequency": weights.frequency, "negative_ratio": weights.negative_ratio,
                                        "negative_severity": weights.negative_severity}},
        })
    # A few very negative reviews can top the score, so thin-evidence issues always rank after well-supported ones.
    return sorted(priorities, key=lambda item: (item["sufficient_evidence"], item["priority_score"]), reverse=True)


def _native(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value
