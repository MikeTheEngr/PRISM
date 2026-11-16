"""
PRISM Backend — Main Application

Unified backend serving the waitlist, market data, AI signals, and
watchlist endpoints. Built to expand into the full Phase 1 API as
auth and additional features come online.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.api import waitlist, assets, signals, watchlist, auth

settings = get_settings()

app = FastAPI(
    title="PRISM Backend",
    version="0.2.0",
    description="AI-powered predictive intelligence across crypto and stocks.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.ALLOWED_ORIGINS_REGEX,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(waitlist.router)
app.include_router(assets.router)
app.include_router(signals.router)
app.include_router(watchlist.router)


@app.on_event("startup")
async def validate_config():
    """Fail loudly at startup if critical config is missing, rather than
    failing mysteriously on the first real request."""
    missing = settings.validate()
    if missing:
        print(f"⚠️  WARNING: Missing required environment variables: {missing}")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all so an unexpected error never leaks a raw stack trace to a client —
    important for a financial product where internals shouldn't be exposed.
    """
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again."},
    )


@app.get("/")
def root():
    return {"service": "PRISM Backend", "status": "online", "version": "0.2.0"}


@app.get("/health")
def health():
    settings_check = get_settings()
    missing = settings_check.validate()
    return {
        "status": "ok" if not missing else "degraded",
        "missing_config": missing,
    }
