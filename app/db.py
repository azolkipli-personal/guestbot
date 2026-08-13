"""Multi-tenant state store for GuestBot (Web self-service).

Extends the original single-tenant SQLite store with a ``tenants`` table so a
single deployed instance can serve many homestay owners ("tenants"). Every
owner has their own WhatsApp phone number ID, access token, Knowledge Base,
owner phone, email, and settings — fully isolated per tenant.

The webhook routes each inbound message to the tenant that owns the
``WHATSAPP_PHONE_NUMBER_ID`` Meta says the message arrived on.

Original single-tenant helpers (``log_message``, ``pause``, etc.) are kept for
the ``:memory:`` demo/default mode but are tenant-scoped where it matters.
Uses only stdlib (``sqlite3``, ``os``) — no third-party deps.
"""
from __future__ import annotations

import os
import secrets
import sqlite3

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_KB_PATH = os.path.join(_PROJECT_ROOT, "kb_seed.md")

# Settings row keys (kept for legacy single-tenant mode).
KB_KEY = "kb"
AI_ENABLED_KEY = "ai_enabled"

_conn = None
_db_path = None


def _default_path() -> str:
    return os.environ.get("DB_PATH", "homestay.db")


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            owner_phone TEXT,
            phone_number_id TEXT UNIQUE,      -- Meta phone number ID (routing key)
            access_token TEXT,                -- Meta WhatsApp access token
            verify_token TEXT UNIQUE,         -- per-tenant webhook verify token
            kb TEXT,                          -- per-tenant Knowledge Base
            property_name TEXT,
            oauth_state TEXT,                 -- pending Meta OAuth state guid
            ai_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,                 -- which tenant this message belongs to
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
            tenant_id INTEGER,
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
    """Seed the default demo KB (legacy single-tenant mode) if not set."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (KB_KEY,)
    ).fetchone()
    if row is not None:
        return
    try:
        with open(_DEFAULT_KB_PATH, encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        return
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        (KB_KEY, content),
    )
    conn.commit()


def init_db(db_path=None) -> sqlite3.Connection:
    """Create tables (and seed demo KB) on a connection to ``db_path``."""
    global _conn, _db_path
    if db_path is None:
        db_path = _default_path()
    db_path = os.fspath(db_path)

    if _conn is not None and _db_path == db_path:
        return _conn
    if _conn is not None:
        _conn.close()
    _conn = _connect(db_path)
    _db_path = db_path
    _create_tables(_conn)
    _seed_kb(_conn)
    return _conn


def _ensure_ready() -> sqlite3.Connection:
    if _conn is None:
        return init_db()
    return _conn


def close_db() -> None:
    global _conn, _db_path
    if _conn is not None:
        _conn.close()
    _conn = None
    _db_path = None


def _reset_for_tests() -> None:
    close_db()


def query(sql: str, params=(), fetch: bool = False):
    """Run raw SQL on the current/default connection."""
    conn = _ensure_ready()
    cur = conn.execute(sql, params)
    if fetch:
        return cur.fetchall()
    conn.commit()
    return cur


# ---------------------------------------------------------------------------
# Tenants (the multi-tenant core)
# ---------------------------------------------------------------------------


def tenant_row(phone_number_id: str) -> dict | None:
    """Return a tenant's config keyed by their Meta phone number ID."""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT * FROM tenants WHERE phone_number_id = ?", (phone_number_id,)
    ).fetchone()
    return dict(row) if row else None


def tenant_by_token(verify_token: str) -> dict | None:
    """Return a tenant by their webhook verify token (for webhook handshake)."""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT * FROM tenants WHERE verify_token = ?", (verify_token,)
    ).fetchone()
    return dict(row) if row else None


def tenant_by_oauth_state(state: str) -> dict | None:
    """Return the tenant awaiting a Meta OAuth callback for this ``state``."""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT * FROM tenants WHERE oauth_state = ?", (state,)
    ).fetchone()
    return dict(row) if row else None


def create_tenant(name: str, email: str, **fields) -> dict:
    """Create a tenant and return its row.

    Generates a unique ``verify_token`` so each owner has their own webhook
    secret (Meta routes to a shared endpoint, but verification is per-tenant).
    Accepts optional ``owner_phone``, ``phone_number_id``, ``access_token``,
    ``kb``, ``property_name``.
    """
    conn = _ensure_ready()
    token = secrets.token_urlsafe(32)
    while tenant_by_token(token) is not None:
        token = secrets.token_urlsafe(32)

    cur = conn.execute(
        """
        INSERT INTO tenants (
            name, email, owner_phone, phone_number_id, access_token,
            verify_token, kb, property_name, ai_enabled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            name,
            email,
            fields.get("owner_phone"),
            fields.get("phone_number_id"),
            fields.get("access_token"),
            token,
            fields.get("kb"),
            fields.get("property_name"),
        ),
    )
    conn.commit()
    return tenant_by_token(token)


def update_tenant(phone_number_id: str, **fields) -> dict | None:
    """Patch editable fields on a tenant keyed by phone number ID."""
    conn = _ensure_ready()
    allowed = {
        "name", "email", "owner_phone", "access_token", "kb",
        "property_name", "ai_enabled", "oauth_state",
    }
    sets = [k for k in fields if k in allowed and fields[k] is not None]
    if not sets:
        return tenant_row(phone_number_id)
    assignments = ", ".join(f"{k} = ?" for k in sets)
    params = [fields[k] for k in sets] + [phone_number_id]
    conn.execute(f"UPDATE tenants SET {assignments} WHERE phone_number_id = ?", params)
    conn.commit()
    return tenant_row(phone_number_id)


def tenant_for_owner(owner_phone: str) -> dict | None:
    """Return the tenant whose owner phone matches (for admin routing)."""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT * FROM tenants WHERE owner_phone = ?", (owner_phone,)
    ).fetchone()
    return dict(row) if row else None


def update_tenant_by_id(tenant_id: int, **fields) -> dict | None:
    """Patch editable fields on a tenant keyed by its integer id.

    Useful when a tenant has not yet been assigned a ``phone_number_id``
    (e.g. right after signup, before Meta OAuth completes).
    """
    conn = _ensure_ready()
    allowed = {
        "name", "email", "owner_phone", "phone_number_id", "access_token",
        "kb", "property_name", "ai_enabled", "oauth_state",
    }
    sets = [k for k in fields if k in allowed and fields[k] is not None]
    if not sets:
        return tenant_by_id(tenant_id)
    assignments = ", ".join(f"{k} = ?" for k in sets)
    params = [fields[k] for k in sets] + [tenant_id]
    conn.execute(f"UPDATE tenants SET {assignments} WHERE id = ?", params)
    conn.commit()
    return tenant_by_id(tenant_id)


def tenant_by_id(tenant_id: int) -> dict | None:
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
    ).fetchone()
    return dict(row) if row else None


def set_oauth_state(tenant_id: int, state: str) -> None:
    """Record the pending Meta OAuth state for a tenant."""
    conn = _ensure_ready()
    conn.execute(
        "UPDATE tenants SET oauth_state = ? WHERE id = ?", (state, tenant_id)
    )
    conn.commit()


def list_tenants() -> list[dict]:
    conn = _ensure_ready()
    rows = conn.execute(
        "SELECT id, name, email, owner_phone, phone_number_id, "
        "property_name, ai_enabled FROM tenants ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_tenant(phone_number_id: str) -> None:
    conn = _ensure_ready()
    conn.execute("DELETE FROM tenants WHERE phone_number_id = ?", (phone_number_id,))
    conn.execute(
        "DELETE FROM messages WHERE tenant_id NOT IN (SELECT id FROM tenants)"
    )
    conn.execute(
        "DELETE FROM paused WHERE phone NOT IN (SELECT phone FROM tenants)"
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tenant-scoped message/pause helpers
# ---------------------------------------------------------------------------


def tenant_id_for(phone_number_id: str) -> int | None:
    t = tenant_row(phone_number_id)
    return t["id"] if t else None


def log_message(phone: str, role: str, body, tenant_id: int | None = None) -> None:
    conn = _ensure_ready()
    conn.execute(
        "INSERT INTO messages (tenant_id, phone, role, body) VALUES (?, ?, ?, ?)",
        (tenant_id, phone, role, body),
    )
    conn.commit()


def history(phone: str, limit: int = 50, tenant_id: int | None = None) -> list[dict]:
    conn = _ensure_ready()
    where = "phone = ?"
    params: list = [phone]
    if tenant_id is not None:
        where = "phone = ? AND tenant_id = ?"
        params.append(tenant_id)
    rows = conn.execute(
        f"""
        SELECT phone, role, body, ts FROM (
            SELECT id, phone, role, body, ts FROM messages
            WHERE {where}
            ORDER BY id DESC
            LIMIT ?
        ) ORDER BY id ASC
        """,
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def pause(phone: str, tenant_id: int | None = None) -> None:
    conn = _ensure_ready()
    conn.execute(
        "INSERT OR REPLACE INTO paused (tenant_id, phone) VALUES (?, ?)",
        (tenant_id, phone),
    )
    conn.commit()


def unpause(phone: str) -> None:
    conn = _ensure_ready()
    conn.execute("DELETE FROM paused WHERE phone = ?", (phone,))
    conn.commit()


def is_paused(phone: str, tenant_id: int | None = None) -> bool:
    conn = _ensure_ready()
    if tenant_id is None:
        row = conn.execute(
            "SELECT 1 FROM paused WHERE phone = ?", (phone,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM paused WHERE phone = ? AND tenant_id = ?",
            (phone, tenant_id),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Tenant-scoped KB / AI flags
# ---------------------------------------------------------------------------


def get_kb(tenant: dict | None = None) -> str:
    """Return a tenant's KB, falling back to the legacy single-tenant store."""
    if tenant:
        return tenant.get("kb") or ""
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (KB_KEY,)
    ).fetchone()
    return row["value"] if row else ""


def set_kb(text: str, tenant: dict | None = None) -> None:
    if tenant:
        update_tenant_by_id(tenant["id"], kb=text)
        return
    conn = _ensure_ready()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (KB_KEY, text),
    )
    conn.commit()


def ai_enabled(tenant: dict | None = None) -> bool:
    if tenant:
        return bool(tenant.get("ai_enabled", 1))
    conn = _ensure_ready()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (AI_ENABLED_KEY,)
    ).fetchone()
    if row is None or row["value"] is None:
        return True
    return row["value"].strip().lower() in ("1", "true", "yes", "on")


def set_ai(enabled: bool, tenant: dict | None = None) -> None:
    if tenant:
        update_tenant_by_id(tenant["id"], ai_enabled=1 if enabled else 0)
        return
    conn = _ensure_ready()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (AI_ENABLED_KEY, "1" if enabled else "0"),
    )
    conn.commit()


def list_all(tenant: dict | None = None) -> list[dict]:
    """Every known phone for a tenant (or globally in legacy mode), with pause status."""
    conn = _ensure_ready()
    if tenant:
        rows = conn.execute(
            """
            SELECT phone FROM (
                SELECT phone FROM messages WHERE tenant_id = ?
                UNION
                SELECT phone FROM paused WHERE tenant_id = ?
            )
            ORDER BY phone
            """,
            (tenant["id"], tenant["id"]),
        ).fetchall()
    else:
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
    return [
        {"phone": r["phone"], "paused": is_paused(r["phone"], tenant["id"] if tenant else None)}
        for r in rows
    ]
