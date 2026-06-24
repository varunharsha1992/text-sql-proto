from __future__ import annotations

import os
from urllib.parse import urlparse

_DEFAULT_API_URL = "http://127.0.0.1:8000"


def normalize_api_url(raw: str | None) -> str:
    """Resolve DATALENS_API_URL for httpx (requires http:// or https://)."""
    if raw is None or not raw.strip():
        return _DEFAULT_API_URL

    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        host = url.split("/", 1)[0]
        if host.startswith(("127.0.0.1", "localhost", "[::1]")):
            url = f"http://{url}"
        else:
            # ngrok / public hosts — users often omit the scheme
            url = f"https://{url}"

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"DATALENS_API_URL is invalid: {raw!r}. "
            "Use a full URL like https://abc123.ngrok-free.app"
        )
    return url


_raw = os.getenv("DATALENS_API_URL")
API_URL = normalize_api_url(_raw if _raw and _raw.strip() else None)
MCP_HOST = os.getenv("DATALENS_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("DATALENS_MCP_PORT", "8010"))
JOB_TIMEOUT_SEC = float(os.getenv("DATALENS_JOB_TIMEOUT_SEC", "300"))
QUERY_TIMEOUT_SEC = float(os.getenv("DATALENS_QUERY_TIMEOUT_SEC", "300"))
POLL_INTERVAL_SEC = float(os.getenv("DATALENS_POLL_INTERVAL_SEC", "2.0"))
PROGRESS_HEARTBEAT_SEC = 15.0
