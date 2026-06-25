"""
Perplexity embedding client.

Model: pplx-embed-v1-4b
Endpoint: https://api.perplexity.ai/v1/embeddings
Encoding: base64_int8 — 2560-dimensional int8 vectors, base64-encoded.
           The API does not support encoding_format=float.
           We decode to float32 and L2-normalize for cosine similarity.

Cost: ~$0.00000087 / call (negligible for ~128 components)
"""

from __future__ import annotations

import base64
import logging
import math
import os
import struct
import time
from typing import Sequence

import httpx

logger = logging.getLogger(__name__)

EMBED_MODEL = "pplx-embed-v1-4b"
EMBED_URL = "https://api.perplexity.ai/v1/embeddings"
EMBED_DIM = 2560   # actual dimension returned by base64_int8

BATCH_SIZE = 32
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds


def _get_api_key() -> str:
    key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "PERPLEXITY_API_KEY environment variable is not set. "
            "Export it or add it to your .env file."
        )
    return key


def _decode_int8_embedding(b64_str: str) -> list[float]:
    """
    Decode a base64_int8 embedding from the Perplexity API.

    The API returns int8 values (signed, range -128..127) base64-encoded.
    We convert to float32 and L2-normalize so ChromaDB's cosine distance
    operates correctly.
    """
    raw = base64.b64decode(b64_str)
    n = len(raw)
    int8_vals = struct.unpack(f"{n}b", raw)   # signed bytes

    # Convert to float
    floats = [float(v) for v in int8_vals]

    # L2 normalize — cosine distance on unit vectors = euclidean distance,
    # which is what ChromaDB's cosine space expects.
    norm = math.sqrt(sum(v * v for v in floats))
    if norm > 0:
        floats = [v / norm for v in floats]

    return floats


def _extract_embedding(item: dict) -> list[float]:
    """
    Extract a float vector from a single Perplexity embedding response item.
    """
    emb = item["embedding"]
    if isinstance(emb, str):
        return _decode_int8_embedding(emb)
    elif isinstance(emb, list):
        # Direct float list — normalize to be safe
        floats = [float(v) for v in emb]
        norm = math.sqrt(sum(v * v for v in floats))
        return [v / norm for v in floats] if norm > 0 else floats
    else:
        raise ValueError(f"Unexpected embedding type: {type(emb)}")


def embed_texts(texts: Sequence[str], *, api_key: str | None = None) -> list[list[float]]:
    """
    Embed a list of texts using pplx-embed-v1-4b.
    Returns a list of L2-normalized 2560-dimensional float vectors.
    """
    if not texts:
        return []

    api_key = api_key or _get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    all_embeddings: list[list[float]] = []

    with httpx.Client(timeout=60.0) as client:
        for batch_start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[batch_start : batch_start + BATCH_SIZE])
            logger.debug(
                "Embedding batch %d–%d of %d",
                batch_start + 1,
                batch_start + len(batch),
                len(texts),
            )

            payload = {
                "model": EMBED_MODEL,
                "input": batch,
                "encoding_format": "base64_int8",
            }
            last_error: Exception | None = None

            for attempt in range(MAX_RETRIES):
                try:
                    resp = client.post(EMBED_URL, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    items = sorted(data["data"], key=lambda x: x["index"])
                    batch_embeddings = [_extract_embedding(item) for item in items]
                    all_embeddings.extend(batch_embeddings)
                    last_error = None
                    break
                except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError) as exc:
                    last_error = exc
                    if attempt < MAX_RETRIES - 1:
                        wait = RETRY_DELAY * (attempt + 1)
                        logger.warning(
                            "Embed attempt %d/%d failed (%s), retrying in %.1fs",
                            attempt + 1, MAX_RETRIES, exc, wait,
                        )
                        time.sleep(wait)

            if last_error is not None:
                raise RuntimeError(
                    f"Embedding failed after {MAX_RETRIES} attempts: {last_error}"
                ) from last_error

    return all_embeddings


def embed_single(text: str, *, api_key: str | None = None) -> list[float]:
    """Convenience wrapper for a single text."""
    return embed_texts([text], api_key=api_key)[0]
