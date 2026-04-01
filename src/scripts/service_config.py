"""Centralised runtime configuration for dependent services."""
from __future__ import annotations

import os


def _strip_trailing(url: str) -> str:
    return url.rstrip("/")


def _build_ehrbase_base() -> str:
    env_base = os.environ.get("EHRBASE_BASE_URL")
    if env_base:
        return _strip_trailing(env_base)

    host = os.environ.get("EHRBASE_HOST", "localhost")
    port = os.environ.get("EHRBASE_HOST_PORT", "8090")
    return f"http://{host}:{port}/ehrbase"


def _default_backend_base() -> str:
    return os.environ.get("BACKEND_BASE_URL", "http://localhost:3000")


EHRBASE_BASE_URL = _build_ehrbase_base()
EHRBASE_API_URL = os.environ.get(
    "EHRBASE_API_URL",
    f"{EHRBASE_BASE_URL}/rest/openehr/v1",
)
EHRBASE_HEALTH_URL = os.environ.get(
    "EHRBASE_HEALTH_URL",
    f"{EHRBASE_BASE_URL}/",
)

BACKEND_BASE_URL = _strip_trailing(_default_backend_base())
BACKEND_HEALTH_URL = os.environ.get(
    "BACKEND_HEALTH_URL",
    f"{BACKEND_BASE_URL}/health",
)

__all__ = [
    "EHRBASE_BASE_URL",
    "EHRBASE_API_URL",
    "EHRBASE_HEALTH_URL",
    "BACKEND_BASE_URL",
    "BACKEND_HEALTH_URL",
]
