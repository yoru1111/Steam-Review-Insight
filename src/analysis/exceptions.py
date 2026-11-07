class AnalysisError(ValueError):
    """Base error for invalid or non-analyzable data."""


class InputValidationError(AnalysisError):
    pass


class EmptyVocabularyError(AnalysisError):
    pass


class ClusteringError(AnalysisError):
    pass
