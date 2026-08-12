"""SQLite state store (Task 5).

Thin persistence layer for the WhatsApp guest assistant bot: an append-only
message log, a pause set, and a small key/value settings table (KB text,
``ai_enabled`` flag). Uses only the stdlib ``sqlite3`` and ``os`` modules —
no third-party dependencies.

The module keeps a single module-level connection ``_conn`` that is lazily
created on first use (or explicitly via :func:`init_db`). A connection is
identified by its path so that calling ``init_db`` again with the same path
(notably ``":memory:"``) reuses the existing connection instead of wiping it.
"""
from __future__ import annotations

import os
import sqlite3

# Project root = parent of the app/ package. Matches app/kb.py's resolution.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_KB_PATH = os.path.join(_PROJECT_ROOT, "kb_seed.md")

# Settings row keys.
KB_KEY = "kb"
AI_ENABLED_KEY = "ai_enabled"

_conn = None
_db_path = None


def _default_path() -> str:
    """Default SQLite file path from ``DB_PATH`` env, else ``homestay.db``."""
    return os.environ.get("DB_PATH", "homestay.db")


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            role TEXT NOT NULL,
            body TEXT,
            ts TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paused (
            phone TEXT PRIMARY KEY,
            ts TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.commit()


def _seed_kb(conn: sqlite3.Connection) -> None:
    """Seed the KB from kb_seed.md but only if ``kb`` is not already stored."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (KB_KEY,)
    ).fetchone()
    if row is not None:
        return  # already set — never clobber existing content
    try:
        with open(_DEFAULT_KB_PATH, encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        # No seed file available (e.g. running from a bare checkout). The
        # key stays absent so a later set_kb() can populate it.
        return
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        (KB_KEY, content),
    )
    conn.commit()


def init_db(db_path=None) -> sqlite3.Connection:
    """Create tables (and seed the KB) on a connection to ``db_path``.

    If ``db_path`` is None the path comes from the ``DB_PATH`` env var (or
    ``homestay.db``). If a connection to the same path already exists it is
    reused so existing rows are preserved; otherwise a fresh connection +
    schema + seed are created. Returns the connection.
    """
    global _conn, _db_path
    if db_path is None:
        db_path = _default_path()
    db_path = os.fspath(db_path)

    if _conn is not None and _db_path == db_path:
        return _conn  # reuse — preserves data (important for ":memory:")

    if _conn is not None:
        _conn.close()
    _conn = _connect(db_path)
    _db_path = db_path
    _create_tables(_conn)
    _seed_kb(_conn)
    return _conn


def _ensure_ready() -> sqlite3.Connection:
    """Return the live connection, lazily creating the default one."""
    if _conn is None:
        return init_db()
    return _conn


def close_db() -> None:
    """Close the current connection and forget it. Safe to call anytime."""
    global _conn, _db_path
    if _conn is not None:
        _conn.close()
    _conn = None
    _db_path = None


def _reset_for_tests() -> None:
    """Test helper — discard the current connection so the next ``init_db``
    starts from a clean slate (fresh tables + re-seeded KB on ``:memory:``)."""
    close_db()


def query(sql: str, params=(), fetch: bool = False):
    """Run a raw SQL statement on the current/default connection.

    Returns the cursor (or all rows if ``fetch`` is True). Primarily used by
    tests/integrators to inspect state.
    """
    conn = _ensure_ready()
    cur = conn.execute(sql, params)
    if fetch:
        return cur.fetchall()
    conn.commit()
    return cur


def log_message(phone: str, role: str, body) -> None:
    """Append one message to the log for ``phone``."""
    conn = _ensure_ready()
    conn.execute(
        "INSERT INTO messages (phone, role, body) VALUES (?, ?, ?)",
        (phone, role, body),
    )
    conn.commit()


def history(phone: str, limit: int = 50) -> list[dict]:
    """Return ``phone``'s message history, oldest→newest.

    Each dict has keys ``phone``, ``role``, ``body``, ``ts``. Limited to the
    most recent ``limit`` rows.
    """
    conn = _ensure_ready()
    rows = conn.execute(
        """
        SELECT phone, role, body, ts FROM (
            SELECT id, phone, role, body, ts FROM messages
            WHERE phone = ?
            ORDER BY id DESC
            LIMIT ?
        ) ORDER BY id ASC
        """,
        (phone, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def pause(phone: str) -> None:
    """Mark ``phone`` as paused (idempotent)."""
    conn = _ensure_ready()
    conn.execute(
        "INSERT OR REPLACE INTO paused (phone) VALUES (?)", (phone,)
    )
    conn.commit()


def unpause(phone: str) -> None:
    """Remove ``phone`` from the paused set (idempotent)."""
    conn = _ensure_ready()
    conn.execute("DELETE FROM paused WHERE phone = ?", (phone,))
    conn.commit()


def is_paused(phone: str) -> bool:
    """Return True if ``phone`` is currently paused."""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT 1 FROM paused WHERE phone = ?", (phone,)
    ).fetchone()
    return row is not None


def list_all() -> list[dict]:
    """Return every known phone with its paused status.

    ``known`` means present in the message log or the paused set. Each dict is
    ``{"phone": ..., "paused": bool}``.
    """
    conn = _ensure_ready()
    rows = conn.execute(
        """
        SELECT phone FROM (
            SELECT phone FROM messages
            UNION
            SELECT phone FROM paused
        )
        ORDER BY phone
        """
    ).fetchall()
    result = []
    for r in rows:
        result.append(
            {
                "phone": r["phone"],
                "paused": is_paused(r["phone"]),
            }
        )
    return result


def get_kb() -> str:
    """Return the stored KB text (empty string if never set)."""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (KB_KEY,)
    ).fetchone()
    return row["value"] if row is not None else ""


def set_kb(text: str) -> None:
    """Overwrite the stored KB text."""
    conn = _ensure_ready()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (KB_KEY, text),
    )
    conn.commit()


def ai_enabled() -> bool:
    """Return whether the AI assistant is enabled (default True)."""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (AI_ENABLED_KEY,)
    ).fetchone()
    if row is None or row["value"] is None:
        return True
    return row["value"].strip().lower() in ("1", "true", "yes", "on")


def set_ai(enabled: bool) -> None:
    """Persist the AI-enabled flag (``"1"`` or ``"0"``)."""
    conn = _ensure_ready()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (AI_ENABLED_KEY, "1" if enabled else "0"),
    )
    conn.commit()
