from __future__ import annotations

import httpx

from datalens_mcp.config import API_URL, JOB_TIMEOUT_SEC, QUERY_TIMEOUT_SEC


class DataLensClient:
    def __init__(self, base_url: str = API_URL) -> None:
        self.base_url = base_url.rstrip("/")

    async def upload_csv(self, filename: str, content: bytes) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=JOB_TIMEOUT_SEC) as client:
            files = {"file": (filename, content, "text/csv")}
            r = await client.post("/api/upload", files=files)
            r.raise_for_status()
            return r.json()

    async def get_job(self, job_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            r = await client.get(f"/api/jobs/{job_id}")
            r.raise_for_status()
            return r.json()

    async def schema_sync(self) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            r = await client.post("/api/schema/sync")
            r.raise_for_status()
            return r.json()

    async def context_chat(self, message: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=QUERY_TIMEOUT_SEC) as client:
            r = await client.post("/api/context/chat", json={"message": message})
            r.raise_for_status()
            return r.json()

    async def query_chat(self, message: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=QUERY_TIMEOUT_SEC) as client:
            r = await client.post("/api/query/chat", json={"message": message})
            r.raise_for_status()
            return r.json()


def format_http_error(exc: httpx.HTTPStatusError) -> str:
    try:
        detail = exc.response.json().get("detail", exc.response.text)
    except Exception:  # noqa: BLE001
        detail = exc.response.text
    return f"HTTP {exc.response.status_code}: {detail}"


def format_connect_error(base_url: str) -> str:
    hint = ""
    if base_url == "http://127.0.0.1:8000":
        hint = (
            " (Horizon: set DATALENS_API_URL to your public backend URL, "
            "e.g. https://abc123.ngrok-free.app)"
        )
    return f"DataLens API unreachable at {base_url}{hint}"


def format_url_error(exc: Exception, base_url: str) -> str:
    return (
        f"Invalid DATALENS_API_URL ({base_url!r}): {exc}. "
        "Set a full URL with https://, e.g. https://abc123.ngrok-free.app"
    )
