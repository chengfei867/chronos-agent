"""Chronos Local HTTP API.

R34-A minimum: read-only FastAPI over :class:`chronos.store.SqliteStore`.
Install with ``pip install chronos-agent[web]`` to pull fastapi + uvicorn.

See :mod:`chronos.api.server` for the app factory and endpoint list.
"""

from __future__ import annotations

from chronos.api.server import build_app

__all__ = ["build_app"]
