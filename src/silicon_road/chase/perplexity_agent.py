"""
Perplexity Sonar agent for component research.

Uses the /chat/completions endpoint with model=sonar, which performs live
web search automatically. For each component we build a targeted prompt
asking for datasheet URL, technical summary, and key specs.

Returns a ChaseResult dataclass with structured findings.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SONAR_URL = "https://api.perplexity.ai/chat/completions"
SONAR_MODEL = "sonar"
MAX_RETRIES = 3
RETRY_DELAY = 3.0


@dataclass
class ChaseResult:
    """Structured findings from the Perplexity chaser for one component."""

    doc_id: str
    part_number: str
    manufacturer: str

    # Discovered content
    datasheet_url: Optional[str] = None
    technical_summary: Optional[str] = None
    key_specs: list[str] = field(default_factory=list)
    applications: list[str] = field(default_factory=list)
    raw_response: Optional[str] = None

    # Validation results (filled by validator)
    datasheet_url_valid: Optional[bool] = None
    datasheet_content_type: Optional[str] = None

    # Status
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None


def _build_prompt(part_number: str, manufacturer: str, category: str,
                  description: str, notes: str) -> str:
    """Build a targeted research prompt for this component."""
    lines = [
        f"Research the electronic component: {part_number}",
    ]
    if manufacturer:
        lines.append(f"Manufacturer: {manufacturer}")
    if category:
        lines.append(f"Category: {category}")
    if description:
        lines.append(f"Known description: {description}")
    if notes:
        lines.append(f"Notes: {notes}")

    lines += [
        "",
        "Please provide:",
        "1. DATASHEET_URL: A direct URL to the official datasheet PDF (from the manufacturer "
        "website or a reputable datasheet site like alldatasheet.com, datasheetarchive.com, "
        "or mouser.com). Must be a real, working URL.",
        "2. TECHNICAL_SUMMARY: A concise 2-3 sentence technical description of what this "
        "component does and its key characteristics.",
        "3. KEY_SPECS: List up to 5 key electrical specifications (voltage, current, frequency, "
        "gain, etc.) in the format 'Parameter: Value'.",
        "4. APPLICATIONS: List up to 4 typical applications for this component.",
        "",
        "Format your response with these exact section headers.",
        "If you cannot find reliable information about this specific part number, say so clearly.",
    ]
    return "\n".join(lines)


def _parse_response(text: str) -> dict:
    """
    Parse the Sonar response into structured fields.

    Looks for section headers in the response text and extracts content.
    Returns a dict with keys: datasheet_url, technical_summary, key_specs, applications.
    """
    import re

    result: dict = {
        "datasheet_url": None,
        "technical_summary": None,
        "key_specs": [],
        "applications": [],
    }

    # Extract DATASHEET_URL
    url_match = re.search(
        r"DATASHEET_URL[:\s]+([^\s\n]+)",
        text,
        re.IGNORECASE,
    )
    if url_match:
        url = url_match.group(1).strip().rstrip(".,")
        if url.startswith("http"):
            result["datasheet_url"] = url

    # If no explicit header, look for any PDF link
    if not result["datasheet_url"]:
        pdf_match = re.search(r"(https?://[^\s\"'<>]+\.pdf[^\s\"'<>]*)", text, re.IGNORECASE)
        if pdf_match:
            result["datasheet_url"] = pdf_match.group(1)

    # Extract TECHNICAL_SUMMARY
    summary_match = re.search(
        r"TECHNICAL_SUMMARY[:\s]+(.*?)(?=KEY_SPECS|APPLICATIONS|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if summary_match:
        summary = summary_match.group(1).strip()
        # Clean up numbered prefixes if present
        summary = re.sub(r"^\d+\.\s*", "", summary)
        result["technical_summary"] = summary[:800] if summary else None

    # Extract KEY_SPECS as list
    specs_match = re.search(
        r"KEY_SPECS[:\s]+(.*?)(?=APPLICATIONS|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if specs_match:
        specs_block = specs_match.group(1).strip()
        specs = [
            line.lstrip("•-*123456789. ").strip()
            for line in specs_block.splitlines()
            if line.strip() and not line.strip().startswith("APPLICATIONS")
        ]
        result["key_specs"] = [s for s in specs if s][:5]

    # Extract APPLICATIONS as list
    apps_match = re.search(
        r"APPLICATIONS[:\s]+(.*?)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if apps_match:
        apps_block = apps_match.group(1).strip()
        apps = [
            line.lstrip("•-*123456789. ").strip()
            for line in apps_block.splitlines()
            if line.strip()
        ]
        result["applications"] = [a for a in apps if a][:4]

    return result


def research_component(
    doc_id: str,
    part_number: str,
    manufacturer: str,
    category: str,
    description: str,
    notes: str,
    api_key: Optional[str] = None,
) -> ChaseResult:
    """
    Query Perplexity Sonar to research a component and return structured findings.

    Args:
        doc_id: The ChromaDB document ID for this component.
        part_number: Component part number.
        manufacturer: Manufacturer name (may be empty).
        category: Inventory sheet / category.
        description: Existing description text (may be empty).
        notes: Existing notes (may be empty).
        api_key: Perplexity API key. Falls back to PERPLEXITY_API_KEY env var.

    Returns:
        ChaseResult with discovered content (or error field set on failure).
    """
    key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
    if not key:
        return ChaseResult(
            doc_id=doc_id,
            part_number=part_number,
            manufacturer=manufacturer,
            error="PERPLEXITY_API_KEY not set",
        )

    prompt = _build_prompt(part_number, manufacturer, category, description, notes)

    payload = {
        "model": SONAR_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a technical electronics expert specializing in locating datasheets "
                    "and specifications for electronic components. Be precise and factual. "
                    "Always include the exact section headers requested."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1024,
        "temperature": 0.1,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    last_error: Optional[str] = None
    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(SONAR_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            raw = data["choices"][0]["message"]["content"]
            parsed = _parse_response(raw)

            return ChaseResult(
                doc_id=doc_id,
                part_number=part_number,
                manufacturer=manufacturer,
                datasheet_url=parsed["datasheet_url"],
                technical_summary=parsed["technical_summary"],
                key_specs=parsed["key_specs"],
                applications=parsed["applications"],
                raw_response=raw,
            )

        except httpx.HTTPStatusError as exc:
            last_error = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            if exc.response.status_code in (401, 403):
                break  # Auth errors won't improve with retry
            logger.warning("Attempt %d failed for %s: %s", attempt + 1, part_number, last_error)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Attempt %d failed for %s: %s", attempt + 1, part_number, last_error)

        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY * (attempt + 1))

    return ChaseResult(
        doc_id=doc_id,
        part_number=part_number,
        manufacturer=manufacturer,
        error=last_error,
    )
