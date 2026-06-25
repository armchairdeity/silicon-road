"""
ChromaDB vector store operations.

Uses a persistent local collection so embeddings survive between runs.
Collection name: "silicon_road_inventory"
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import chromadb

logger = logging.getLogger(__name__)

COLLECTION_NAME = "silicon_road_inventory"
DEFAULT_DB_PATH = Path.home() / ".silicon_road" / "chroma"


def _get_client(db_path: str | Path | None = None) -> chromadb.PersistentClient:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.mkdir(parents=True, exist_ok=True)
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
) -> None:
    """
    Upsert a batch of components into the collection.
    Using upsert so re-ingesting the spreadsheet after edits is idempotent.
    """
    collection.upsert(
        ids=list(ids),
        embeddings=list(embeddings),
        documents=list(documents),
        metadatas=list(metadatas),
    )
    logger.debug("Upserted %d items", len(ids))


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
