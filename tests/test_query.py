"""
Tests for the query layer and ChromaDB store.
All tests use mocks — no live API calls or real ChromaDB writes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

FAKE_VECTOR = [0.1] * 2560   # unit-ish vector, right dimensionality

FAKE_HIT = {
    "id": "ics_ne555",
    "document": "Category: ICs. Part number: NE555. Manufacturer: Texas Instruments.",
    "metadata": {
        "sheet": "ICs",
        "part_number": "NE555",
        "manufacturer": "Texas Instruments",
        "description": "Timer IC",
        "package": "DIP-8",
        "category": "Timers",
        "supply_voltage": "5-15",
        "pincount": "8",
        "qty": "3",
        "location": "Bin C1",
        "notes": "Classic astable/monostable timer",
        "datasheet_url": "https://www.ti.com/lit/ds/symlink/ne555.pdf",
    },
    "distance": 0.05,  # very close match
}


# ──────────────────────────────────────────────────────────────────────────────
# store.chroma tests
# ──────────────────────────────────────────────────────────────────────────────

class TestQueryInventory:
    def test_returns_ranked_hits(self):
        """query_inventory should return hits sorted by distance."""
        from silicon_road.store.chroma import query_inventory

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["ics_ne555", "ics_lm555"]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[FAKE_HIT["metadata"], {**FAKE_HIT["metadata"], "part_number": "LM555"}]],
            "distances": [[0.05, 0.12]],
        }

        hits = query_inventory(mock_collection, FAKE_VECTOR, n_results=2)
        assert len(hits) == 2
        assert hits[0]["distance"] < hits[1]["distance"]
        assert hits[0]["metadata"]["part_number"] == "NE555"

    def test_empty_collection_returns_empty(self):
        from silicon_road.store.chroma import query_inventory

        mock_collection = MagicMock()
        mock_collection.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        hits = query_inventory(mock_collection, FAKE_VECTOR, n_results=5)
        assert hits == []

    def test_where_filter_passed_through(self):
        from silicon_road.store.chroma import query_inventory

        mock_collection = MagicMock()
        mock_collection.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        query_inventory(mock_collection, FAKE_VECTOR, n_results=3, where={"sheet": {"$eq": "ICs"}})
        call_kwargs = mock_collection.query.call_args.kwargs
        assert call_kwargs["where"] == {"sheet": {"$eq": "ICs"}}


# ──────────────────────────────────────────────────────────────────────────────
# query.py tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSearch:
    @patch("silicon_road.query.get_collection")
    @patch("silicon_road.query.embed_single")
    @patch("silicon_road.query.query_inventory")
    def test_search_returns_hits(self, mock_qi, mock_embed, mock_gc):
        from silicon_road.query import search

        mock_collection = MagicMock()
        mock_collection.count.return_value = 117
        mock_gc.return_value = mock_collection
        mock_embed.return_value = FAKE_VECTOR
        mock_qi.return_value = [FAKE_HIT]

        hits = search("timer IC 5V")
        assert len(hits) == 1
        assert hits[0]["metadata"]["part_number"] == "NE555"
        mock_embed.assert_called_once_with("timer IC 5V")

    @patch("silicon_road.query.get_collection")
    def test_search_raises_when_empty(self, mock_gc):
        from silicon_road.query import search

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_gc.return_value = mock_collection

        with pytest.raises(RuntimeError, match="empty"):
            search("anything")

    @patch("silicon_road.query.get_collection")
    @patch("silicon_road.query.embed_single")
    @patch("silicon_road.query.query_inventory")
    def test_search_respects_n_results(self, mock_qi, mock_embed, mock_gc):
        from silicon_road.query import search

        mock_collection = MagicMock()
        mock_collection.count.return_value = 117
        mock_gc.return_value = mock_collection
        mock_embed.return_value = FAKE_VECTOR
        mock_qi.return_value = [FAKE_HIT]

        search("decoupling cap", n_results=10)
        mock_qi.assert_called_once()
        assert mock_qi.call_args.kwargs["n_results"] == 10


# ──────────────────────────────────────────────────────────────────────────────
# server.py MCP tool tests
# ──────────────────────────────────────────────────────────────────────────────

class TestMCPTools:
    @patch("silicon_road.server.get_collection")
    @patch("silicon_road.server.embed_single")
    @patch("silicon_road.server.query_inventory")
    def test_search_inventory_tool(self, mock_qi, mock_embed, mock_gc):
        from silicon_road.server import search_inventory

        mock_collection = MagicMock()
        mock_collection.count.return_value = 117
        mock_gc.return_value = mock_collection
        mock_embed.return_value = FAKE_VECTOR
        mock_qi.return_value = [FAKE_HIT]

        results = search_inventory("NE555 timer", n_results=1)
        assert isinstance(results, list)
        assert results[0]["part_number"] == "NE555"
        assert "score" in results[0]
        assert results[0]["rank"] == 1

    @patch("silicon_road.server.get_collection")
    @patch("silicon_road.server.embed_single")
    @patch("silicon_road.server.query_inventory")
    def test_search_inventory_caps_n_results(self, mock_qi, mock_embed, mock_gc):
        from silicon_road.server import search_inventory

        mock_collection = MagicMock()
        mock_collection.count.return_value = 117
        mock_gc.return_value = mock_collection
        mock_embed.return_value = FAKE_VECTOR
        mock_qi.return_value = []

        search_inventory("anything", n_results=999)
        # should be capped at 20
        assert mock_qi.call_args.kwargs["n_results"] == 20

    @patch("silicon_road.server.get_collection")
    def test_inventory_stats_empty(self, mock_gc):
        from silicon_road.server import inventory_stats

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_gc.return_value = mock_collection

        result = inventory_stats()
        assert result["total"] == 0

    @patch("silicon_road.server.get_collection")
    def test_list_categories_groups_by_sheet(self, mock_gc):
        from silicon_road.server import list_categories

        mock_collection = MagicMock()
        mock_collection.count.return_value = 3
        mock_collection.get.return_value = {
            "metadatas": [
                {"sheet": "ICs"},
                {"sheet": "ICs"},
                {"sheet": "Capacitors"},
            ]
        }
        mock_gc.return_value = mock_collection

        cats = list_categories()
        sheets = {c["category"] for c in cats}
        assert "ICs" in sheets
        assert "Capacitors" in sheets
        ics = next(c for c in cats if c["category"] == "ICs")
        assert ics["count"] == 2
