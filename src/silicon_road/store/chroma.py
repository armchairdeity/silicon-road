"""
ChromaDB vector store operations.

Uses a persistent local collection so embeddings survive between runs.
Collection name: "silicon_road_inventory"
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import sqlite3
from pathlib import Path
from typing import Iterator, Sequence

import chromadb

logger = logging.getLogger(__name__)

COLLECTION_NAME = "silicon_road_inventory"
DEFAULT_DB_PATH = Path.home() / ".silicon_road" / "chroma"
LOCK_FILENAME = ".write.lock"


def _resolve_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path) if db_path else DEFAULT_DB_PATH


@contextlib.contextmanager
def write_lock(db_path: str | Path | None = None) -> Iterator[None]:
    """
    Cross-process exclusive lock for mutating the store.

    Claude Desktop spawns one stdio server instance per surface (desktop +
    Cowork), so several processes may share one ChromaDB. Serialize every
    write through an flock on a lockfile so concurrent upserts/deletes never
    collide on the underlying SQLite + HNSW files. POSIX-only (macOS/Linux).
    """
    path = _resolve_path(db_path)
    path.mkdir(parents=True, exist_ok=True)
    lock_path = path / LOCK_FILENAME
    with open(lock_path, "w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _ensure_wal(path: Path) -> None:
    """Best-effort: put the Chroma SQLite into WAL so readers don't block writers."""
    sqlite_file = path / "chroma.sqlite3"
    try:
        with contextlib.closing(sqlite3.connect(str(sqlite_file), timeout=30)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
    except sqlite3.Error as exc:  # pragma: no cover - best effort
        logger.debug("Could not set WAL on %s: %s", sqlite_file, exc)


def _get_client(db_path: str | Path | None = None) -> chromadb.PersistentClient:
    path = _resolve_path(db_path)
    path.mkdir(parents=True, exist_ok=True)
    # Set WAL before Chroma opens its own connection to avoid lock contention.
    _ensure_wal(path)
    logger.debug("ChromaDB path: %s", path)
    return chromadb.PersistentClient(path=str(path))


def get_collection(
    db_path: str | Path | None = None,
) -> chromadb.Collection:
    """Return (or create) the inventory collection."""
    client = _get_client(db_path)
    # get_or_create so re-running ingest is safe
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # cosine similarity for semantic search
    )
    logger.debug(
        "Collection %r has %d items", COLLECTION_NAME, collection.count()
    )
    return collection


def upsert_components(
    collection: chromadb.Collection,
    ids: Sequence[str],
    embeddings: Sequence[list[float]],
    documents: Sequence[str],
    metadatas: Sequence[dict],
    db_path: str | Path | None = None,
) -> None:
    """
    Upsert a batch of components into the collection.
    Using upsert so re-ingesting the spreadsheet after edits is idempotent.
    Serialized across processes via write_lock.
    """
    with write_lock(db_path):
        collection.upsert(
            ids=list(ids),
            embeddings=list(embeddings),
            documents=list(documents),
            metadatas=list(metadatas),
        )
    logger.debug("Upserted %d items", len(ids))


def delete_components(
    collection: chromadb.Collection,
    ids: Sequence[str],
    db_path: str | Path | None = None,
) -> None:
    """Delete components by id, serialized across processes via write_lock."""
    with write_lock(db_path):
        collection.delete(ids=list(ids))
    logger.debug("Deleted %d items", len(ids))


def query_inventory(
    collection: chromadb.Collection,
    query_embedding: list[float],
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """
    Query the collection for the n most semantically similar components.

    Returns a list of dicts with keys: id, document, metadata, distance.
    Lower distance = more similar (cosine distance in [0, 2]).
    """
    kwargs: dict = {"query_embeddings": [query_embedding], "n_results": n_results}
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    hits = []
    if results and results.get("ids"):
        ids = results["ids"][0]
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]
        for _id, doc, meta, dist in zip(ids, docs, metas, distances):
            hits.append({"id": _id, "document": doc, "metadata": meta, "distance": dist})

    return hits


def collection_count(db_path: str | Path | None = None) -> int:
    """Return the number of items currently in the collection."""
    return get_collection(db_path).count()
