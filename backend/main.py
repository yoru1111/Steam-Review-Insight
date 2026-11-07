from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.analysis import AnalysisConfig, analyze_reviews
from src.analysis.exceptions import AnalysisError

from .data_adapter import DataPipelineUnavailable, ReviewDataAdapter, UnavailableDataAdapter
from .schemas import AnalyzeRequest

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def create_app(adapter: ReviewDataAdapter | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.data_adapter = adapter or UnavailableDataAdapter()
        yield

    app = FastAPI(title="Steam Review Insight API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
                       allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "analysis": "ready"}

    @app.get("/api/games/search")
    def search_games(request: Request, query: str = Query(min_length=1, max_length=100)) -> dict[str, Any]:
        try:
            return {"games": request.app.state.data_adapter.search_games(query.strip())}
        except DataPipelineUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Game search failed: {exc}") from exc

    @app.post("/api/analyze")
    def analyze(payload: AnalyzeRequest, request: Request) -> dict[str, Any]:
        try:
            frame, metadata = request.app.state.data_adapter.get_reviews(
                payload.app_id, payload.limit, payload.refresh
            )
            config = AnalysisConfig()
            config.clustering.k = payload.k
            metadata = {**metadata, "app_id": payload.app_id}
            return analyze_reviews(frame, config, metadata)
        except DataPipelineUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except AnalysisError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    @app.get("/api/analyze/status/{job_id}")
    def analysis_status(job_id: str) -> dict[str, str]:
        raise HTTPException(status_code=501, detail="Background analysis jobs are not implemented; /api/analyze is synchronous")

    # Mounted last so /api/* and /docs keep priority; serves frontend/index.html at "/".
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
