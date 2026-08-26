"""
Portfolio & Saved-Search Persistence — SQLite.

The only persistence layer in the app. Everything else lives in
`st.session_state` for the duration of a browser session; this module is
what lets a shortlisted property or a saved Site Finder search survive
across sessions/reruns.

Storage: a single SQLite file at `data/portfolio.db` (repo-relative,
created lazily on first import). Three tables:
  portfolio        — one row per saved property, keyed by BBL (upsert)
  saved_searches   — Site Finder Investment Criteria snapshots, re-run manually
  diligence_items  — categorized per-property diligence checklist/tracker
                      (Title, Zoning, Phase I ESA, Structural, Financing,
                      etc.), replacing the single free-text `status`
                      pipeline-stage field as the only progress signal

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
OUTREACH_STATUSES = ["Not Contacted", "Contacted", "Responded", "Passed"]
TAG_OPTIONS = ["Hot", "Watch", "Pass"]

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

CREATE TABLE IF NOT EXISTS diligence_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bbl            TEXT NOT NULL,
    category       TEXT NOT NULL,
    item           TEXT NOT NULL,
    is_complete    INTEGER NOT NULL DEFAULT 0,
    notes          TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diligence_items_bbl ON diligence_items(bbl);

CREATE TABLE IF NOT EXISTS outreach (
    bbl               TEXT PRIMARY KEY,
    status            TEXT NOT NULL DEFAULT 'Not Contacted',
    last_contacted_at TEXT,
    follow_up_date    TEXT,
    notes             TEXT DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bbl        TEXT NOT NULL,
    tag        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(bbl, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_bbl ON tags(bbl);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    description TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, collection_id INTEGER NOT NULL,
    bbl TEXT NOT NULL, address TEXT, property_json TEXT NOT NULL, added_at TEXT NOT NULL,
    UNIQUE(collection_id, bbl)
);
CREATE INDEX IF NOT EXISTS idx_collection_items_cid ON collection_items(collection_id);
"""

# Starter checklist seeded for a BBL the first time its tracker is opened —
# a reasonable default set spanning the categories a real diligence process
# covers; users can add/remove items freely afterward (this is a template,
# not a fixed schema).
DEFAULT_CHECKLIST: list[tuple[str, str]] = [
    ("Title", "Order title report"),
    ("Title", "Review ACRIS ownership/lien chain"),
    ("Zoning", "Confirm zoning district and bulk regs with NYC Planning"),
    ("Zoning", "Confirm landmark/historic-district status with LPC"),
    ("Environmental", "Order Phase I Environmental Site Assessment"),
    ("Environmental", "Confirm FEMA flood zone status"),
    ("Structural", "Structural/MEP survey"),
    ("Structural", "Confirm no open DOB/HPD violations blocking permits"),
    ("Financing", "Obtain lender term sheet"),
    ("Financing", "Confirm construction/permanent loan sizing assumptions"),
    ("Legal", "Confirm rent-stabilization status via DHCR"),
    ("Legal", "Review any existing leases/tenancies"),
]


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


# ── Diligence Checklist/Tracker CRUD ────────────────────────────────────

def add_diligence_item(bbl: str, category: str, item: str,
                        conn: sqlite3.Connection | None = None) -> dict:
    c, should_close = _with_conn(conn)
    try:
        now = _now()
        cur = c.execute(
            """
            INSERT INTO diligence_items (bbl, category, item, is_complete, notes, created_at, updated_at)
            VALUES (?, ?, ?, 0, '', ?, ?)
            """,
            (str(bbl), category, item, now, now),
        )
        c.commit()
        row = c.execute("SELECT * FROM diligence_items WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        if should_close:
            c.close()


def list_diligence_items(bbl: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    c, should_close = _with_conn(conn)
    try:
        rows = c.execute(
            "SELECT * FROM diligence_items WHERE bbl = ? ORDER BY category, id", (str(bbl),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if should_close:
            c.close()


def update_diligence_item(item_id: int, is_complete: bool | None = None, notes: str | None = None,
                           conn: sqlite3.Connection | None = None) -> bool:
    """Partial update — only fields that are not None change. Returns True
    if a row was found and updated."""
    if is_complete is None and notes is None:
        return False
    c, should_close = _with_conn(conn)
    try:
        sets, params = [], []
        if is_complete is not None:
            sets.append("is_complete = ?")
            params.append(1 if is_complete else 0)
        if notes is not None:
            sets.append("notes = ?")
            params.append(notes)
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(item_id)
        cur = c.execute(f"UPDATE diligence_items SET {', '.join(sets)} WHERE id = ?", params)
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


def delete_diligence_item(item_id: int, conn: sqlite3.Connection | None = None) -> bool:
    c, should_close = _with_conn(conn)
    try:
        cur = c.execute("DELETE FROM diligence_items WHERE id = ?", (item_id,))
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


def diligence_progress(bbl: str, conn: sqlite3.Connection | None = None) -> dict:
    """Returns {"total": int, "complete": int, "pct": float (0-100)}."""
    items = list_diligence_items(bbl, conn=conn)
    total = len(items)
    complete = sum(1 for i in items if i["is_complete"])
    pct = (complete / total * 100.0) if total > 0 else 0.0
    return {"total": total, "complete": complete, "pct": pct}


def seed_default_checklist(bbl: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Insert DEFAULT_CHECKLIST's items for `bbl` — but ONLY if this BBL
    has no diligence items at all yet (idempotent; safe to call every time
    the tracker UI renders without duplicating rows on every rerun)."""
    c, should_close = _with_conn(conn)
    try:
        existing = c.execute(
            "SELECT COUNT(*) AS n FROM diligence_items WHERE bbl = ?", (str(bbl),)
        ).fetchone()
        if existing["n"] > 0:
            return list_diligence_items(bbl, conn=c)
        for category, item in DEFAULT_CHECKLIST:
            add_diligence_item(bbl, category, item, conn=c)
        return list_diligence_items(bbl, conn=c)
    finally:
        if should_close:
            c.close()


# ── Outreach Tracker CRUD ───────────────────────────────────────────────

def upsert_outreach(bbl: str, status: str | None = None, follow_up_date: str | None = None,
                     notes: str | None = None, conn: sqlite3.Connection | None = None) -> dict:
    """Upsert a single outreach row keyed by `bbl`. Only fields explicitly
    passed as non-None overwrite the existing row (mirrors `update_status()`'s
    partial-update semantics); a brand-new row defaults to status
    'Not Contacted' / empty notes / no follow-up date. `last_contacted_at`
    is auto-stamped to now whenever `status` is explicitly passed as
    something other than 'Not Contacted'."""
    bbl = str(bbl or "").strip()
    if not bbl:
        raise ValueError("upsert_outreach: bbl is required and cannot be empty")

    c, should_close = _with_conn(conn)
    try:
        existing = c.execute(
            "SELECT status, last_contacted_at, follow_up_date, notes, created_at FROM outreach WHERE bbl = ?",
            (bbl,),
        ).fetchone()

        use_status = status if status is not None else (existing["status"] if existing else "Not Contacted")
        use_follow_up = follow_up_date if follow_up_date is not None else (
            existing["follow_up_date"] if existing else None
        )
        use_notes = notes if notes is not None else (existing["notes"] if existing else "")

        use_last_contacted = existing["last_contacted_at"] if existing else None
        if status is not None and status != "Not Contacted":
            use_last_contacted = _now()

        now = _now()
        created_at = existing["created_at"] if existing else now

        c.execute(
            """
            INSERT INTO outreach (bbl, status, last_contacted_at, follow_up_date, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bbl) DO UPDATE SET
                status            = excluded.status,
                last_contacted_at = excluded.last_contacted_at,
                follow_up_date    = excluded.follow_up_date,
                notes             = excluded.notes,
                updated_at        = excluded.updated_at
            """,
            (bbl, use_status, use_last_contacted, use_follow_up, use_notes, created_at, now),
        )
        c.commit()
        row = c.execute("SELECT * FROM outreach WHERE bbl = ?", (bbl,)).fetchone()
        return dict(row)
    finally:
        if should_close:
            c.close()


def get_outreach(bbl: str, conn: sqlite3.Connection | None = None) -> dict | None:
    c, should_close = _with_conn(conn)
    try:
        row = c.execute("SELECT * FROM outreach WHERE bbl = ?", (str(bbl),)).fetchone()
        return dict(row) if row else None
    finally:
        if should_close:
            c.close()


def list_outreach(conn: sqlite3.Connection | None = None) -> list[dict]:
    c, should_close = _with_conn(conn)
    try:
        rows = c.execute("SELECT * FROM outreach ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        if should_close:
            c.close()


# ── Tags/Labels CRUD ────────────────────────────────────────────────────

def add_tag(bbl: str, tag: str, conn: sqlite3.Connection | None = None) -> bool:
    """Attach `tag` to `bbl`. Idempotent — re-adding an already-present tag
    is a harmless no-op thanks to the UNIQUE(bbl, tag) constraint + INSERT
    OR IGNORE. Returns True only if a new row was actually inserted."""
    c, should_close = _with_conn(conn)
    try:
        cur = c.execute(
            "INSERT OR IGNORE INTO tags (bbl, tag, created_at) VALUES (?, ?, ?)",
            (str(bbl), tag, _now()),
        )
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


def remove_tag(bbl: str, tag: str, conn: sqlite3.Connection | None = None) -> bool:
    c, should_close = _with_conn(conn)
    try:
        cur = c.execute("DELETE FROM tags WHERE bbl = ? AND tag = ?", (str(bbl), tag))
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


def list_tags(bbl: str, conn: sqlite3.Connection | None = None) -> list[str]:
    c, should_close = _with_conn(conn)
    try:
        rows = c.execute(
            "SELECT tag FROM tags WHERE bbl = ? ORDER BY tag", (str(bbl),)
        ).fetchall()
        return [r["tag"] for r in rows]
    finally:
        if should_close:
            c.close()


def list_tags_bulk(bbls: list[str], conn: sqlite3.Connection | None = None) -> dict[str, list[str]]:
    """Same shape as calling list_tags() per bbl, but a single `bbl IN (...)`
    query instead of N+1 — used when joining tags onto a whole results
    table at once. An empty `bbls` list returns {} without querying."""
    if not bbls:
        return {}
    c, should_close = _with_conn(conn)
    try:
        placeholders = ", ".join("?" for _ in bbls)
        rows = c.execute(
            f"SELECT bbl, tag FROM tags WHERE bbl IN ({placeholders}) ORDER BY tag",
            [str(b) for b in bbls],
        ).fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["bbl"], []).append(r["tag"])
        return out
    finally:
        if should_close:
            c.close()


# ── Named Site Collections CRUD ─────────────────────────────────────────

def create_collection(name: str, description: str = "",
                       conn: sqlite3.Connection | None = None) -> int:
    c, should_close = _with_conn(conn)
    try:
        now = _now()
        cur = c.execute(
            "INSERT INTO collections (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, description, now, now),
        )
        c.commit()
        return cur.lastrowid
    finally:
        if should_close:
            c.close()


def list_collections(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Every collection plus an `item_count` — one JOIN+GROUP BY query
    rather than N+1 per-collection COUNT queries."""
    c, should_close = _with_conn(conn)
    try:
        rows = c.execute(
            """
            SELECT c.*, COUNT(ci.id) AS item_count
            FROM collections c
            LEFT JOIN collection_items ci ON ci.collection_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if should_close:
            c.close()


def add_to_collection(collection_id: int, prop: dict,
                       conn: sqlite3.Connection | None = None) -> bool:
    """Upsert a property into a collection, keyed by (collection_id, bbl) —
    mirrors save_property()'s upsert pattern. Returns True (the row always
    exists after this call; INSERT vs UPDATE isn't distinguished, same
    spirit as save_property() not distinguishing new-vs-refreshed either)."""
    bbl = str(prop.get("bbl") or "").strip()
    if not bbl:
        raise ValueError("add_to_collection: prop['bbl'] is required and cannot be empty")
    c, should_close = _with_conn(conn)
    try:
        now = _now()
        c.execute(
            """
            INSERT INTO collection_items (collection_id, bbl, address, property_json, added_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(collection_id, bbl) DO UPDATE SET
                address       = excluded.address,
                property_json = excluded.property_json
            """,
            (collection_id, bbl, prop.get("address", ""), json.dumps(dict(prop)), now),
        )
        c.execute("UPDATE collections SET updated_at = ? WHERE id = ?", (now, collection_id))
        c.commit()
        return True
    finally:
        if should_close:
            c.close()


def remove_from_collection(collection_id: int, bbl: str,
                            conn: sqlite3.Connection | None = None) -> bool:
    c, should_close = _with_conn(conn)
    try:
        cur = c.execute(
            "DELETE FROM collection_items WHERE collection_id = ? AND bbl = ?",
            (collection_id, str(bbl)),
        )
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()


def list_collection_items(collection_id: int, conn: sqlite3.Connection | None = None) -> list[dict]:
    c, should_close = _with_conn(conn)
    try:
        rows = c.execute(
            "SELECT * FROM collection_items WHERE collection_id = ? ORDER BY added_at DESC",
            (collection_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["property"] = json.loads(d.pop("property_json"))
            except Exception:
                d["property"] = {}
                d.pop("property_json", None)
            out.append(d)
        return out
    finally:
        if should_close:
            c.close()


def delete_collection(collection_id: int, conn: sqlite3.Connection | None = None) -> bool:
    """Explicit two-step delete — this file never turns on `PRAGMA
    foreign_keys`, so collection_items rows for this collection would
    otherwise be silently orphaned rather than cascade-deleted."""
    c, should_close = _with_conn(conn)
    try:
        c.execute("DELETE FROM collection_items WHERE collection_id = ?", (collection_id,))
        cur = c.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        c.commit()
        return cur.rowcount > 0
    finally:
        if should_close:
            c.close()
