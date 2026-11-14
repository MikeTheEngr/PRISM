"""Safe error descriptions for logs.

httpx error messages include the full request URL. Alpha Vantage takes its
API key inside the URL, so printing the raw error would leak the key into
your logs. We log only the error type and status code instead.
"""

import httpx


def describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__