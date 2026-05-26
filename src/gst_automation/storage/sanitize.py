from __future__ import annotations

import re


_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_segment(value: str) -> str:
    """Sanitize a value for use as a single path segment (no slashes, no traversal)."""
    v = value.strip()
    v = v.replace("/", "_").replace("\\", "_")
    v = _SEGMENT_RE.sub("_", v)
    v = v.strip("._-")
    return v or "unknown"

