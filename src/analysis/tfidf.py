import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import TfidfConfig
from .exceptions import EmptyVocabularyError, InputValidationError


def vectorize_reviews(df: pd.DataFrame, config: TfidfConfig | None = None) -> tuple[csr_matrix, TfidfVectorizer]:
    config = config or TfidfConfig()
    if "review_clean" not in df:
        raise InputValidationError("Required column missing: review_clean")
    if df.empty:
        raise InputValidationError("No reviews to vectorize")
    texts = df["review_clean"].fillna("").astype(str).str.strip()
    if not texts.str.contains(r"\w", regex=True).any():
        raise EmptyVocabularyError("review_clean contains no usable terms")
    max_df = 1.0 if isinstance(config.max_df, float) and len(texts) < 3 else config.max_df
    stop_words = sorted(set(ENGLISH_STOP_WORDS) - {"no", "not", "nor", "never"})
    vectorizer = TfidfVectorizer(
        max_features=config.max_features, min_df=config.min_df, max_df=max_df,
        ngram_range=config.ngram_range, stop_words=stop_words, strip_accents="unicode",
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z']+\b",
    )
    try:
        vectors = vectorizer.fit_transform(texts)
    except ValueError as exc:
        if "vocabulary" in str(exc).lower() or "terms remain" in str(exc).lower():
            raise EmptyVocabularyError(f"Unable to build TF-IDF vocabulary: {exc}") from exc
        raise
    if vectors.shape[1] == 0:
        raise EmptyVocabularyError("TF-IDF produced zero features")
    return vectors.tocsr(), vectorizer
