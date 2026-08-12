"""Knowledge base loader (Task 1).

Pure, stdlib-only helpers for reading the property Knowledge Base (KB) markdown and
extracting structured bits (booking link, section titles).
"""
from __future__ import annotations

import os
import re

# Default path is relative to the project root (parent of app/).
DEFAULT_KB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kb_seed.md")

# Matches any http(s) URL.
_URL_RE = re.compile(r"https?://\S+")


def load_kb(kb_path: str | None = None) -> str:
    """Return the KB text.

    Uses the ``KB_PATH`` environment variable if set, otherwise the default
    ``kb_seed.md``. Raises FileNotFoundError if the file is missing.
    """
    if kb_path is None:
        kb_path = os.environ.get("KB_PATH", DEFAULT_KB_PATH)
    with open(kb_path, encoding="utf-8") as fh:
        return fh.read()


def extract_booking_link(kb: str) -> str | None:
    """Return the first booking URL found in the ``## Booking`` section.

    Returns None if no ``## Booking`` section or URL is present.
    """
    section_re = re.compile(
        r"^##\s+(.+?)\s*$([\s\S]*?)(?=^##\s+|\Z)", re.MULTILINE
    )
    for title, body in section_re.findall(kb):
        if title.strip().lower() == "booking":
            match = _URL_RE.search(body)
            return match.group(0) if match else None
    return None


def kb_sections(kb: str) -> list[str]:
    """Return the list of markdown ``## `` section titles (stripped)."""
    return [line[3:].strip() for line in kb.splitlines() if line.startswith("## ")]
