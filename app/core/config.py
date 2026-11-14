"""
PRISM Backend — Core Configuration

Everything reads environment variables through this module only.
"""

import os
from pathlib import Path
from functools import lru_cache
from dotenv import load_dotenv

# Load .env from the backend folder, regardless of where uvicorn is started.
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings:
    # Supabase
    SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")
    # Public anon key: used ONLY for login/signup/token checks
    SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "")

    # Upstash Redis (cache)
    UPSTASH_REDIS_URL: str = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_TOKEN: str = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    # Market data providers
    COINGECKO_API_KEY: str = os.environ.get("COINGECKO_API_KEY", "")
    ALPHA_VANTAGE_API_KEY: str = os.environ.get("ALPHA_VANTAGE_API_KEY", "")

    # AI providers
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

    # App
    ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")

    # CORS. In production set FRONTEND_ORIGINS to your exact site URL(s).
    ALLOWED_ORIGINS_REGEX: str = os.environ.get(
        "ALLOWED_ORIGINS_REGEX", r"https://.*\.vercel\.app"
    )
    FRONTEND_ORIGINS: list[str] = [
        o.strip()
        for o in os.environ.get(
            "FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(",")
        if o.strip()
    ]

    # Cache lifetimes (seconds)
    CACHE_TTL_CRYPTO_PRICE: int = 60
    CACHE_TTL_STOCK_PRICE: int = int(os.environ.get("CACHE_TTL_STOCK_PRICE", "300"))
    CACHE_TTL_SIGNAL: int = 1800
    CACHE_TTL_STALE_FALLBACK: int = 86400  # last-known-good price kept for 24h

    def validate(self) -> list[str]:
        """Returns the names of required settings that are missing."""
        required = {
            "SUPABASE_URL": self.SUPABASE_URL,
            "SUPABASE_SERVICE_KEY": self.SUPABASE_SERVICE_KEY,
            "SUPABASE_ANON_KEY": self.SUPABASE_ANON_KEY,
        }
        return [key for key, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()