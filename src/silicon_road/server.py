"""
Silicon Road MCP Server.

Exposes the component inventory as MCP tools so Claude Desktop (and any other
MCP-capable client) can semantically search your scavenged parts bin.

Tools
─────
  search_inventory   — semantic search (uses Perplexity embeddings + ChromaDB)
  get_component      — direct lookup by part number (exact or prefix match)
  add_component      — embed and store a new component directly (no xlsx required)
  update_quantity    — delta-based or absolute quantity adjustment
  remove_component   — permanently delete a component from the inventory
  list_categories    — show which sheets/categories are loaded
  inventory_stats    — count per category + grand total

Run with:
  PERPLEXITY_API_KEY=<key> uv run mcsr          # stdio (Claude Desktop spawns it)
  PERPLEXITY_API_KEY=<key> uv run mcsr-sse      # SSE on 127.0.0.1:8765 (launchd)

Register in Claude Desktop claude_desktop_config.json (stdio):
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

Register in Claude Desktop claude_desktop_config.json (SSE / launchd):
  {
    "mcpServers": {
      "silicon-road": {
        "url": "http://127.0.0.1:8765/sse"
      }
    }
  }
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from silicon_road.embed.perplexity import embed_single
from silicon_road.ingest.spreadsheet import Component
from silicon_road.store.chroma import (
    delete_components,
    get_collection,
    query_inventory,
    upsert_components,
)

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
        "Use add_component to add or fully update a component. "
        "Use update_quantity to adjust stock levels (delta or absolute). "
        "Use remove_component to delete a component permanently. "
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


def _find_matching_ids_and_meta(
    collection, part_number: str, sheet: str
) -> list[tuple[str, dict]]:
    """
    Return [(doc_id, metadata), ...] for all entries matching part_number + sheet.
    Uses exact part_number match (case-insensitive) within the given sheet.
    """
    where: dict = {"sheet": {"$eq": sheet}}
    results = collection.get(where=where, include=["metadatas", "documents"])

    ids = results.get("ids") or []
    metas = results.get("metadatas") or []
    part_lower = part_number.strip().lower()

    matches = []
    for doc_id, meta in zip(ids, metas):
        if meta.get("part_number", "").lower() == part_lower:
            matches.append((doc_id, meta))
    return matches


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
def add_component(
    part_number: str,
    sheet: str,
    description: str = "",
    manufacturer: str = "",
    package: str = "",
    category: str = "",
    supply_voltage: str = "",
    pincount: str = "",
    datasheet_url: str = "",
    qty: str = "",
    location: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """
    Add or fully replace a single component in the vector database.

    Use this when you've identified a component (e.g. from a photo) and want
    to store it immediately without touching the spreadsheet. The component is
    embedded via Perplexity and upserted into ChromaDB — if the same part
    number already exists in the same sheet, all fields are replaced.

    To adjust quantity without replacing other fields, use update_quantity instead.

    Args:
        part_number:    Component part number, e.g. "LM317T", "2N3904". Required.
        sheet:          Inventory category. Use one of: ICs, Transistors, Diodes,
                        MOSFETs, Resistors, Capacitors, Inductors, Misc. Required.
        description:    Human-readable description of what the component does.
        manufacturer:   Manufacturer name, e.g. "Texas Instruments", "ON Semi".
        package:        Physical package, e.g. "TO-92", "DIP-8", "SOT-23".
        category:       Function/category label, e.g. "Voltage Regulator", "NPN BJT".
        supply_voltage: Operating voltage range, e.g. "3.3-40".
        pincount:       Number of pins as a string, e.g. "3", "8".
        datasheet_url:  URL to the datasheet PDF (optional but encouraged).
        qty:            Quantity on hand as a string, e.g. "12".
        location:       Bin or drawer label, e.g. "A3", "IC Drawer 2".
        notes:          Any additional notes about this specific component.

    Returns:
        Dict with doc_id, total inventory count after insert, and a confirmation.
    """
    if not part_number.strip():
        return {"error": "part_number is required"}
    if not sheet.strip():
        return {"error": "sheet is required (ICs, Transistors, Diodes, MOSFETs, "
                         "Resistors, Capacitors, Inductors, Misc)"}

    comp = Component(
        sheet=sheet.strip(),
        part_number=part_number.strip(),
        manufacturer=manufacturer.strip(),
        description=description.strip(),
        package=package.strip(),
        category=category.strip(),
        supply_voltage=supply_voltage.strip(),
        pincount=pincount.strip(),
        datasheet_url=datasheet_url.strip(),
        qty=qty.strip(),
        location=location.strip(),
        notes=notes.strip(),
    )

    text = comp.to_text()
    embedding = embed_single(text)

    collection = get_collection(DEFAULT_DB_PATH)
    upsert_components(
        collection=collection,
        ids=[comp.doc_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[comp.to_metadata()],
    )

    total = collection.count()
    return {
        "doc_id": comp.doc_id,
        "part_number": comp.part_number,
        "sheet": comp.sheet,
        "embedded_text": text,
        "total_in_inventory": total,
        "message": (
            f"✓ {comp.part_number} added to {comp.sheet} (doc_id: {comp.doc_id}). "
            f"Inventory now has {total} components."
        ),
    }


@mcp.tool()
def update_quantity(
    part_number: str,
    sheet: str,
    delta: Optional[int] = None,
    set_to: Optional[int] = None,
) -> dict[str, Any]:
    """
    Adjust the quantity of an existing component without changing any other fields.

    Provide either delta (relative change) or set_to (absolute value) — not both.

    Args:
        part_number: Exact part number of the component to update. Required.
        sheet:       Sheet/category the component lives in (e.g. "ICs"). Required.
        delta:       Relative quantity change. Positive to add stock (+3),
                     negative to remove stock (-1). Cannot make qty go below 0.
        set_to:      Set quantity to this exact value (must be >= 0).

    Returns:
        Dict with part_number, old_qty, new_qty, doc_id, and a confirmation message.

    Examples:
        Found 5 more LM317s in a drawer → update_quantity("LM317T", "ICs", delta=5)
        Used 2 capacitors → update_quantity("100nF", "Capacitors", delta=-2)
        Manual recount → update_quantity("2N3904", "Transistors", set_to=12)
    """
    if delta is None and set_to is None:
        return {"error": "Provide either delta or set_to"}
    if delta is not None and set_to is not None:
        return {"error": "Provide either delta or set_to, not both"}
    if set_to is not None and set_to < 0:
        return {"error": "set_to must be >= 0"}

    collection = get_collection(DEFAULT_DB_PATH)
    matches = _find_matching_ids_and_meta(collection, part_number, sheet)

    if not matches:
        return {"error": f"No component found: '{part_number}' in sheet '{sheet}'. "
                         "Use add_component to create it first."}
    if len(matches) > 1:
        return {
            "error": f"Ambiguous: {len(matches)} entries match '{part_number}' in '{sheet}'. "
                     "This shouldn't happen — check for duplicate doc_ids.",
            "matches": [m[0] for m in matches],
        }

    doc_id, meta = matches[0]

    # Parse current qty
    try:
        old_qty = int(meta.get("qty", "0") or "0")
    except ValueError:
        old_qty = 0

    if delta is not None:
        new_qty = max(0, old_qty + delta)
    else:
        new_qty = set_to  # type: ignore[assignment]

    # Rebuild Component with updated qty, re-embed, upsert
    comp = Component(
        sheet=meta.get("sheet", sheet),
        part_number=meta.get("part_number", part_number),
        manufacturer=meta.get("manufacturer", ""),
        description=meta.get("description", ""),
        package=meta.get("package", ""),
        category=meta.get("category", ""),
        supply_voltage=meta.get("supply_voltage", ""),
        pincount=meta.get("pincount", ""),
        datasheet_url=meta.get("datasheet_url", ""),
        qty=str(new_qty),
        location=meta.get("location", ""),
        notes=meta.get("notes", ""),
    )

    text = comp.to_text()
    embedding = embed_single(text)

    upsert_components(
        collection=collection,
        ids=[doc_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[comp.to_metadata()],
    )

    change = f"+{delta}" if (delta is not None and delta >= 0) else str(delta if delta is not None else f"→{new_qty}")
    return {
        "doc_id": doc_id,
        "part_number": comp.part_number,
        "sheet": comp.sheet,
        "old_qty": old_qty,
        "new_qty": new_qty,
        "message": f"✓ {comp.part_number} qty updated {old_qty} → {new_qty} (doc_id: {doc_id}).",
    }


@mcp.tool()
def remove_component(part_number: str, sheet: str) -> dict[str, Any]:
    """
    Permanently delete a component from the inventory.

    Use this when a component is lost, destroyed, or was added by mistake.
    This cannot be undone — the component will need to be re-added via
    add_component if removed in error.

    Args:
        part_number: Exact part number of the component to remove. Required.
        sheet:       Sheet/category the component lives in (e.g. "ICs"). Required.

    Returns:
        Dict with the deleted doc_id(s), remaining inventory count, and a
        confirmation message. Returns an error if the component is not found.
    """
    if not part_number.strip():
        return {"error": "part_number is required"}
    if not sheet.strip():
        return {"error": "sheet is required"}

    collection = get_collection(DEFAULT_DB_PATH)
    matches = _find_matching_ids_and_meta(collection, part_number, sheet)

    if not matches:
        return {
            "error": f"No component found: '{part_number}' in sheet '{sheet}'. Nothing deleted.",
        }

    ids_to_delete = [doc_id for doc_id, _ in matches]
    delete_components(collection, ids_to_delete)

    remaining = collection.count()
    return {
        "deleted_ids": ids_to_delete,
        "part_number": part_number,
        "sheet": sheet,
        "remaining_in_inventory": remaining,
        "message": (
            f"✓ Deleted {len(ids_to_delete)} entry for '{part_number}' from '{sheet}'. "
            f"Inventory now has {remaining} components."
        ),
    }


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


# ── Entry points ──────────────────────────────────────────────────────────────

def main() -> None:
    """stdio transport — Claude Desktop spawns this as a child process."""
    mcp.run()


def main_sse() -> None:
    """SSE/HTTP transport — run as a launchd-managed daemon on localhost:8765.

    Claude Desktop connects via URL instead of spawning a subprocess, so
    launchd can restart the server if it crashes without any user intervention.
    """
    port = int(os.environ.get("MCSR_SSE_PORT", "8765"))
    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = port
    logger.info("Starting Silicon Road MCP server (SSE) on 127.0.0.1:%d", port)
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
