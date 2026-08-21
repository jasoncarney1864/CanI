"""Filename sanitization for the original-document download endpoint (docs/21 §2.2).

Titles come from user-controlled input (the uploaded filename, or a derived title for
generated documents) and end up in a Content-Disposition header — strip anything that
could break header parsing or produce a filesystem-hostile name on download.
"""

from __future__ import annotations

import re

MAX_FILENAME_LENGTH = 120
FALLBACK_FILENAME = "document"

# Windows/Unix path separators plus the classic Windows-reserved characters.
_FORBIDDEN_CHARS = re.compile(r'[\\/:*?"<>|]')
# Non-whitespace control characters (0x00-0x1F, 0x7F) minus tab/newline/CR, which are
# whitespace and get collapsed by _WHITESPACE below instead of deleted outright — deleting
# a tab between two words would otherwise glue them together with no separator at all.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(title: str) -> str:
    """Collapse a document title into a filesystem/header-safe filename stem (no
    extension). Empty or all-forbidden input falls back to a fixed name rather than
    producing an empty Content-Disposition filename."""
    stripped = _CONTROL_CHARS.sub("", title)
    stripped = _FORBIDDEN_CHARS.sub("", stripped)
    stripped = _WHITESPACE.sub(" ", stripped).strip()
    stripped = stripped[:MAX_FILENAME_LENGTH].strip()
    return stripped or FALLBACK_FILENAME
