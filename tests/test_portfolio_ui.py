"""
AppTest-driven checks for modules/portfolio_ui.py's new
"_render_outreach_summary()" section (Batch E, Feature 8) — the
Portfolio-tab summary table over the new `outreach` DB table.

Uses a per-test temp SQLite file (monkeypatched onto
modules.portfolio_db.DB_PATH) so these tests never touch the real
data/portfolio.db the running app uses.
"""

import os

from streamlit.testing.v1 import AppTest

from modules import portfolio_db as pdb

_APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _isolated_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_portfolio.db")
    monkeypatch.setattr(pdb, "DB_PATH", db_path)
    return db_path


def test_outreach_summary_empty_state_renders_without_exception(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()

    assert not at.exception
    info_messages = [i.value for i in at.info]
    assert any("No outreach logged yet" in m for m in info_messages)


def test_outreach_summary_populated_state_renders_without_exception(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    pdb.upsert_outreach("1001234567", status="Contacted", follow_up_date="2026-09-01", notes="Left voicemail")
    pdb.upsert_outreach("1007654321", status="Responded", notes="Interested — schedule call")

    at = AppTest.from_file(_APP_PATH, default_timeout=60)
    at.run()

    assert not at.exception
    dataframes = [el.value for el in at.dataframe]
    outreach_dfs = [
        df for df in dataframes
        if "Status" in df.columns and "Follow-up date" in df.columns and "BBL" in df.columns
    ]
    assert outreach_dfs, "expected the outreach summary dataframe to be rendered"
    df = outreach_dfs[0]
    assert len(df) == 2
    assert set(df["BBL"]) == {"1001234567", "1007654321"}
    assert "Contacted" in set(df["Status"])
    assert "Responded" in set(df["Status"])
