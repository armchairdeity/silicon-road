"""
Phase 1 query interface — semantic search over the component inventory.

Usage:
    uv run python -m silicon_road.query "5V boost converter"
    uv run python -m silicon_road.query "SOT-23 NPN transistor" --top 10

Or after `uv pip install -e .`:
    silicon-road "5V boost converter"
"""

from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console
from rich.table import Table

from silicon_road.embed.perplexity import embed_single
from silicon_road.store.chroma import get_collection, query_inventory

console = Console()
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def search(query_text: str, n_results: int = 5, db_path=None) -> list[dict]:
    """
    Embed query_text and return the top n_results components.
    Each hit dict: {id, document, metadata, distance}
    """
    collection = get_collection(db_path)
    if collection.count() == 0:
        raise RuntimeError(
            "Collection is empty — run `silicon-road-ingest` first to load the inventory."
        )

    query_vec = embed_single(query_text)
    hits = query_inventory(collection, query_vec, n_results=n_results)
    return hits


def print_results(query_text: str, hits: list[dict]) -> None:
    console.print(f'\n[bold cyan]Query:[/] "{query_text}"')
    if not hits:
        console.print("[yellow]No results found.[/]")
        return

    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("#", style="dim", width=3)
    table.add_column("Part #", min_width=12)
    table.add_column("Mfr", min_width=10)
    table.add_column("Description", min_width=24)
    table.add_column("Package", min_width=8)
    table.add_column("Qty", width=4)
    table.add_column("Bin", min_width=8)
    table.add_column("Score", width=6, justify="right")

    for i, hit in enumerate(hits, 1):
        m = hit["metadata"]
        # Convert cosine distance to similarity score (1 = perfect, 0 = orthogonal)
        score = max(0.0, 1.0 - hit["distance"] / 2.0)
        table.add_row(
            str(i),
            m.get("part_number", ""),
            m.get("manufacturer", ""),
            m.get("description", "")[:40],
            m.get("package", ""),
            m.get("qty", ""),
            m.get("location", ""),
            f"{score:.2f}",
        )

    console.print(table)

    # Surface notes for top hit if present
    top_notes = hits[0]["metadata"].get("notes", "")
    if top_notes:
        console.print(f"\n[dim]Top hit notes:[/] {top_notes}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Silicon Road — semantic search over scavenged component inventory"
    )
    parser.add_argument("query", nargs="?", help="What are you looking for?")
    parser.add_argument(
        "--top", "-n", type=int, default=5, help="Number of results (default: 5)"
    )
    parser.add_argument("--db", type=str, default=None, help="Override ChromaDB path")

    args = parser.parse_args()

    if not args.query:
        # Interactive mode
        console.print("[bold cyan]Silicon Road[/] — component inventory search")
        console.print("Type a query, or Ctrl-C to exit.\n")
        while True:
            try:
                q = input("Search > ").strip()
                if not q:
                    continue
                hits = search(q, n_results=args.top, db_path=args.db)
                print_results(q, hits)
                console.print()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Bye.[/]")
                break
    else:
        try:
            hits = search(args.query, n_results=args.top, db_path=args.db)
            print_results(args.query, hits)
        except RuntimeError as e:
            console.print(f"[red]Error:[/] {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
