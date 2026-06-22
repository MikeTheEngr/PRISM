"""
PRISM Backend — Supabase Client

Single shared Supabase client instance. Uses service_role key since this
is a server-side-only service — never expose this client or key to the frontend.
"""

from functools import lru_cache
from supabase import create_client, Client

from app.core.config import get_settings


@lru_cache
def get_supabase() -> Client:
    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
