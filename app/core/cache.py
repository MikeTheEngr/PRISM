"""
PRISM Backend — Upstash Redis cache (REST API)

Commands are sent as a JSON list in a POST body, for example
["SET", key, value, "EX", 60]. The old version put the data in the URL path,
which breaks on characters like / ? # % and on long values, and the broad
`except` hid the failure.
"""

import json
import logging
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.utils.errors import describe_error

logger = logging.getLogger("prism.cache")
settings = get_settings()


class Cache:
    def __init__(self):
        self.base_url = settings.UPSTASH_REDIS_URL.rstrip("/")
        self.token = settings.UPSTASH_REDIS_TOKEN
        self.enabled = bool(self.base_url and self.token)
        if not self.enabled:
            logger.warning("Upstash cache not configured: every request will hit upstream APIs.")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _command(self, *cmd: Any) -> Any:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(self.base_url, headers=self._headers(), json=list(cmd))
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise RuntimeError(body["error"])
            return body.get("result")

    async def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            result = await self._command("GET", key)
            if result is None:
                return None
            return json.loads(result) if isinstance(result, str) else result
        except Exception as exc:
            logger.warning("cache GET failed for %s: %s", key, describe_error(exc))
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> bool:
        if not self.enabled:
            return False
        try:
            await self._command("SET", key, json.dumps(value), "EX", ttl_seconds)
            return True
        except Exception as exc:
            logger.warning("cache SET failed for %s: %s", key, describe_error(exc))
            return False


_cache_instance: Optional[Cache] = None


def get_cache() -> Cache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = Cache()
    return _cache_instance