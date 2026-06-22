"""
PRISM Backend — Core Configuration

Centralizes all environment variable access. Nothing else in the codebase
should call os.environ directly — everything goes through this module so
config is validated once, at startup, with clear errors if something's missing.
"""

import os
from pathlib import Path
from functools import lru_cache
from dotenv import load_dotenv

# Load .env explicitly from the project root, rather than relying on the
# current working directory. uvicorn's --reload spawns a subprocess that
# doesn't always inherit the same cwd, which can cause load_dotenv() to
# silently fail to find the file even though it works fine when run directly.
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

class Settings:
    # Supabase
    SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

    # Upstash Redis (caching layer — critical for rate-limited market data APIs)
    UPSTASH_REDIS_URL: str = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_TOKEN: str = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    # Market data providers
    COINGECKO_API_KEY: str = os.environ.get("COINGECKO_API_KEY", "")  # optional, free tier works without
    ALPHA_VANTAGE_API_KEY: str = os.environ.get("ALPHA_VANTAGE_API_KEY", "")

    # AI providers
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

    # App
    ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")
    ALLOWED_ORIGINS_REGEX: str = r"https://.*\.vercel\.app"

    # Cache TTLs (seconds) — tuned per data volatility, not arbitrary
    CACHE_TTL_CRYPTO_PRICE: int = 60          # crypto moves fast, short cache
    CACHE_TTL_STOCK_PRICE: int = 300          # stocks during market hours, 5 min is reasonable
    CACHE_TTL_SIGNAL: int = 1800              # AI signals refresh every 30 min, not per-request

    def validate(self) -> list[str]:
        """Returns a list of missing required config keys. Called at startup."""
        required = {
            "SUPABASE_URL": self.SUPABASE_URL,
            "SUPABASE_SERVICE_KEY": self.SUPABASE_SERVICE_KEY,
        }
        return [key for key, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
