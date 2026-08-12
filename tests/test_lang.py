"""Tests for language detection (Task 2)."""
import pytest

from app import lang


@pytest.mark.parametrize(
    "text, expected",
    [
        ("What time is check-in?", "en"),
        ("Berapa harga homestay untuk hujung minggu?", "ms"),
        ("nak tanya bilangan bilik", "ms"),
        ("Terima kasih banyak-banyak", "ms"),
        ("", "en"),
        ("   ", "en"),
        ("12345", "en"),
        ("Saya mahu tempah untuk malam esok", "ms"),
        (None, "en"),
        ("do you have parking", "en"),
        ("Assalamualaikum, ada bilik tak?", "ms"),
    ],
)
def test_detect_language(text, expected):
    assert lang.detect_language(text) == expected


def test_detect_language_case_insensitive():
    assert lang.detect_language("BERAPA HARGA BILIK?") == "ms"


def test_detect_language_neutral_shared_words_default_en():
    # "homestay" alone is shared/neutral, must NOT trigger Malay.
    assert lang.detect_language("homestay") == "en"
