"""
App-wide Logging & Data Source Health.

The rest of the codebase swallows fetcher exceptions with bare
`except Exception:` blocks that return an empty/fallback shape — a
defensible way to keep the Streamlit app from crashing when one of a dozen
scrapers/APIs is unreachable, but it means outages are invisible: a user
sees "no results found" with no way to tell a genuine empty result from a
broken data source.

This module adds two lightweight, additive pieces (it does not change any
existing function's return shape or error-handling behavior):

  1. Standard `logging` — a rotating file handler under `logs/app.log`,
     plus an in-memory ring buffer so a deployed user without terminal/SSH
     access can still see recent errors from inside the UI.
  2. `record_source_status()` — a tiny in-session registry of "did the
     last call to source X succeed", rendered by app.py as a sidebar
     "Data Health" panel.

Usage (from app.py, once, near the top before the sidebar is built):
    from modules.app_logging import init_logging
    init_logging()

Usage (from a fetcher call site, e.g. next to an existing
`st.session_state[key] = fetch_x(...)` line):
    from modules.app_logging import get_logger, record_source_status
    log = get_logger(__name__)
    result = fetch_x(...)
    ok = not result.get("error")
    record_source_status("ACRIS", ok, result.get("error") or "")
    if not ok:
        log.warning("ACRIS fetch failed: %s", result.get("error"))
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from collections import deque

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(os.path.dirname(_HERE), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

_RING_BUFFER_SIZE = 200
_ring_buffer: deque = deque(maxlen=_RING_BUFFER_SIZE)

_ROOT_NAME = "re_diligence"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _RingBufferHandler(logging.Handler):
    """Keeps the last N formatted log lines in memory for in-UI display."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _ring_buffer.append(self.format(record))
        except Exception:
            pass


def init_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Configure the app's root logger once per process.

    Idempotent by design: Streamlit re-executes the whole script top-to-
    bottom on every user interaction, so this must be safe to call on every
    rerun without stacking duplicate handlers (which would otherwise
    multiply every log line by the number of reruns so far).
    """
    root = logging.getLogger(_ROOT_NAME)
    if root.handlers:
        return root

    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=2_000_000, backupCount=3
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception:
        # Read-only filesystem or similar deployment constraint — the
        # in-memory ring buffer below still works, so logging degrades
        # gracefully rather than crashing app startup.
        pass

    ring_handler = _RingBufferHandler()
    ring_handler.setFormatter(formatter)
    root.addHandler(ring_handler)

    root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the app's root logger namespace."""
    short = name.rsplit(".", 1)[-1] if name else "app"
    return logging.getLogger(f"{_ROOT_NAME}.{short}")


def get_recent_logs() -> list[str]:
    """Most-recent-last list of formatted log lines currently in the ring buffer."""
    return list(_ring_buffer)


def record_source_status(name: str, ok: bool, detail: str = "") -> None:
    """
    Record the outcome of the most recent call to a named data source into
    `st.session_state["_source_health"]`, for the sidebar Data Health panel.

    Streamlit is imported lazily inside the function body so this module
    stays importable (and unit-testable) outside a Streamlit runtime.
    """
    try:
        import streamlit as st
        from datetime import datetime, timezone

        st.session_state.setdefault("_source_health", {})
        st.session_state["_source_health"][name] = {
            "ok": bool(ok),
            "detail": detail or "",
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
    except Exception:
        # Never let health-tracking itself break a data-fetching code path.
        pass
