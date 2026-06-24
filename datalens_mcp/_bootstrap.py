"""Ensure repo root is on sys.path for script-style entrypoints (Horizon, fastmcp dev)."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_root() -> None:
    root = Path(__file__).resolve().parent.parent
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
