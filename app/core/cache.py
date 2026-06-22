

import json
import httpx
from typing import Any, Optional

from app.core.config import get_settings

settings = get_settings()


class Cache:
    def __init__(self):
        self.base_url = settings.UPSTASH_REDIS_URL
        self.token = settings.UPSTASH_REDIS_TOKEN
        self.enabled = bool(self.base_url and self.token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/get/{key}", headers=self._headers())
                resp.raise_for_status()
                result = resp.json().get("result")
                if result is None:
                    return None
                # result is always a JSON string from Upstash — parse it
                if isinstance(result, str):
                    result = json.loads(result)
                # Handle Upstash's occasional {"value": "..."} envelope
                if isinstance(result, dict) and "value" in result and len(result) == 1:
                    inner = result["value"]
                    if isinstance(inner, str):
                        result = json.loads(inner)
                    else:
                        result = inner
                return result
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> bool:
        if not self.enabled:
            return False
        try:
            # Upstash REST API: POST /set/key/value with EX query param
            payload = json.dumps(value)
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(
                    f"{self.base_url}/set/{key}/{payload}",
                    headers=self._headers(),
                    params={"EX": ttl_seconds},
                )
                resp.raise_for_status()
                return True
        except Exception:
            return False


_cache_instance: Optional[Cache] = None


def get_cache() -> Cache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = Cache()
    return _cache_instance