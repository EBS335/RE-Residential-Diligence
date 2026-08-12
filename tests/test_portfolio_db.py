import sqlite3

import pytest

from modules import portfolio_db as pdb


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    pdb.init_schema(c)
    yield c
    c.close()


def test_save_property_requires_bbl(conn):
    with pytest.raises(ValueError):
        pdb.save_property({"address": "no bbl here"}, conn=conn)


def test_save_property_upserts_by_bbl(conn):
    prop1 = {"bbl": "1001234567", "address": "123 Main St", "borough": "Manhattan",
             "deal_score": {"score": 70, "tier": "Watch"}}
    saved1 = pdb.save_property(prop1, conn=conn)
    assert saved1["deal_score"] == 70.0
    assert saved1["status"] == "Watching"

    prop2 = dict(prop1)
    prop2["deal_score"] = {"score": 95, "tier": "Strong Lead"}
    saved2 = pdb.save_property(prop2, conn=conn)

    assert saved2["deal_score"] == 95.0
    # Same BBL -> single row, added_at preserved across the upsert
    assert saved2["added_at"] == saved1["added_at"]
    assert len(pdb.list_portfolio(conn=conn)) == 1


def test_update_status_partial(conn):
    pdb.save_property({"bbl": "2001", "address": "A"}, conn=conn)
    ok = pdb.update_status("2001", status="Under Contract", conn=conn)
    assert ok is True

    row = pdb.get_property("2001", conn=conn)
    assert row["status"] == "Under Contract"
    assert row["notes"] == ""  # untouched by the status-only update

    pdb.update_status("2001", notes="Great corner lot", conn=conn)
    row2 = pdb.get_property("2001", conn=conn)
    assert row2["status"] == "Under Contract"  # untouched by the notes-only update
    assert row2["notes"] == "Great corner lot"


def test_update_status_missing_bbl_returns_false(conn):
    assert pdb.update_status("nonexistent", status="Passed", conn=conn) is False


def test_list_portfolio_filters_by_status(conn):
    pdb.save_property({"bbl": "3001", "address": "A"}, status="Watching", conn=conn)
    pdb.save_property({"bbl": "3002", "address": "B"}, status="Passed", conn=conn)

    watching = pdb.list_portfolio(status="Watching", conn=conn)
    assert len(watching) == 1
    assert watching[0]["bbl"] == "3001"

    all_rows = pdb.list_portfolio(conn=conn)
    assert len(all_rows) == 2


def test_remove_property(conn):
    pdb.save_property({"bbl": "4001", "address": "A"}, conn=conn)
    assert pdb.remove_property("4001", conn=conn) is True
    assert pdb.get_property("4001", conn=conn) is None
    assert pdb.remove_property("4001", conn=conn) is False  # already gone


def test_property_json_round_trips(conn):
    prop = {"bbl": "5001", "address": "A", "lot_sf": 5000.0, "far_max": 3.44}
    pdb.save_property(prop, conn=conn)
    row = pdb.get_property("5001", conn=conn)
    assert row["property"]["lot_sf"] == 5000.0
    assert row["property"]["far_max"] == 3.44


def test_saved_search_crud_round_trip(conn):
    sid = pdb.save_search("Brooklyn Vacant Lots", {"boroughs": ["Brooklyn"], "min_far": 2.0}, conn=conn)
    assert isinstance(sid, int)

    searches = pdb.list_saved_searches(conn=conn)
    assert len(searches) == 1
    assert searches[0]["name"] == "Brooklyn Vacant Lots"
    assert searches[0]["criteria"]["boroughs"] == ["Brooklyn"]

    fetched = pdb.get_saved_search(sid, conn=conn)
    assert fetched["criteria"]["min_far"] == 2.0

    pdb.touch_search_last_run(sid, conn=conn)
    touched = pdb.get_saved_search(sid, conn=conn)
    assert touched["last_run_at"] is not None

    assert pdb.delete_saved_search(sid, conn=conn) is True
    assert pdb.list_saved_searches(conn=conn) == []


def test_get_saved_search_missing_returns_none(conn):
    assert pdb.get_saved_search(9999, conn=conn) is None
