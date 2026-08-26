"""
Tests for modules/portfolio_ui.py's Feature 11 — Kanban Pipeline Board:
  - _render_kanban_board() groups rows by portfolio_db.STATUSES correctly
  - the ◀/▶ buttons call the EXISTING update_status() with the correct
    adjacent status, and disable at the first/last status

Uses a per-test temp SQLite file (monkeypatched onto
modules.portfolio_db.DB_PATH), the exact fixture pattern established in
tests/test_portfolio_ui.py (Batch E).
"""

import os

from streamlit.testing.v1 import AppTest

from modules import portfolio_db as pdb
from modules.portfolio_ui import _render_kanban_board

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _isolated_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_portfolio.db")
    monkeypatch.setattr(pdb, "DB_PATH", db_path)
    return db_path


# ── Direct unit-level coverage of _render_kanban_board() via AppTest.run(fn) ──

def _seed_two_properties(conn=None):
    pdb.save_property(
        {"bbl": "9001", "address": "1 Kanban St", "borough": "Brooklyn",
         "deal_score": {"score": 88, "tier": "Strong Lead"}},
        status="Watching",
    )
    pdb.save_property(
        {"bbl": "9002", "address": "2 Kanban St", "borough": "Brooklyn",
         "deal_score": {"score": 55, "tier": "Watch"}},
        status="Under Diligence",
    )


def test_kanban_board_groups_rows_by_status(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    _seed_two_properties()

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_portfolio_view_mode"] = "🗂️ Kanban"
    at.run()

    assert not at.exception
    markdown_values = [m.value for m in at.markdown]
    # One card per property, grouped under its own status column.
    assert any("1 Kanban St" in m for m in markdown_values)
    assert any("2 Kanban St" in m for m in markdown_values)
    # Column headers show the STATUSES-derived per-column counts.
    assert any(m.startswith("**Watching**") for m in markdown_values)
    assert any(m.startswith("**Under Diligence**") for m in markdown_values)


def test_kanban_view_toggle_renders_without_exception_empty_state(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_portfolio_view_mode"] = "🗂️ Kanban"
    at.run()

    assert not at.exception
    info_messages = [i.value for i in at.info]
    assert any("Nothing saved yet" in m for m in info_messages)


def test_table_view_is_default_pipeline_table_still_renders(tmp_path, monkeypatch):
    """The existing Pipeline table is completely unmodified and stays the
    default view when the radio isn't switched to Kanban."""
    _isolated_db(tmp_path, monkeypatch)
    _seed_two_properties()

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()

    assert not at.exception
    dataframes = [el.value for el in at.dataframe]
    pipeline_dfs = [df for df in dataframes if "Status" in df.columns and "Deal Score" in df.columns and "BBL" in df.columns]
    assert pipeline_dfs, "expected the existing Pipeline table to still render by default"


def test_prev_button_calls_update_status_with_adjacent_status(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    pdb.save_property(
        {"bbl": "9003", "address": "3 Kanban St", "borough": "Brooklyn"},
        status="Under Diligence",
    )

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_portfolio_view_mode"] = "🗂️ Kanban"
    at.run()
    assert not at.exception

    at.button(key="_portfolio_kanban_prev_9003").click().run()
    assert not at.exception

    row = pdb.get_property("9003")
    assert row["status"] == "Watching"  # the status immediately before "Under Diligence"


def test_next_button_calls_update_status_with_adjacent_status(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    pdb.save_property(
        {"bbl": "9004", "address": "4 Kanban St", "borough": "Brooklyn"},
        status="Watching",
    )

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_portfolio_view_mode"] = "🗂️ Kanban"
    at.run()
    assert not at.exception

    at.button(key="_portfolio_kanban_next_9004").click().run()
    assert not at.exception

    row = pdb.get_property("9004")
    assert row["status"] == "Under Diligence"  # the status immediately after "Watching"


def test_first_status_prev_button_disabled(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    pdb.save_property({"bbl": "9005", "address": "5 Kanban St"}, status=pdb.STATUSES[0])

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_portfolio_view_mode"] = "🗂️ Kanban"
    at.run()
    assert not at.exception

    prev_btn = at.button(key="_portfolio_kanban_prev_9005")
    assert prev_btn.disabled is True


def test_last_status_next_button_disabled(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    pdb.save_property({"bbl": "9006", "address": "6 Kanban St"}, status=pdb.STATUSES[-1])

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()
    at.session_state["_portfolio_view_mode"] = "🗂️ Kanban"
    at.run()
    assert not at.exception

    next_btn = at.button(key="_portfolio_kanban_next_9006")
    assert next_btn.disabled is True
