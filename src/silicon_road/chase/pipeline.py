"""
Phase 3 chaser pipeline — mcsr-chase

Iterates components with sparse data (missing datasheet URL, thin description,
thin notes), queries Perplexity Sonar for enrichment, validates any discovered
URLs, and writes a JSON sidecar at ~/.silicon_road/chase_results.json.

Results are for human curation — nothing is written back to ChromaDB here.

Usage:
    mcsr-chase                       # chase all sparse components
    mcsr-chase --limit 10            # process at most 10 components
    mcsr-chase --sheet ICs           # restrict to one inventory sheet
    mcsr-chase --force               # re-chase even if result already exists
    mcsr-chase --dry-run             # show what would be chased, no API calls
    mcsr-chase --validate-only       # only validate URLs in existing sidecar
    mcsr-chase --xlsx /path/to.xlsx  # override inventory file path
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from silicon_road.ingest.spreadsheet import load_inventory
from silicon_road.chase.perplexity_agent import ChaseResult, research_component
from silicon_road.chase.validator import validate_url

logger = logging.getLogger(__name__)
console = Console()

DEFAULT_XLSX = (
    Path.home() / "Documents" / "Claude" / "documents" / "component_inventory.xlsx"
)
SIDECAR_PATH = Path.home() / ".silicon_road" / "chase_results.json"

# Thresholds for deciding a component is "sparse"
MIN_DESCRIPTION_LEN = 20
MIN_NOTES_LEN = 10


def _is_sparse(comp) -> tuple[bool, str]:
    """
    Determine if a component needs chasing.

    Returns (needs_chase, reason).
    """
    reasons = []
    if not comp.datasheet_url:
        reasons.append("no datasheet")
    if len(comp.description or "") < MIN_DESCRIPTION_LEN:
        reasons.append("thin description")
    if len(comp.notes or "") < MIN_NOTES_LEN:
        reasons.append("thin notes")

    if reasons:
        return True, ", ".join(reasons)
    return False, ""


def _load_sidecar() -> dict[str, Any]:
    """Load existing chase results from the JSON sidecar, or return empty dict."""
    if SIDECAR_PATH.exists():
        try:
            return json.loads(SIDECAR_PATH.read_text())
        except Exception as exc:
            logger.warning("Could not parse sidecar: %s", exc)
    return {}


def _save_sidecar(data: dict[str, Any]) -> None:
    """Write the chase results sidecar to disk (atomic via temp file)."""
    SIDECAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SIDECAR_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(SIDECAR_PATH)


def _result_to_dict(result: ChaseResult, validate_result=None) -> dict:
    """Serialize a ChaseResult (and optional ValidationResult) for the sidecar."""
    d = asdict(result)
    if validate_result is not None:
        from dataclasses import asdict as _asdict
        d["url_validation"] = _asdict(validate_result)
    return d


def run_chase(
    xlsx_path: Path | None = None,
    limit: int | None = None,
    sheet_filter: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    validate_only: bool = False,
    rate_limit_delay: float = 1.5,
) -> None:
    """
    Main chase logic.

    Args:
        xlsx_path: Path to component_inventory.xlsx. Defaults to DEFAULT_XLSX.
        limit: Max number of components to process.
        sheet_filter: If set, only process components from this sheet name.
        force: Re-chase components that already have a sidecar entry.
        dry_run: Print what would be chased but make no API calls.
        validate_only: Only run URL validation on existing sidecar entries.
        rate_limit_delay: Seconds to wait between Perplexity API calls.
    """
    sidecar = _load_sidecar()

    if validate_only:
        _run_validate_only(sidecar)
        return

    xlsx_path = xlsx_path or DEFAULT_XLSX

    # Load all components from inventory
    components = load_inventory(xlsx_path)
    console.print(f"[dim]Loaded {len(components)} components from {xlsx_path.name}[/dim]")

    # Filter and select candidates
    candidates = []
    for comp in components:
        if sheet_filter and comp.sheet.lower() != sheet_filter.lower():
            continue
        sparse, reason = _is_sparse(comp)
        if not sparse:
            continue
        if not force and comp.doc_id in sidecar:
            continue
        candidates.append((comp, reason))

    if not candidates:
        console.print("[green]✓ No sparse components to chase.[/green]")
        return

    if limit:
        candidates = candidates[:limit]

    console.print(
        f"\n[bold]Chasing {len(candidates)} sparse components"
        f"{f' (limit {limit})' if limit else ''}[/bold]"
    )

    if dry_run:
        table = Table("Doc ID", "Part #", "Sheet", "Why sparse")
        for comp, reason in candidates:
            table.add_row(comp.doc_id, comp.part_number, comp.sheet, reason)
        console.print(table)
        console.print(f"\n[yellow]Dry run — {len(candidates)} would be chased[/yellow]")
        return

    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        console.print("[red]ERROR: PERPLEXITY_API_KEY not set[/red]")
        return

    success = skipped = failed = 0

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Chasing...", total=len(candidates))

        for comp, reason in candidates:
            progress.update(task, description=f"[cyan]{comp.part_number}[/cyan] ({reason})")

            result = research_component(
                doc_id=comp.doc_id,
                part_number=comp.part_number,
                manufacturer=comp.manufacturer or "",
                category=comp.sheet,
                description=comp.description or "",
                notes=comp.notes or "",
                api_key=api_key,
            )

            # Validate the discovered URL if we got one
            validate_result = None
            if result.datasheet_url:
                validate_result = validate_url(result.datasheet_url)
                result.datasheet_url_valid = validate_result.reachable
                result.datasheet_content_type = validate_result.content_type

            # Store in sidecar
            sidecar[comp.doc_id] = _result_to_dict(result, validate_result)
            _save_sidecar(sidecar)

            if result.error:
                failed += 1
                logger.warning("Chase failed for %s: %s", comp.part_number, result.error)
            else:
                success += 1

            progress.advance(task)

            # Rate limiting
            if rate_limit_delay > 0:
                time.sleep(rate_limit_delay)

    # Summary
    console.print(f"\n[green]✓ Done.[/green] Success: {success}  Failed: {failed}")
    console.print(f"Sidecar: [dim]{SIDECAR_PATH}[/dim]")

    # Quick stats on URL validity
    valid_urls = sum(
        1 for v in sidecar.values()
        if v.get("datasheet_url") and v.get("datasheet_url_valid")
    )
    total_with_url = sum(1 for v in sidecar.values() if v.get("datasheet_url"))
    if total_with_url:
        console.print(
            f"URLs validated: {valid_urls}/{total_with_url} reachable "
            f"({100 * valid_urls // total_with_url}%)"
        )


def _run_validate_only(sidecar: dict) -> None:
    """Re-validate all URLs in an existing sidecar."""
    entries_with_url = [(doc_id, v) for doc_id, v in sidecar.items() if v.get("datasheet_url")]
    if not entries_with_url:
        console.print("[yellow]No URLs in sidecar to validate.[/yellow]")
        return

    console.print(f"[bold]Validating {len(entries_with_url)} URLs...[/bold]")
    valid = invalid = 0

    for doc_id, entry in entries_with_url:
        url = entry["datasheet_url"]
        result = validate_url(url)
        entry["url_validation"] = {
            "url": result.url,
            "reachable": result.reachable,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "is_pdf": result.is_pdf,
            "error": result.error,
        }
        entry["datasheet_url_valid"] = result.reachable
        entry["datasheet_content_type"] = result.content_type

        if result.reachable:
            valid += 1
            status = f"[green]✓[/green] {result.status_code}"
        else:
            invalid += 1
            status = f"[red]✗[/red] {result.error or result.status_code}"

        console.print(f"  {doc_id}: {url[:60]}… {status}")

    _save_sidecar(sidecar)
    console.print(f"\n[green]Valid:[/green] {valid}  [red]Invalid:[/red] {invalid}")
    console.print(f"Updated sidecar: [dim]{SIDECAR_PATH}[/dim]")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="mcsr-chase — Perplexity-powered component data enrichment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=None,
        help=f"Path to component_inventory.xlsx (default: {DEFAULT_XLSX})",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None,
        help="Max number of components to process (default: all)",
    )
    parser.add_argument(
        "--sheet", "-s", default=None,
        help="Restrict to a single inventory sheet (e.g. ICs, Transistors)",
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Re-chase components that already have a sidecar entry",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be chased but make no API calls",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Only validate URLs in the existing sidecar (no new research)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.5,
        help="Seconds between API calls to avoid rate limits (default: 1.5)",
    )

    args = parser.parse_args()

    run_chase(
        xlsx_path=args.xlsx,
        limit=args.limit,
        sheet_filter=args.sheet,
        force=args.force,
        dry_run=args.dry_run,
        validate_only=args.validate_only,
        rate_limit_delay=args.delay,
    )


if __name__ == "__main__":
    main()
