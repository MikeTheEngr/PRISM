"""
PRISM Backend — Supabase Clients

Two clients on purpose:

* get_supabase()       service-role client for reading/writing tables.
                       NEVER call .auth.sign_in / sign_up on it: supabase-py
                       would switch it to that user's login and later queries
                       could run as the wrong user.
* get_auth_client()    a fresh anon-key client per login/signup call.
* get_token_verifier() a shared anon-key client used only to check tokens.

Never expose the service key to the frontend.
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


def _anon_client() -> Client:
    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise RuntimeError(
            "Supabase auth is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


def get_auth_client() -> Client:
    """Fresh client per call: use for sign_up / sign_in_with_password."""
    return _anon_client()


@lru_cache
def get_token_verifier() -> Client:
    """Shared client used only for auth.get_user(token)."""
    return _anon_client()