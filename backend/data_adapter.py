from __future__ import annotations

from typing import Any, Protocol

import pandas as pd


class DataPipelineUnavailable(RuntimeError):
    pass


class ReviewDataAdapter(Protocol):
    def search_games(self, query: str) -> list[dict[str, Any]]: ...
    def get_reviews(self, app_id: int, limit: int, refresh: bool,
                    sample_mode: str = "recent") -> tuple[pd.DataFrame, dict[str, Any]]: ...


class UnavailableDataAdapter:
    """Explicit placeholder until the collection/preprocessing team supplies its module."""

    message = "Steam collection/preprocessing adapter is not connected"

    def search_games(self, query: str) -> list[dict[str, Any]]:
        raise DataPipelineUnavailable(self.message)

    def get_reviews(self, app_id: int, limit: int, refresh: bool,
                    sample_mode: str = "recent") -> tuple[pd.DataFrame, dict[str, Any]]:
        raise DataPipelineUnavailable(self.message)


def create_default_adapter() -> ReviewDataAdapter:
    """Build the repository's Steam collection and preprocessing adapter."""
    from src.data_pipeline import ReviewPipeline

    return ReviewPipeline()
