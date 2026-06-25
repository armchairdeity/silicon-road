"""
Tests for the spreadsheet loader.
Run with: uv run pytest tests/
"""

from pathlib import Path

import pytest

from silicon_road.ingest.spreadsheet import Component, load_inventory

FIXTURE_XLSX = Path(__file__).parent / "fixtures" / "sample_inventory.xlsx"

# ──────────────────────────────────────────────────────────────────────────────
# Unit tests for Component
# ──────────────────────────────────────────────────────────────────────────────


def test_component_to_text_basic():
    c = Component(
        sheet="ICs",
        part_number="LM317T",
        manufacturer="Texas Instruments",
        description="Adjustable Voltage Regulator",
        package="TO-220",
        category="Voltage Regulator",
        supply_voltage="1.2-37",
        pincount="3",
        qty="4",
        location="Bin A3",
    )
    text = c.to_text()
    assert "LM317T" in text
    assert "Voltage Regulator" in text
    assert "Bin A3" in text
    assert "TO-220" in text


def test_component_doc_id_is_slugified():
    c = Component(sheet="ICs", part_number="TL494 CN")
    assert " " not in c.doc_id
    assert "/" not in c.doc_id


def test_component_doc_id_unique_by_sheet():
    c1 = Component(sheet="ICs", part_number="LM358")
    c2 = Component(sheet="Misc", part_number="LM358")
    assert c1.doc_id != c2.doc_id


def test_component_to_metadata_all_strings():
    c = Component(sheet="Capacitors", part_number="C100U", qty="10", supply_voltage="25")
    meta = c.to_metadata()
    for k, v in meta.items():
        assert isinstance(v, str), f"metadata[{k!r}] is {type(v)}, expected str"


def test_component_text_omits_datasheet_url():
    c = Component(
        sheet="ICs",
        part_number="NE555",
        datasheet_url="https://www.ti.com/lit/ds/symlink/ne555.pdf",
    )
    text = c.to_text()
    assert "http" not in text, "Datasheet URL should not appear in embedding text"


# ──────────────────────────────────────────────────────────────────────────────
# Integration test (requires the real inventory file)
# ──────────────────────────────────────────────────────────────────────────────

REAL_XLSX = (
    Path.home() / "Documents" / "Claude" / "documents" / "component_inventory.xlsx"
)


@pytest.mark.skipif(
    not REAL_XLSX.exists(), reason="Real inventory file not found; skipping integration test"
)
def test_load_real_inventory():
    components = load_inventory(REAL_XLSX)
    assert len(components) > 50, "Expected at least 50 components"
    # Every component must have a part number
    assert all(c.part_number for c in components)
    # Every component must have a non-empty text representation
    assert all(c.to_text() for c in components)
    # Doc IDs must be unique
    ids = [c.doc_id for c in components]
    assert len(ids) == len(set(ids)), "Doc IDs must be unique"
