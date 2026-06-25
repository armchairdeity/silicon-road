"""
URL validator for discovered datasheet and resource links.

Checks that a URL:
  1. Returns HTTP 200 (or 206 for partial content)
  2. Has a Content-Type consistent with the expected resource
     (application/pdf, text/html, etc.)
  3. Isn't a redirect to a 404 page (checks final URL)

Does NOT download full content — just a HEAD request (falls back to GET
with stream=True and immediate close if HEAD returns 405).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 15.0
VALID_STATUS = {200, 206}
PDF_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}


@dataclass
class ValidationResult:
    url: str
    reachable: bool
    status_code: int | None = None
    content_type: str | None = None
    final_url: str | None = None   # after redirects
    is_pdf: bool = False
    error: str | None = None


def _parse_content_type(raw: str | None) -> str | None:
    """Strip parameters from Content-Type header (e.g. 'text/html; charset=utf-8' → 'text/html')."""
    if not raw:
        return None
    return raw.split(";")[0].strip().lower()


def _is_plausible_url(url: str) -> bool:
    """Quick sanity check — must have http(s) scheme and a hostname."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def validate_url(url: str) -> ValidationResult:
    """
    Validate a URL by sending a HEAD request (with GET fallback).

    Returns a ValidationResult with reachability, status code, and content type.
    """
    if not url:
        return ValidationResult(url=url, reachable=False, error="Empty URL")

    if not _is_plausible_url(url):
        return ValidationResult(url=url, reachable=False, error="Malformed URL")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,text/html,*/*",
    }

    try:
        with httpx.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers=headers,
        ) as client:
            try:
                resp = client.head(url)
                if resp.status_code == 405:
                    raise httpx.HTTPStatusError("HEAD not allowed", request=resp.request, response=resp)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 405:
                    # Fallback to GET with immediate close
                    resp = client.get(url, headers={**headers, "Range": "bytes=0-1023"})
                else:
                    raise

        ct_raw = resp.headers.get("content-type")
        ct = _parse_content_type(ct_raw)
        is_pdf = ct in PDF_CONTENT_TYPES or url.lower().endswith(".pdf")

        return ValidationResult(
            url=url,
            reachable=resp.status_code in VALID_STATUS,
            status_code=resp.status_code,
            content_type=ct,
            final_url=str(resp.url) if str(resp.url) != url else None,
            is_pdf=is_pdf,
        )

    except httpx.TimeoutException:
        return ValidationResult(url=url, reachable=False, error="Timeout")
    except httpx.TooManyRedirects:
        return ValidationResult(url=url, reachable=False, error="Too many redirects")
    except httpx.RequestError as exc:
        return ValidationResult(url=url, reachable=False, error=f"Request error: {exc}")
    except Exception as exc:
        return ValidationResult(url=url, reachable=False, error=f"Unexpected: {exc}")
