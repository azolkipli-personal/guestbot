"""Tests for the knowledge-base loader (Task 1)."""
import os

import pytest

from app import kb

# Reference URL present in the seeded KB's ## Booking section.
BOOKING_URL = "https://www.booking.com/Share-gtWXR5"


@pytest.fixture()
def kb_text() -> str:
    """Load the real seeded KB once."""
    return kb.load_kb()


def test_load_kb_no_arg_returns_nonempty():
    text = kb.load_kb()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_kb_missing_path_raises(tmp_path):
    missing = tmp_path / "does-not-exist.md"
    assert not missing.exists()
    with pytest.raises(FileNotFoundError):
        kb.load_kb(kb_path=str(missing))


def test_load_kb_respects_env_var(tmp_path, monkeypatch):
    f = tmp_path / "custom.md"
    f.write_text("custom content")
    monkeypatch.setenv("KB_PATH", str(f))
    assert kb.load_kb() == "custom content"


def test_extract_booking_link_finds_seed_url(kb_text):
    assert kb.extract_booking_link(kb_text) == BOOKING_URL


def test_extract_booking_link_returns_none_when_absent():
    assert kb.extract_booking_link("No ## Booking section with a URL here.") is None


def test_kb_sections_seed_includes_booking(kb_text):
    sections = kb.kb_sections(kb_text)
    assert isinstance(sections, list)
    assert len(sections) > 0
    assert "Booking" in [s.lower() for s in sections] or "Booking" in sections


def test_kb_sections_small_inline_string():
    md = "## One\n## Two\nSome body text\n## Three"
    assert kb.kb_sections(md) == ["One", "Two", "Three"]
