"""
mcsr-curate — interactive curation of chase_results.json

Walk through each sidecar entry one at a time. For each component you see
a plain-English summary — part number, datasheet URL status, key specs, and
a brief description — then press a single key to decide:

    A  Accept — include in ChromaDB write-back
    R  Reject — exclude (bad data, wrong part, unresolvable)
    E  Edit URL — enter a correct datasheet URL, then accept
    S  Skip — leave undecided for later
    Q  Quit — save progress and exit

Decisions are written back to the sidecar immediately (crash-safe).
Run mcsr-writeback afterward to push accepted entries into ChromaDB.

Usage:
    mcsr-curate                  # curate uncurated entries
    mcsr-curate --all            # re-curate everything
    mcsr-curate --accepted       # list accepted entries (review, no interaction)
"""

from __future__ import annotations

import argparse
import json
import sys
import termios
import time
import tty
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

SIDECAR_PATH = Path.home() / ".silicon_road" / "chase_results.json"


# ---------------------------------------------------------------------------
# Sidecar I/O
# ---------------------------------------------------------------------------

def _load_sidecar() -> dict[str, Any]:
    if SIDECAR_PATH.exists():
        try:
            return json.loads(SIDECAR_PATH.read_text())
        except Exception as exc:
            console.print(f"[red]ERROR: Could not parse sidecar: {exc}[/red]")
            sys.exit(1)
    return {}


def _save_sidecar(data: dict[str, Any]) -> None:
    tmp = SIDECAR_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(SIDECAR_PATH)


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def _getch() -> str:
    """Read a single keypress without requiring Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _clean_specs(specs: list[str]) -> list[str]:
    """Filter out garbage lines that got mixed into key_specs during parsing."""
    junk = {"key_specs:", "applications:", "technical_summary:"}
    return [
        s for s in specs
        if s and s.strip().lower() not in junk and len(s) < 150
    ][:6]


def _render_entry(entry: dict, index: int, total: int) -> Panel:
    part = entry.get("part_number") or "Unknown"
    manufacturer = entry.get("manufacturer") or "Unknown"
    doc_id = entry.get("doc_id") or ""
    url = entry.get("datasheet_url")
    url_valid = entry.get("datasheet_url_valid")
    summary = (entry.get("technical_summary") or "").strip()
    key_specs = _clean_specs(entry.get("key_specs") or [])
    raw = entry.get("raw_response") or ""
    current_decision = entry.get("curated")

    t = Text()

    # Header info
    t.append(" Part #:       ", style="dim")
    t.append(f"{part}\n", style="bold white")
    t.append(" Manufacturer: ", style="dim")
    t.append(f"{manufacturer}\n", style="white")
    t.append(" Doc ID:       ", style="dim")
    t.append(f"{doc_id}\n\n", style="dim")

    # Datasheet URL
    if url:
        if url_valid is True:
            badge = "[green]✓ REACHABLE PDF[/green]"
        elif url_valid is False:
            badge = "[red]✗ BROKEN URL[/red]"
        else:
            badge = "[yellow]? NOT VALIDATED[/yellow]"
        t.append(" Datasheet:   ", style="dim")
        t.append(f"{url}\n")
        t.append(f"               {badge}\n\n")
    else:
        t.append(" Datasheet:   ", style="dim")
        t.append("NONE FOUND\n\n", style="red bold")

    # Resolved-match warning
    if raw and "cannot find reliable information" in raw.lower() and url:
        t.append(" ⚠  APPROXIMATE MATCH — ", style="yellow bold")
        t.append("chaser resolved to a functional equivalent, not an exact part match.\n\n",
                 style="yellow")

    # Summary
    if summary:
        short = summary[:220] + ("…" if len(summary) > 220 else "")
        t.append(" Summary:\n", style="dim")
        t.append(f"   {short}\n\n")

    # Key specs
    if key_specs:
        t.append(" Key specs:\n", style="dim")
        for spec in key_specs:
            t.append(f"   • {spec}\n")
        t.append("\n")

    # Explain why no datasheet was found
    if not url and raw:
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()][:4]
        t.append(" Chaser notes:\n", style="dim")
        for ln in lines:
            truncated = ln[:110] + ("…" if len(ln) > 110 else "")
            t.append(f"   {truncated}\n", style="dim italic")
        t.append("\n")

    # Current decision badge
    if current_decision:
        color = "green" if current_decision == "accepted" else "red" if current_decision == "rejected" else "dim"
        t.append(f" Current decision: ", style="dim")
        t.append(f"{current_decision.upper()}\n", style=f"bold {color}")

    return Panel(
        t,
        title=f"[bold cyan]Component {index} of {total}[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _print_summary(sidecar: dict, s_accepted: int, s_rejected: int, s_skipped: int) -> None:
    total_accepted = sum(1 for v in sidecar.values() if v.get("curated") == "accepted")
    total_rejected = sum(1 for v in sidecar.values() if v.get("curated") == "rejected")
    total_pending  = sum(1 for v in sidecar.values() if v.get("curated") is None)

    console.print(f"  This session:  [green]+{s_accepted} accepted[/green]  "
                  f"[red]+{s_rejected} rejected[/red]  {s_skipped} skipped")
    console.print(f"  Sidecar total: [green]{total_accepted} accepted[/green]  "
                  f"[red]{total_rejected} rejected[/red]  [dim]{total_pending} pending[/dim]\n")
    if total_accepted:
        console.print("  [dim]When ready, run [bold]mcsr-writeback[/bold] to push accepted "
                      "entries into ChromaDB.[/dim]\n")


# ---------------------------------------------------------------------------
# Main curation loop
# ---------------------------------------------------------------------------

def run_curate(curate_all: bool = False, show_accepted: bool = False) -> None:
    sidecar = _load_sidecar()

    if not sidecar:
        console.print("[yellow]Sidecar is empty. Run mcsr-chase first.[/yellow]")
        return

    # Review mode — just list accepted entries
    if show_accepted:
        accepted = [(k, v) for k, v in sidecar.items() if v.get("curated") == "accepted"]
        if not accepted:
            console.print("[yellow]No accepted entries yet.[/yellow]")
            return
        console.print(f"\n[green bold]Accepted entries ({len(accepted)}):[/green bold]\n")
        for _doc_id, entry in accepted:
            url = entry.get("datasheet_url") or "[dim]no URL[/dim]"
            console.print(f"  ✓  [bold]{entry.get('part_number')}[/bold]  —  {url}")
        console.print()
        return

    # Select entries to present
    if curate_all:
        entries = list(sidecar.items())
    else:
        entries = [(k, v) for k, v in sidecar.items() if v.get("curated") is None]

    if not entries:
        accepted = sum(1 for v in sidecar.values() if v.get("curated") == "accepted")
        rejected = sum(1 for v in sidecar.values() if v.get("curated") == "rejected")
        console.print(f"\n[green]All entries already curated.[/green]  "
                      f"Accepted: {accepted}  Rejected: {rejected}")
        console.print("Use [bold]--all[/bold] to re-curate.\n")
        return

    console.print(f"\n[bold]Curating {len(entries)} entr{'y' if len(entries)==1 else 'ies'}[/bold]  "
                  f"[dim]— A=Accept  R=Reject  E=Edit URL  S=Skip  Q=Quit[/dim]\n")
    time.sleep(0.8)

    s_accepted = s_rejected = s_skipped = 0

    for i, (doc_id, entry) in enumerate(entries, 1):
        console.clear()
        console.print(_render_entry(entry, i, len(entries)))
        console.print(
            "\n  [bold green][A][/bold green] Accept    "
            "[bold red][R][/bold red] Reject    "
            "[bold yellow][E][/bold yellow] Edit URL    "
            "[bold dim][S][/bold dim] Skip    "
            "[bold dim][Q][/bold dim] Quit\n"
        )
        console.print("  Your choice: ", end="")

        while True:
            ch = _getch().lower()

            if ch == "a":
                entry["curated"] = "accepted"
                sidecar[doc_id] = entry
                _save_sidecar(sidecar)
                s_accepted += 1
                console.print("[green]ACCEPTED ✓[/green]")
                break

            elif ch == "r":
                entry["curated"] = "rejected"
                sidecar[doc_id] = entry
                _save_sidecar(sidecar)
                s_rejected += 1
                console.print("[red]REJECTED ✗[/red]")
                break

            elif ch == "e":
                console.print()
                new_url = console.input("  [bold yellow]New datasheet URL:[/bold yellow] ").strip()
                if new_url:
                    entry["datasheet_url"] = new_url
                    entry["datasheet_url_valid"] = None   # will need re-validation
                    entry["curated"] = "accepted"
                    sidecar[doc_id] = entry
                    _save_sidecar(sidecar)
                    s_accepted += 1
                    console.print("[green]URL UPDATED & ACCEPTED ✓[/green]")
                else:
                    s_skipped += 1
                    console.print("[dim]No URL entered — skipped[/dim]")
                break

            elif ch == "s":
                s_skipped += 1
                console.print("[dim]SKIPPED[/dim]")
                break

            elif ch in ("q", "\x03", "\x04"):   # q, Ctrl-C, Ctrl-D
                console.print("\n\n[bold]Quitting.[/bold]\n")
                _print_summary(sidecar, s_accepted, s_rejected, s_skipped)
                return

            # Ignore anything else

        time.sleep(0.25)

    console.clear()
    console.print("\n[bold green]✓ Curation session complete.[/bold green]\n")
    _print_summary(sidecar, s_accepted, s_rejected, s_skipped)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="mcsr-curate — interactive curation of chase results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--all", action="store_true", dest="curate_all",
        help="Re-curate all entries, including already-decided ones",
    )
    parser.add_argument(
        "--accepted", action="store_true",
        help="List accepted entries only (review mode, no interaction)",
    )
    args = parser.parse_args()
    run_curate(curate_all=args.curate_all, show_accepted=args.accepted)


if __name__ == "__main__":
    main()
