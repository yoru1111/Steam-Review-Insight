from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    app_id: int = Field(gt=0)
    limit: int = Field(default=1000, ge=2, le=10000)
    k: int = Field(default=5, ge=2, le=50)
    refresh: bool = False
    sample_mode: Literal["recent", "balanced"] = "recent"
