"""
Concurrency safety for the Chroma store.

Claude Desktop spawns one stdio server per surface (desktop + Cowork), so
multiple processes can share one ChromaDB. These tests assert the write path
serializes and that the SQLite store is put into WAL mode.
"""

from __future__ import annotations

import sqlite3
import threading
import time

from silicon_road.store import chroma


def test_write_lock_serializes(tmp_path):
    """A second writer must not enter the critical section until the first exits."""
    order: list[str] = []

    def worker(name: str, hold: float) -> None:
        with chroma.write_lock(tmp_path):
            order.append(f"{name}-start")
            time.sleep(hold)
            order.append(f"{name}-end")

    a = threading.Thread(target=worker, args=("A", 0.25))
    b = threading.Thread(target=worker, args=("B", 0.0))

    a.start()
    time.sleep(0.05)  # ensure A grabs the lock first
    b.start()
    a.join()
    b.join()

    # No interleaving: B starts only after A finishes.
    assert order == ["A-start", "A-end", "B-start", "B-end"]


def test_write_lock_creates_lockfile(tmp_path):
    with chroma.write_lock(tmp_path):
        pass
    assert (tmp_path / chroma.LOCK_FILENAME).exists()


def test_get_collection_enables_wal(tmp_path):
    """Opening the collection should leave the SQLite store in WAL mode."""
    chroma.get_collection(tmp_path)
    sqlite_file = tmp_path / "chroma.sqlite3"
    assert sqlite_file.exists()
    conn = sqlite3.connect(str(sqlite_file))
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"
