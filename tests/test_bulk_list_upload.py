"""
Tests for modules/bulk_list_upload.py — the "Bring Your Own List" CSV
upload sourcing path (Batch A, Feature 4).
"""

from unittest.mock import patch

from modules.bulk_list_upload import parse_uploaded_list, resolve_addresses_to_bbls


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


# ── parse_uploaded_list() ───────────────────────────────────────────────────

def test_parse_bbl_column_lowercase():
    csv = "bbl,notes\n1000010001,foo\n1000020002,bar\n"
    bbls, addresses, status = parse_uploaded_list(_csv_bytes(csv))
    assert status["error"] is None
    assert status["rows_parsed"] == 2
    assert bbls == ["1000010001", "1000020002"]
    assert addresses == []


def test_parse_bbl_column_case_insensitive_uppercase_header():
    csv = "BBL\n1000010001\n"
    bbls, addresses, status = parse_uploaded_list(_csv_bytes(csv))
    assert status["error"] is None
    assert bbls == ["1000010001"]
    assert addresses == []


def test_parse_address_only_column():
    csv = 'address\n"123 Main St, Brooklyn NY"\n"456 Broadway, Manhattan NY"\n'
    bbls, addresses, status = parse_uploaded_list(_csv_bytes(csv))
    assert status["error"] is None
    assert status["rows_parsed"] == 2
    assert bbls == []
    assert addresses == ["123 Main St, Brooklyn NY", "456 Broadway, Manhattan NY"]


def test_parse_falls_back_to_first_column_when_no_bbl_or_address_header():
    csv = "site,notes\n123 Main St,foo\n"
    bbls, addresses, status = parse_uploaded_list(_csv_bytes(csv))
    assert status["error"] is None
    assert bbls == []
    assert addresses == ["123 Main St"]


def test_parse_bbl_column_preferred_over_address_column():
    csv = "address,bbl\n123 Main St,1000010001\n"
    bbls, addresses, status = parse_uploaded_list(_csv_bytes(csv))
    assert bbls == ["1000010001"]
    assert addresses == []


def test_parse_malformed_csv_bytes_sets_error_never_raises():
    # Invalid UTF-8 bytes -> pandas raises UnicodeDecodeError internally.
    bbls, addresses, status = parse_uploaded_list(b"\x00\x01\x02\xff\xfe")
    assert status["error"]
    assert bbls == []
    assert addresses == []


def test_parse_empty_csv_bytes_sets_error_never_raises():
    bbls, addresses, status = parse_uploaded_list(b"")
    assert status["error"]
    assert bbls == []
    assert addresses == []


def test_parse_header_only_csv_no_rows():
    csv = "bbl\n"
    bbls, addresses, status = parse_uploaded_list(_csv_bytes(csv))
    assert status["error"] is None  # valid CSV, just zero data rows — not a failure
    assert bbls == []
    assert status["rows_parsed"] == 0


def test_parse_bbl_values_strip_non_digits():
    csv = "bbl\n1-00001-0001\n"
    bbls, addresses, status = parse_uploaded_list(_csv_bytes(csv))
    assert status["error"] is None
    assert bbls == ["1000010001"]


# ── resolve_addresses_to_bbls() ─────────────────────────────────────────────

def test_resolve_addresses_to_bbls_mocked_geocode_success():
    with patch("modules.bulk_list_upload.time.sleep"), \
         patch("modules.bulk_list_upload.geosearch_bbl") as mock_geo:
        mock_geo.side_effect = [
            {"bbl": "1000010001", "label": "123 Main St", "lat": 40.7, "lon": -74.0},
            {"bbl": "1000020002", "label": "456 Broadway", "lat": 40.71, "lon": -74.01},
        ]
        resolved, unresolved = resolve_addresses_to_bbls(["123 Main St", "456 Broadway"])
    assert resolved == ["1000010001", "1000020002"]
    assert unresolved == []
    assert mock_geo.call_count == 2


def test_resolve_addresses_to_bbls_handles_misses_and_exceptions():
    with patch("modules.bulk_list_upload.time.sleep"), \
         patch("modules.bulk_list_upload.geosearch_bbl") as mock_geo:
        mock_geo.side_effect = [None, RuntimeError("boom"), {"bbl": "1000030003"}]
        resolved, unresolved = resolve_addresses_to_bbls(["nowhere", "boom addr", "good addr"])
    assert resolved == ["1000030003"]
    assert unresolved == ["nowhere", "boom addr"]


def test_resolve_addresses_to_bbls_respects_max_rows_and_calls_progress():
    calls = []
    with patch("modules.bulk_list_upload.time.sleep"), \
         patch("modules.bulk_list_upload.geosearch_bbl", return_value={"bbl": "1000010001"}):
        resolved, unresolved = resolve_addresses_to_bbls(
            ["a", "b", "c"], max_rows=2, progress_callback=lambda i, n: calls.append((i, n)),
        )
    assert len(resolved) == 2
    assert calls == [(1, 2), (2, 2)]


def test_resolve_addresses_to_bbls_empty_input():
    with patch("modules.bulk_list_upload.geosearch_bbl") as mock_geo:
        resolved, unresolved = resolve_addresses_to_bbls([])
    assert resolved == []
    assert unresolved == []
    mock_geo.assert_not_called()
