from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class TfidfConfig:
    max_features: int = 5000
    min_df: int | float = 1
    max_df: int | float = 0.95
    ngram_range: tuple[int, int] = (1, 2)


@dataclass(slots=True)
class ClusteringConfig:
    k: int = 5
    random_state: int = 42
    top_keywords: int = 10
    representative_reviews: int = 3
    silhouette_sample_size: int = 2000
    minibatch_threshold: int = 10000


@dataclass(slots=True)
class SentimentConfig:
    positive_threshold: float = 0.05
    negative_threshold: float = -0.05


@dataclass(slots=True)
class PriorityWeights:
    frequency: float = 0.4
    negative_ratio: float = 0.3
    negative_severity: float = 0.3

    def validate(self) -> None:
        values = (self.frequency, self.negative_ratio, self.negative_severity)
        if any(x < 0 for x in values) or abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("Priority weights must be non-negative and sum to 1.0")


@dataclass(slots=True)
class AnalysisConfig:
    tfidf: TfidfConfig = field(default_factory=TfidfConfig)
    clustering: ClusteringConfig = field(default_factory=ClusteringConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    priority_weights: PriorityWeights = field(default_factory=PriorityWeights)
    # Issues raised by fewer reviews than this are flagged as thin evidence and ranked after the rest.
    min_priority_reviews: int = 3

    def __post_init__(self) -> None:
        self.priority_weights.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
