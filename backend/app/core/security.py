"""Security helpers: admin-key guard and filename sanitisation."""

from __future__ import annotations

import hmac
import re
from pathlib import PurePath

from fastapi import Header, HTTPException, status

from app.core.config import get_settings

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str | None, max_length: int = 120) -> str:
    """Reduce an uploaded filename to a safe basename (no directories, no traversal)."""

    if not name:
        return "upload"
    base = PurePath(name.replace("\\", "/")).name
    base = base.replace("..", "")
    base = _SAFE_NAME.sub("_", base).strip("._")
    return (base or "upload")[:max_length]


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Guard for destructive operations. Disabled entirely unless EVALS_ADMIN_API_KEY is set."""
    configured = get_settings().admin_api_key
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sensitive operations are disabled. Set EVALS_ADMIN_API_KEY to enable them.",
        )
    if not x_admin_key or not hmac.compare_digest(x_admin_key, configured):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing X-Admin-Key header.")
