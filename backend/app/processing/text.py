"""Text normalisation helpers shared by dedup, clustering and failure detection."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_PLACEHOLDER = re.compile(r"\[REDACTED_[A-Z_]+\]")
_NON_WORD = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    t = _PLACEHOLDER.sub(" redacted ", unicodedata.normalize("NFKC", text)).lower()
    t = _NON_WORD.sub(" ", t)
    return _WS.sub(" ", t).strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
