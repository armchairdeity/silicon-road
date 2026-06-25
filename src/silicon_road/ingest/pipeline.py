"""
Phase 1 ingest pipeline.

Usage:
    uv run python -m silicon_road.ingest.pipeline --xlsx ~/Documents/Claude/documents/component_inventory.xlsx

Or via script entry point:
    silicon-road-ingest --xlsx <path>

Steps:
  1. Load spreadsheet → list[Component]
  2. Build text representations
  3. Call Perplexity embed API in batches
  4. Upsert into ChromaDB
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from silicon_road.embed.perplexity import embed_texts
from silicon_road.ingest.spreadsheet import load_inventory
from silicon_road.store.chroma import get_collection, upsert_components

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_XLSX = (
    Path.home() / "Documents" / "Claude" / "documents" / "component_inventory.xlsx"
)


def run_ingest(xlsx_path: Path, db_path: Path | None = None, dry_run: bool = False) -> None:
    console.rule("[bold cyan]Silicon Road — Ingest Pipeline[/]")

    # ── Step 1: Load spreadsheet ──────────────────────────────────────────────
    console.print(f"[bold]Loading:[/] {xlsx_path}")
    t0 = time.perf_counter()
    components = load_inventory(xlsx_path)
    console.print(f"  → {len(components)} components in {time.perf_counter() - t0:.1f}s")

    if not components:
        console.print("[red]No components found — check the spreadsheet path and format.[/]")
        sys.exit(1)

    # ── Step 2: Build text representations ───────────────────────────────────
    console.print("[bold]Building text representations…[/]")
    texts = [c.to_text() for c in components]
    ids = [c.doc_id for c in components]
    metadatas = [c.to_metadata() for c in components]

    if dry_run:
        console.print("[yellow]Dry run — showing first 3 text representations:[/]")
        for i, (comp, text) in enumerate(zip(components[:3], texts[:3])):
            console.print(f"\n[dim]ID:[/] {comp.doc_id}")
            console.print(f"[dim]Text:[/] {text}")
        console.print(f"\n[yellow]Would embed {len(texts)} components. Exiting (dry run).[/]")
        return

    # ── Step 3: Embed ─────────────────────────────────────────────────────────
    console.print(f"[bold]Embedding {len(texts)} components via Perplexity pplx-embed-v1-4b…[/]")
    t1 = time.perf_counter()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Embedding…", total=len(texts))
        BATCH = 32
        all_embeddings: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            batch_embeddings = embed_texts(batch)
            all_embeddings.extend(batch_embeddings)
            progress.advance(task, len(batch))

    elapsed = time.perf_counter() - t1
    console.print(f"  → {len(all_embeddings)} embeddings in {elapsed:.1f}s")

    # ── Step 4: Upsert into ChromaDB ─────────────────────────────────────────
    console.print("[bold]Upserting into ChromaDB…[/]")
    t2 = time.perf_counter()
    collection = get_collection(db_path)
    upsert_components(
        collection=collection,
        ids=ids,
        embeddings=all_embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    console.print(
        f"  → Done in {time.perf_counter() - t2:.1f}s. "
        f"Collection now has [bold]{collection.count()}[/] items."
    )

    console.rule("[bold green]Ingest complete ✓[/]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Silicon Road — ingest component inventory into ChromaDB"
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX,
        help=f"Path to component_inventory.xlsx (default: {DEFAULT_XLSX})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Override ChromaDB storage path (default: ~/.silicon_road/chroma)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and show text representations without calling the API",
    )
    args = parser.parse_args()
    run_ingest(xlsx_path=args.xlsx, db_path=args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
