"""Text normalization + content hashing for change detection."""

from __future__ import annotations

import hashlib
import re

_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Collapse all whitespace runs to single spaces and trim edges."""
    return _WHITESPACE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    """SHA-256 of the normalized text — the change-detection fingerprint."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
