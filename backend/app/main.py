from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.backtests import router
from app.api.research import router as research_router
from app.api.data_center import router as data_center_router
from app.api.optimizations import router as optimizations_router
from app.api.ma_box import router as ma_box_router
from app.api.ma_breakout_analytics import router as ma_breakout_analytics_router
from app.data.fallback import ProviderChain
from app.data.stooq import StooqDataProvider
from app.data.yahoo import YahooDataProvider
from app.db.repository import BacktestRepository
from app.jobs import JobService
from app.ma_breakout_analytics.repository import AnalyticsRepository


MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))


def _csv_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _database_path(data_dir: Path) -> Path:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return data_dir / "backtests.sqlite3"
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("Only sqlite DATABASE_URL values are supported in this release.")
    raw_path = database_url.removeprefix("sqlite:///")
    return Path(raw_path).resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_root = Path(os.getenv("DATA_DIR", "../data")).resolve()
    cache_root = Path(os.getenv("CACHE_DIR", str(data_root / "cache"))).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    app.state.repository = BacktestRepository(_database_path(data_root))
    # Separate repository/connection and additive analytics-only tables keep
    # event-study records independent from legacy and MA_BOX persistence.
    app.state.ma_breakout_analytics_repository = AnalyticsRepository(_database_path(data_root))
    # Providers own isolated cache namespaces.  The chain checks complete local
    # data before touching either network, then prefers Yahoo and falls back to
    # Stooq without ever merging bars from the two adjustment policies.
    app.state.provider = ProviderChain(
        YahooDataProvider(cache_root),
        StooqDataProvider(cache_root),
    )
    app.state.job_service = JobService(data_root, app.state.provider, app.state.repository)
    app.state.job_service.start()
    try:
        yield
    finally:
        app.state.job_service.stop()


app = FastAPI(title="Backtest Lab API", version="0.1.0", lifespan=lifespan, debug=False)


@app.middleware("http")
async def request_size_limit(request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": {"code": "REQUEST_TOO_LARGE", "message": "Request body is too large."}})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": {"code": "INVALID_CONTENT_LENGTH", "message": "Invalid Content-Length header."}})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_csv_env("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_csv_env("ALLOWED_HOSTS", "*"))
app.include_router(router)
app.include_router(research_router)
app.include_router(data_center_router)
app.include_router(optimizations_router)
app.include_router(ma_box_router)
app.include_router(ma_breakout_analytics_router)


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/data-provider/status")
def data_provider_status(request: Request):
    """Return safe reachability for every configured daily provider."""
    provider = getattr(request.app.state, "provider", None)
    if provider is None or not hasattr(provider, "status"):
        return {"status": "offline", "providers": {}, "preferred_provider": None, "cache_available": False}
    return provider.status()
