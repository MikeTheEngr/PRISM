"""
PRISM Backend — Cache (memory + Upstash Redis)

Two layers:
1. Memory (inside this server process): checked first, costs no network.
2. Upstash Redis (shared, survives restarts): used when memory misses.

If Upstash fails (timeout, DNS, outage), we stop trying it for a short
cooldown instead of making every request wait for the timeout, and the server
keeps working from memory. Memory is lost on restart, which is fine: it only
protects against Upstash being slow or down.

Commands go to Upstash as a JSON list in a POST body, e.g.
["SET", key, value, "EX", 60].
"""

import json
import logging
import time
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.utils.errors import describe_error

logger = logging.getLogger("prism.cache")
settings = get_settings()

_MAX_ENTRIES = 2000          # memory cap, oldest entries are dropped first
_REDIS_COOLDOWN_SECONDS = 30  # after a failure, skip Upstash for this long
_REDIS_TIMEOUT = 3.0
_MEMORY_TTL_FROM_REDIS = 60   # how long we keep a value we just read from Upstash


class Cache:
    def __init__(self):
        self.base_url = settings.UPSTASH_REDIS_URL.rstrip("/")
        self.token = settings.UPSTASH_REDIS_TOKEN
        self.enabled = bool(self.base_url and self.token)
        self._memory: dict[str, tuple[float, str]] = {}  # key -> (expires_at, json)
        self._redis_down_until = 0.0
        self._client: Optional[httpx.AsyncClient] = None
        if not self.enabled:
            logger.warning("Upstash not configured: using memory cache only.")

    # ---------- memory layer ----------
    def _mem_get(self, key: str) -> Optional[Any]:
        item = self._memory.get(key)
        if item is None:
            return None
        expires_at, raw = item
        if expires_at <= time.monotonic():
            self._memory.pop(key, None)
            return None
        return json.loads(raw)

    def _mem_set(self, key: str, raw: str, ttl_seconds: float) -> None:
        if len(self._memory) >= _MAX_ENTRIES:
            self._evict()
        self._memory[key] = (time.monotonic() + ttl_seconds, raw)

    def _evict(self) -> None:
        now = time.monotonic()
        for k in [k for k, (exp, _) in self._memory.items() if exp <= now]:
            del self._memory[k]
        while len(self._memory) >= _MAX_ENTRIES:
            oldest = min(self._memory, key=lambda k: self._memory[k][0])
            del self._memory[oldest]

    # ---------- Upstash layer ----------
    def _redis_available(self) -> bool:
        return self.enabled and time.monotonic() >= self._redis_down_until

    def _mark_redis_down(self) -> None:
        self._redis_down_until = time.monotonic() + _REDIS_COOLDOWN_SECONDS

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _command(self, *cmd: Any) -> Any:
        # One shared connection: avoids a new TCP+TLS handshake on every call,
        # which is slow on weak connections.
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_REDIS_TIMEOUT)
        try:
            resp = await self._client.post(self.base_url, headers=self._headers(), json=list(cmd))
            resp.raise_for_status()
            body = resp.json()
        except Exception:
            client, self._client = self._client, None  # rebuild on the next call
            try:
                await client.aclose()
            except Exception:
                pass
            raise
        if "error" in body:
            raise RuntimeError(body["error"])
        return body.get("result")

    # ---------- public API ----------
    async def get(self, key: str) -> Optional[Any]:
        hit = self._mem_get(key)
        if hit is not None:
            return hit
        if not self._redis_available():
            return None
        try:
            result = await self._command("GET", key)
        except Exception as exc:
            self._mark_redis_down()
            logger.warning(
                "Upstash GET failed (%s). Using memory only for %ss.",
                describe_error(exc), _REDIS_COOLDOWN_SECONDS,
            )
            return None
        if result is None:
            return None
        try:
            value = json.loads(result) if isinstance(result, str) else result
        except json.JSONDecodeError:
            return None
        self._mem_set(key, json.dumps(value), _MEMORY_TTL_FROM_REDIS)
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> bool:
        """Always stores in memory. Returns True only if Upstash stored it too."""
        raw = json.dumps(value)
        self._mem_set(key, raw, ttl_seconds)
        if not self._redis_available():
            return False
        try:
            await self._command("SET", key, raw, "EX", ttl_seconds)
            return True
        except Exception as exc:
            self._mark_redis_down()
            logger.warning(
                "Upstash SET failed (%s). Using memory only for %ss.",
                describe_error(exc), _REDIS_COOLDOWN_SECONDS,
            )
            return False


_cache_instance: Optional[Cache] = None


def get_cache() -> Cache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = Cache()
    return _cache_instance