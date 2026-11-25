from typing import Literal
from datetime import date

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    app_id: int = Field(gt=0)
    limit: int = Field(default=1000, ge=2, le=10000)
    k: int = Field(default=5, ge=2, le=50)
    refresh: bool = False
    sample_mode: Literal["recent", "balanced"] = "recent"


class CompareRequest(BaseModel):
    app_id: int = Field(gt=0, le=2**32 - 1)
    reference_date: date
    window_days: int = Field(default=14, ge=1, le=365)
    timezone: str = Field(default="Asia/Seoul", max_length=80)
    language: str = Field(default="english", min_length=2, max_length=24)
    limit_per_period: int = Field(default=1000, ge=2, le=10000)
    sample_mode: Literal["recent", "balanced"] = "recent"
    minimum_required_count: int = Field(default=30, ge=1, le=10000)
    refresh: bool = False
