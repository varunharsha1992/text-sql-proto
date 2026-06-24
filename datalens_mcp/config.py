from __future__ import annotations

import os

API_URL = os.getenv("DATALENS_API_URL", "http://127.0.0.1:8000").rstrip("/")
MCP_HOST = os.getenv("DATALENS_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("DATALENS_MCP_PORT", "8010"))
JOB_TIMEOUT_SEC = float(os.getenv("DATALENS_JOB_TIMEOUT_SEC", "300"))
QUERY_TIMEOUT_SEC = float(os.getenv("DATALENS_QUERY_TIMEOUT_SEC", "300"))
POLL_INTERVAL_SEC = float(os.getenv("DATALENS_POLL_INTERVAL_SEC", "2.0"))
PROGRESS_HEARTBEAT_SEC = 15.0
