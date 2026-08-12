"""Language detection for the WhatsApp guest assistant bot (Task 2).

Detects whether user input is Bahasa Malaysia (``"ms"``) or English
(``"en"``). Pure stdlib-only function, no side effects.
"""
import re

# Curated Malay keyword signals, matched case-insensitively on word
# boundaries. "homestay" is intentionally excluded: it is shared/neutral.
_MALAY_KEYWORDS = (
    "berapa",       # how much / how many
    "nak",          # want
    "saya",         # I
    "boleh",        # can
    "harga",        # price
    "terima kasih", # thank you
    "sila",         # please
    "ada",          # is there / there is
    "malam",        # night
    "minggu",       # week / weekend
    "esok",         # tomorrow
    "siapa",        # who
    "bilik",        # room
    "kena",         # must / has to ("kena bayar")
    "assalamualaikum",
    "waalaikumsalam",
    "mahu",         # want
    "tempah",       # book / reserve
    "tak",          # not ("ada bilik tak")
    "hujung",       # end ("hujung minggu")
    "banyak",       # a lot ("banyak-banyak")
    "tolong",       # please / help
)

# Precompile once: alternation wrapped in word boundaries, case-insensitive.
_MALAY_RE = re.compile(
    r"\b(?:" + "|".join(_MALAY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Return ``"ms"`` if Malay keywords are present, else ``"en"``.

    Case-insensitive matching with word boundaries. ``None``, empty,
    whitespace-only, number-only and punctuation-only input all default
    to ``"en"`` (neutral/mixed input is treated as English).
    """
    if not text or not isinstance(text, str):
        return "en"
    if _MALAY_RE.search(text):
        return "ms"
    return "en"
