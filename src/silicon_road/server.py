"""
Silicon Road MCP Server.

Exposes the component inventory as MCP tools so Claude Desktop (and any other
MCP-capable client) can semantically search your scavenged parts bin.

Tools
─────
  search_inventory   — semantic search (uses Perplexity embeddings + ChromaDB)
  get_component      — direct lookup by part number (exact or prefix match)
  list_categories    — show which sheets/categories are loaded
  inventory_stats    — count per category + grand total

Run with:
  PERPLEXITY_API_KEY=<key> uv run mcsr
  # or
  PERPLEXITY_API_KEY=<key> uv run python -m silicon_road.server

Register in Claude Desktop claude_desktop_config.json:
  {
    "mcpServers": {
      "silicon-road": {
        "command": "uv",
        "args": ["run", "--directory",
                 "/Users/<you>/Developer/Python/silicon-road", "mcsr"],
        "env": {
          "PERPLEXITY_API_KEY": "<key>",
          "ANONYMIZED_TELEMETRY": "False"
        }
      }
    }
  }
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from silicon_road.embed.perplexity import embed_single
from silicon_road.store.chroma import get_collection, query_inventory

# ── Silence chromadb telemetry spam ──────────────────────────────────────────
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("posthog").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "silicon-road",
    instructions=(
        "Silicon Road gives you semantic search over a scavenged electronics "
        "component inventory. Use search_inventory to find parts by function, "
        "description, or specs. Use get_component for direct part-number lookup. "
        "Use inventory_stats or list_categories to understand what's available."
    ),
)

DEFAULT_DB_PATH: Path | None = None   # uses ~/.silicon_road/chroma


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_hit(hit: dict, rank: int) -> dict[str, Any]:
    m = hit["metadata"]
    score = max(0.0, 1.0 - hit["distance"] / 2.0)
    return {
        "rank": rank,
        "score": round(score, 3),
        "part_number": m.get("part_number", ""),
        "manufacturer": m.get("manufacturer", ""),
        "description": m.get("description", ""),
        "category": m.get("category", ""),
        "sheet": m.get("sheet", ""),
        "package": m.get("package", ""),
        "supply_voltage": m.get("supply_voltage", ""),
        "pincount": m.get("pincount", ""),
        "qty": m.get("qty", ""),
        "location": m.get("location", ""),
        "notes": m.get("notes", ""),
        "datasheet_url": m.get("datasheet_url", ""),
    }


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_inventory(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    """
    Semantic search over the scavenged component inventory.

    Args:
        query:     Natural language description of what you need.
                   Examples: "5V LDO regulator", "N-channel MOSFET 30V",
                   "audio power amplifier SIP package", "decoupling capacitor".
        n_results: How many results to return (default 5, max 20).

    Returns:
        List of matching components ranked by semantic similarity, each with
        part_number, manufacturer, description, package, qty, location, notes,
        datasheet_url, and a similarity score (0–1, higher = better match).
    """
    n_results = min(max(1, n_results), 20)
    collection = get_collection(DEFAULT_DB_PATH)

    if collection.count() == 0:
        return [{"error": "Inventory is empty. Run mcsr-ingest to load components."}]

    query_vec = embed_single(query)
    hits = query_inventory(collection, query_vec, n_results=n_results)
    return [_format_hit(h, i + 1) for i, h in enumerate(hits)]


@mcp.tool()
def get_component(part_number: str, sheet: str = "") -> list[dict[str, Any]]:
    """
    Direct lookup of a component by part number (case-insensitive, prefix match).

    Args:
        part_number: Full or partial part number to look up (e.g. "LM317", "NE555").
        sheet:       Optional sheet/category filter (e.g. "ICs", "Capacitors").
                     Leave blank to search all categories.

    Returns:
        List of matching components. Returns multiple if part number is ambiguous.
    """
    collection = get_collection(DEFAULT_DB_PATH)
    if collection.count() == 0:
        return [{"error": "Inventory is empty. Run mcsr-ingest to load components."}]

    where: dict = {}
    if sheet:
        where["sheet"] = {"$eq": sheet}

    # ChromaDB doesn't support substring match in metadata — fetch all and filter
    all_results = collection.get(where=where or None, include=["metadatas", "documents"])

    part_lower = part_number.lower()
    matches = []
    for meta in (all_results.get("metadatas") or []):
        pn = meta.get("part_number", "").lower()
        if pn.startswith(part_lower) or part_lower in pn:
            matches.append({
                "part_number": meta.get("part_number", ""),
                "manufacturer": meta.get("manufacturer", ""),
                "description": meta.get("description", ""),
                "category": meta.get("category", ""),
                "sheet": meta.get("sheet", ""),
                "package": meta.get("package", ""),
                "supply_voltage": meta.get("supply_voltage", ""),
                "pincount": meta.get("pincount", ""),
                "qty": meta.get("qty", ""),
                "location": meta.get("location", ""),
                "notes": meta.get("notes", ""),
                "datasheet_url": meta.get("datasheet_url", ""),
            })

    if not matches:
        return [{"message": f"No component found matching '{part_number}'"}]
    return matches


@mcp.tool()
def list_categories() -> list[dict[str, Any]]:
    """
    List all component categories (spreadsheet sheets) in the inventory,
    with a count of components per category.

    Returns:
        List of {category, count} dicts.
    """
    collection = get_collection(DEFAULT_DB_PATH)
    if collection.count() == 0:
        return [{"error": "Inventory is empty. Run mcsr-ingest to load components."}]

    all_meta = collection.get(include=["metadatas"]).get("metadatas") or []
    counts: dict[str, int] = {}
    for m in all_meta:
        sheet = m.get("sheet", "Unknown")
        counts[sheet] = counts.get(sheet, 0) + 1

    return [
        {"category": sheet, "count": count}
        for sheet, count in sorted(counts.items(), key=lambda x: -x[1])
    ]


@mcp.tool()
def inventory_stats() -> dict[str, Any]:
    """
    Summary statistics for the loaded component inventory.

    Returns:
        Total component count, count per category, and database path.
    """
    collection = get_collection(DEFAULT_DB_PATH)
    total = collection.count()
    if total == 0:
        return {"total": 0, "message": "Inventory is empty. Run mcsr-ingest to load components."}

    all_meta = collection.get(include=["metadatas"]).get("metadatas") or []
    by_category: dict[str, int] = {}
    for m in all_meta:
        sheet = m.get("sheet", "Unknown")
        by_category[sheet] = by_category.get(sheet, 0) + 1

    return {
        "total": total,
        "by_category": dict(sorted(by_category.items(), key=lambda x: -x[1])),
        "db_path": str(Path.home() / ".silicon_road" / "chroma"),
        "embed_model": "pplx-embed-v1-4b",
        "embed_dims": 2560,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
