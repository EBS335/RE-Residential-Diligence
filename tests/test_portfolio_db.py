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


# ── Diligence Checklist/Tracker ──────────────────────────────────────────────

def test_add_and_list_diligence_items(conn):
    pdb.add_diligence_item("3001", "Title", "Order title report", conn=conn)
    pdb.add_diligence_item("3001", "Zoning", "Confirm zoning district", conn=conn)
    items = pdb.list_diligence_items("3001", conn=conn)
    assert len(items) == 2
    assert items[0]["is_complete"] == 0
    assert items[0]["notes"] == ""


def test_diligence_items_scoped_by_bbl(conn):
    pdb.add_diligence_item("3001", "Title", "Order title report", conn=conn)
    pdb.add_diligence_item("3002", "Title", "Order title report", conn=conn)
    assert len(pdb.list_diligence_items("3001", conn=conn)) == 1
    assert len(pdb.list_diligence_items("3002", conn=conn)) == 1


def test_update_diligence_item_completion_and_notes(conn):
    item = pdb.add_diligence_item("3001", "Title", "Order title report", conn=conn)
    assert pdb.update_diligence_item(item["id"], is_complete=True, notes="Ordered 1/1", conn=conn) is True
    updated = pdb.list_diligence_items("3001", conn=conn)[0]
    assert updated["is_complete"] == 1
    assert updated["notes"] == "Ordered 1/1"


def test_update_diligence_item_no_fields_returns_false(conn):
    item = pdb.add_diligence_item("3001", "Title", "Order title report", conn=conn)
    assert pdb.update_diligence_item(item["id"], conn=conn) is False


def test_delete_diligence_item(conn):
    item = pdb.add_diligence_item("3001", "Title", "Order title report", conn=conn)
    assert pdb.delete_diligence_item(item["id"], conn=conn) is True
    assert pdb.list_diligence_items("3001", conn=conn) == []


def test_diligence_progress_computed_correctly(conn):
    i1 = pdb.add_diligence_item("3001", "Title", "A", conn=conn)
    i2 = pdb.add_diligence_item("3001", "Title", "B", conn=conn)
    pdb.add_diligence_item("3001", "Title", "C", conn=conn)
    pdb.update_diligence_item(i1["id"], is_complete=True, conn=conn)
    pdb.update_diligence_item(i2["id"], is_complete=True, conn=conn)
    progress = pdb.diligence_progress("3001", conn=conn)
    assert progress == {"total": 3, "complete": 2, "pct": pytest.approx(66.666, rel=1e-3)}


def test_diligence_progress_empty_bbl_zero_not_divide_by_zero(conn):
    progress = pdb.diligence_progress("nonexistent", conn=conn)
    assert progress == {"total": 0, "complete": 0, "pct": 0.0}


def test_seed_default_checklist_populates_once(conn):
    items = pdb.seed_default_checklist("3001", conn=conn)
    assert len(items) == len(pdb.DEFAULT_CHECKLIST)
    # Calling again must NOT duplicate rows.
    items2 = pdb.seed_default_checklist("3001", conn=conn)
    assert len(items2) == len(pdb.DEFAULT_CHECKLIST)
    assert len(pdb.list_diligence_items("3001", conn=conn)) == len(pdb.DEFAULT_CHECKLIST)


def test_seed_default_checklist_categories_match_source_list(conn):
    items = pdb.seed_default_checklist("3001", conn=conn)
    categories = {i["category"] for i in items}
    assert categories == {c for c, _ in pdb.DEFAULT_CHECKLIST}


# ── Outreach Tracker ──────────────────────────────────────────────────────

def test_upsert_outreach_requires_bbl(conn):
    with pytest.raises(ValueError):
        pdb.upsert_outreach("", status="Contacted", conn=conn)


def test_upsert_outreach_inserts_new_row(conn):
    row = pdb.upsert_outreach("6001", status="Contacted", notes="Left voicemail", conn=conn)
    assert row["bbl"] == "6001"
    assert row["status"] == "Contacted"
    assert row["notes"] == "Left voicemail"
    assert row["follow_up_date"] is None
    assert row["last_contacted_at"] is not None  # auto-stamped: status != "Not Contacted"
    assert row["created_at"] == row["updated_at"]


def test_upsert_outreach_default_status_not_contacted(conn):
    row = pdb.upsert_outreach("6002", conn=conn)
    assert row["status"] == "Not Contacted"
    assert row["last_contacted_at"] is None  # never auto-stamped for the default status


def test_upsert_outreach_partial_update_status_only(conn):
    pdb.upsert_outreach("6003", status="Contacted", follow_up_date="2026-09-01", notes="Initial note", conn=conn)
    updated = pdb.upsert_outreach("6003", status="Responded", conn=conn)
    assert updated["status"] == "Responded"
    # follow_up_date/notes untouched by the status-only update
    assert updated["follow_up_date"] == "2026-09-01"
    assert updated["notes"] == "Initial note"


def test_upsert_outreach_partial_update_notes_only(conn):
    pdb.upsert_outreach("6004", status="Contacted", follow_up_date="2026-09-01", notes="Initial note", conn=conn)
    updated = pdb.upsert_outreach("6004", notes="Updated note", conn=conn)
    assert updated["notes"] == "Updated note"
    # status/follow_up_date untouched by the notes-only update
    assert updated["status"] == "Contacted"
    assert updated["follow_up_date"] == "2026-09-01"


def test_upsert_outreach_idempotent_by_bbl(conn):
    pdb.upsert_outreach("6005", status="Contacted", conn=conn)
    pdb.upsert_outreach("6005", status="Responded", conn=conn)
    assert len(pdb.list_outreach(conn=conn)) == 1
    assert pdb.get_outreach("6005", conn=conn)["status"] == "Responded"


def test_get_outreach_missing_bbl_returns_none(conn):
    assert pdb.get_outreach("nonexistent", conn=conn) is None


def test_list_outreach_returns_all_rows(conn):
    pdb.upsert_outreach("6006", status="Contacted", conn=conn)
    pdb.upsert_outreach("6007", status="Passed", conn=conn)
    rows = pdb.list_outreach(conn=conn)
    assert len(rows) == 2
    assert {r["bbl"] for r in rows} == {"6006", "6007"}


# ── Tags/Labels ─────────────────────────────────────────────────────────

def test_add_tag_inserts_and_reports_true(conn):
    assert pdb.add_tag("7001", "Hot", conn=conn) is True
    assert pdb.list_tags("7001", conn=conn) == ["Hot"]


def test_add_tag_idempotent_re_add_via_unique_constraint(conn):
    assert pdb.add_tag("7001", "Hot", conn=conn) is True
    # Re-adding the same (bbl, tag) pair is a harmless no-op — UNIQUE
    # constraint + INSERT OR IGNORE — and reports False (nothing inserted).
    assert pdb.add_tag("7001", "Hot", conn=conn) is False
    assert pdb.list_tags("7001", conn=conn) == ["Hot"]


def test_remove_tag(conn):
    pdb.add_tag("7002", "Watch", conn=conn)
    assert pdb.remove_tag("7002", "Watch", conn=conn) is True
    assert pdb.list_tags("7002", conn=conn) == []
    assert pdb.remove_tag("7002", "Watch", conn=conn) is False  # already gone


def test_list_tags_scoped_by_bbl(conn):
    pdb.add_tag("7003", "Hot", conn=conn)
    pdb.add_tag("7003", "Pass", conn=conn)
    pdb.add_tag("7004", "Watch", conn=conn)
    assert sorted(pdb.list_tags("7003", conn=conn)) == ["Hot", "Pass"]
    assert pdb.list_tags("7004", conn=conn) == ["Watch"]


def test_list_tags_bulk_groups_correctly(conn):
    pdb.add_tag("7005", "Hot", conn=conn)
    pdb.add_tag("7005", "Watch", conn=conn)
    pdb.add_tag("7006", "Pass", conn=conn)
    result = pdb.list_tags_bulk(["7005", "7006", "7999"], conn=conn)
    assert sorted(result["7005"]) == ["Hot", "Watch"]
    assert result["7006"] == ["Pass"]
    assert "7999" not in result  # no tags -> not present in the dict at all


def test_list_tags_bulk_empty_list_returns_empty_dict_no_query(conn):
    # Passing an empty list must short-circuit before touching the DB —
    # verified by monkeypatching conn.execute to raise if it's ever called.
    class _ExplodingConn:
        def execute(self, *a, **kw):
            raise AssertionError("list_tags_bulk([]) must not query the DB")

    assert pdb.list_tags_bulk([], conn=_ExplodingConn()) == {}


# ── Named Site Collections ─────────────────────────────────────────────

def test_create_collection_returns_int_id(conn):
    cid = pdb.create_collection("Q3 Brooklyn Shortlist", "A few good corner lots", conn=conn)
    assert isinstance(cid, int)


def test_list_collections_includes_item_count(conn):
    cid = pdb.create_collection("Test Collection", conn=conn)
    assert pdb.list_collections(conn=conn)[0]["item_count"] == 0

    pdb.add_to_collection(cid, {"bbl": "8001", "address": "1 Test St"}, conn=conn)
    pdb.add_to_collection(cid, {"bbl": "8002", "address": "2 Test St"}, conn=conn)
    collections = pdb.list_collections(conn=conn)
    assert len(collections) == 1
    assert collections[0]["item_count"] == 2
    assert collections[0]["name"] == "Test Collection"


def test_add_to_collection_requires_bbl(conn):
    cid = pdb.create_collection("Test Collection", conn=conn)
    with pytest.raises(ValueError):
        pdb.add_to_collection(cid, {"address": "no bbl here"}, conn=conn)


def test_add_to_collection_upsert_semantics(conn):
    cid = pdb.create_collection("Test Collection", conn=conn)
    pdb.add_to_collection(cid, {"bbl": "8003", "address": "Old Address", "lot_sf": 1000.0}, conn=conn)
    pdb.add_to_collection(cid, {"bbl": "8003", "address": "New Address", "lot_sf": 2000.0}, conn=conn)

    items = pdb.list_collection_items(cid, conn=conn)
    assert len(items) == 1  # upsert, not a duplicate row
    assert items[0]["address"] == "New Address"
    assert items[0]["property"]["lot_sf"] == 2000.0


def test_remove_from_collection(conn):
    cid = pdb.create_collection("Test Collection", conn=conn)
    pdb.add_to_collection(cid, {"bbl": "8004", "address": "A"}, conn=conn)
    assert pdb.remove_from_collection(cid, "8004", conn=conn) is True
    assert pdb.list_collection_items(cid, conn=conn) == []
    assert pdb.remove_from_collection(cid, "8004", conn=conn) is False  # already gone


def test_list_collection_items_round_trips_property_json(conn):
    cid = pdb.create_collection("Test Collection", conn=conn)
    prop = {"bbl": "8005", "address": "A", "lot_sf": 5000.0, "far_max": 3.44}
    pdb.add_to_collection(cid, prop, conn=conn)
    items = pdb.list_collection_items(cid, conn=conn)
    assert items[0]["property"]["lot_sf"] == 5000.0
    assert items[0]["property"]["far_max"] == 3.44
    assert items[0]["bbl"] == "8005"


def test_delete_collection_cascades_to_items(conn):
    cid = pdb.create_collection("Test Collection", conn=conn)
    pdb.add_to_collection(cid, {"bbl": "8006", "address": "A"}, conn=conn)
    pdb.add_to_collection(cid, {"bbl": "8007", "address": "B"}, conn=conn)

    assert pdb.delete_collection(cid, conn=conn) is True
    assert pdb.list_collections(conn=conn) == []
    # The items are actually gone, not orphaned — verified directly against
    # the table, since list_collection_items(cid) alone can't distinguish
    # "collection deleted" from "collection exists but is empty".
    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM collection_items WHERE collection_id = ?", (cid,)
    ).fetchone()
    assert remaining["n"] == 0


def test_delete_collection_missing_returns_false(conn):
    assert pdb.delete_collection(9999, conn=conn) is False
