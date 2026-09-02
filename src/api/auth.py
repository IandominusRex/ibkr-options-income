"""Authentication and the role model.

Today this returns a single owner for a valid bearer token. The seam is deliberate: when
the site goes multi-user, `authenticate` is what changes, and every route that already
depends on `current_user` keeps working unchanged. See design §4.4.
"""

from __future__ import annotations

import secrets
from enum import StrEnum

from pydantic import BaseModel

from src.common.config import get_config


class Role(StrEnum):
    OWNER = "owner"  # sees the book: positions, account, fills, campaigns
    VIEWER = "viewer"  # research only


class User(BaseModel):
    id: str
    role: Role


def _configured_token() -> str:
    """Indirection so tests can patch the configured token without touching .env."""
    return get_config().secrets.web_api_token


def authenticate(token: str | None) -> User | None:
    """Return the user for a valid bearer token, or None.

    Fails closed when WEB_API_TOKEN is unset: an unconfigured deployment must reject
    everything rather than accept anything.
    """
    configured = _configured_token()
    if not configured or not token:
        return None
    if not secrets.compare_digest(token, configured):
        return None
    return User(id="owner", role=Role.OWNER)
