"""
Portfolio & Saved-Search Persistence — SQLite.

The only persistence layer in the app. Everything else lives in
`st.session_state` for the duration of a browser session; this module is
what lets a shortlisted property or a saved Site Finder search survive
across sessions/reruns.

Storage: a single SQLite file at `data/portfolio.db` (repo-relative,
created lazily on first import). Two tables:
  portfolio        — one row per saved property, keyed by BBL (upsert)
  saved_searches   — Site Finder Investment Criteria snapshots, re-run manually

No API keys, no network calls. Every public function accepts an optional
`conn` (an already-open `sqlite3.Connection`) so tests can pass an
in-memory database (`sqlite3.connect(":memory:")`) without touching the
real file on disk.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(os.path.dirname(_HERE), "data")
DB_PATH = os.path.join(DB_DIR, "portfolio.db")

STATUSES = ["Watching", "Under Diligence", "Offer Out", "Under Contract", "Passed", "Closed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio (
    bbl            TEXT PRIMARY KEY,
    address        TEXT NOT NULL,
    borough        TEXT,
    status         TEXT NOT NULL DEFAULT 'Watching',
    deal_score     REAL,
    deal_tier      TEXT,
    notes          TEXT DEFAULT '',
    property_json  TEXT NOT NULL,
    added_at       TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    criteria_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_run_at    TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Idempotent — safe to call on every connection (CREATE TABLE IF NOT EXISTS)."""
    conn.executescript(_SCHEMA)
    conn.commit()


def _with_conn(conn: sqlite3.Connection | None):
    """Return (connection, should_close). Opens+initializes the real DB file
    if no connection was supplied (the normal app path); reuses the given
    connection as-is otherwise (the test path, e.g. sqlite3.connect(':memory:'))."""
    if conn is not None:
        init_schema(conn)
        return conn, False
    c = _connect()
    init_schema(c)
    return c, True


def _row_to_portfolio_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["property"] = json.loads(d.pop("property_json"))
    except Exception:
        d["property"] = {}
        d.pop("property_json", None)
    return d


# ── Portfolio CRUD ──────────────────────────────────────────────────────

def save_property(prop: dict, status: str = "Watching", notes: str = "",
                   conn: sqlite3.Connection | None = None) -> dict:
    """Upsert a property into the portfolio, keyed by its 'bbl'. Re-saving
    an already-saved BBL refreshes its snapshot/score/updated_at and, unless
    a new status/notes is explicitly passed, preserves the existing ones."""
    bbl = str(prop.get("bbl") or "").strip()
    if not bbl:
        raise ValueError("save_property: prop['bbl'] is required and cannot be empty")

    c, should_close = _with_conn(conn)
    try:
        existing = c.execute("SELECT status, notes FROM portfolio WHERE bbl = ?", (bbl,)).fetchone()
        use_status = status if status else (existing["status"] if existing else "Watching")
        use_notes = notes if notes else (existing["notes"] if existing else "")

        deal_score = None
        deal_tier = None
        ds = prop.get("deal_score")
        if isinstance(ds, dict):
            deal_score = ds.get("score")
            deal_tier = ds.get("tier")

        now = _now()
        added_at = now
        if existing is not None:
            prev = c.execute("SELECT added_at FROM portfolio WHERE bbl = ?", (bbl,)).fetchone()
            added_at = prev["added_at"] if prev else now

        c.execute(
            """
            INSERT INTO portfolio (bbl, address, borough, status, deal_score, deal_tier,
                                    notes, property_json, added_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bbl) DO UPDATE SET
                address       = excluded.address,
                borough       = excluded.borough,
                status        = excluded.status,
                deal_score    = excluded.deal_score,
                deal_tier     = excluded.deal_tier,
                notes         = excluded.notes,
                property_json = excluded.property_json,
                updated_at    = excluded.updated_at
            """,
            (bbl, prop.get("address", ""), prop.get("borough", ""), use_status,
             deal_score, deal_tier, use_notes, json.dumps(prop), added_at, now),
        )
        c.commit()
        row = c.execute("SELECT * FROM portfolio WHERE bbl = ?", (bbl,)).fetchone()
        return _row_to_portfolio_dict(row)
    finally:
        if should_close:
            c.close()


def update_status(bbl: str, status: str | None = None, notes: str | None = None,
                   conn: sqlite3.Connection | None = None) -> bool:
    """Partial update — only fields that are not None change. Returns True
    if a row was found and updated."""
    if status is None and notes is None:
        return False
    c, should_close = _with_conn(conn)
    try:
        sets, params = [], []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if notes is not None:
            sets.append("notes = ?")
            params.append(notes)
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(bbl)
        cur = c.execute(f"UPDATE portfolio SET {', '.join(sets)} WHERE bbl = ?", params)
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


def list_portfolio(status: str | None = None, conn: sqlite3.Connection | None = None) -> list[dict]:
    c, should_close = _with_conn(conn)
    try:
        if status:
            rows = c.execute(
                "SELECT * FROM portfolio WHERE status = ? ORDER BY updated_at DESC", (status,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM portfolio ORDER BY updated_at DESC").fetchall()
        return [_row_to_portfolio_dict(r) for r in rows]
    finally:
        if should_close:
            c.close()


def get_property(bbl: str, conn: sqlite3.Connection | None = None) -> dict | None:
    c, should_close = _with_conn(conn)
    try:
        row = c.execute("SELECT * FROM portfolio WHERE bbl = ?", (bbl,)).fetchone()
        return _row_to_portfolio_dict(row) if row else None
    finally:
        if should_close:
            c.close()


def remove_property(bbl: str, conn: sqlite3.Connection | None = None) -> bool:
    c, should_close = _with_conn(conn)
    try:
        cur = c.execute("DELETE FROM portfolio WHERE bbl = ?", (bbl,))
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


# ── Saved Searches CRUD ─────────────────────────────────────────────────

def save_search(name: str, criteria: dict, conn: sqlite3.Connection | None = None) -> int:
    c, should_close = _with_conn(conn)
    try:
        cur = c.execute(
            "INSERT INTO saved_searches (name, criteria_json, created_at) VALUES (?, ?, ?)",
            (name, json.dumps(criteria), _now()),
        )
        c.commit()
        return cur.lastrowid
    finally:
        if should_close:
            c.close()


def list_saved_searches(conn: sqlite3.Connection | None = None) -> list[dict]:
    c, should_close = _with_conn(conn)
    try:
        rows = c.execute("SELECT * FROM saved_searches ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["criteria"] = json.loads(d.pop("criteria_json"))
            except Exception:
                d["criteria"] = {}
                d.pop("criteria_json", None)
            out.append(d)
        return out
    finally:
        if should_close:
            c.close()


def get_saved_search(search_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
    c, should_close = _with_conn(conn)
    try:
        row = c.execute("SELECT * FROM saved_searches WHERE id = ?", (search_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["criteria"] = json.loads(d.pop("criteria_json"))
        except Exception:
            d["criteria"] = {}
            d.pop("criteria_json", None)
        return d
    finally:
        if should_close:
            c.close()


def delete_saved_search(search_id: int, conn: sqlite3.Connection | None = None) -> bool:
    c, should_close = _with_conn(conn)
    try:
        cur = c.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


def touch_search_last_run(search_id: int, conn: sqlite3.Connection | None = None) -> None:
    c, should_close = _with_conn(conn)
    try:
        c.execute("UPDATE saved_searches SET last_run_at = ? WHERE id = ?", (_now(), search_id))
        c.commit()
    finally:
        if should_close:
            c.close()
