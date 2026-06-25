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
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SONAR_URL = "https://api.perplexity.ai/chat/completions"
SONAR_MODEL = "sonar"
MAX_RETRIES = 3
RETRY_DELAY = 3.0

# All section headers — used as lookahead terminators in every section regex
_SECTION_HEADERS = r"(?=DATASHEET_URL|TECHNICAL_SUMMARY|KEY_SPECS|APPLICATIONS|\Z)"


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
        "Please provide exactly these four sections in this order, using these exact headers:",
        "",
        "DATASHEET_URL: <direct URL to the official datasheet PDF, or 'Not found'>",
        "",
        "TECHNICAL_SUMMARY: <2-3 sentence technical description of what this component "
        "does and its key characteristics>",
        "",
        "KEY_SPECS:",
        "- Parameter: Value",
        "(list up to 5 key electrical specifications)",
        "",
        "APPLICATIONS:",
        "- Application description",
        "(list up to 4 typical real-world applications)",
        "",
        "If you cannot find reliable information about this specific part number, "
        "say so under TECHNICAL_SUMMARY and leave other sections empty.",
    ]
    return "\n".join(lines)


def _clean_list_line(line: str) -> str:
    """Strip bullet/number prefixes from a list line."""
    return re.sub(r"^[\s•\-\*\d\.]+", "", line).strip()


def _is_section_header(line: str) -> bool:
    """Return True if a line looks like one of our section headers."""
    return bool(re.match(
        r"^(DATASHEET_URL|TECHNICAL_SUMMARY|KEY_SPECS|APPLICATIONS)\s*[:\s]",
        line.strip(),
        re.IGNORECASE,
    ))


def _is_spec_line(line: str) -> bool:
    """Heuristic: a line that looks like 'Label: Value' is probably a spec, not an app."""
    cleaned = _clean_list_line(line)
    # Specs tend to have short keys before a colon: "Vout: 5V", "Current: 1.5A"
    if ":" in cleaned:
        key, _, _ = cleaned.partition(":")
        if len(key.strip()) < 35 and key.strip():
            return True
    return False


def _parse_response(text: str) -> dict:
    """
    Parse the Sonar response into structured fields.

    Looks for section headers in the response text and extracts content.
    All section regexes use a shared lookahead (all headers + end-of-string)
    so sections can appear in any order without bleed-through.

    Returns a dict with keys: datasheet_url, technical_summary, key_specs, applications.
    """
    result: dict = {
        "datasheet_url": None,
        "technical_summary": None,
        "key_specs": [],
        "applications": [],
    }

    # ── DATASHEET_URL ─────────────────────────────────────────────────────────
    url_match = re.search(
        r"DATASHEET_URL[:\s]+([^\s\n]+)",
        text,
        re.IGNORECASE,
    )
    if url_match:
        url = url_match.group(1).strip().rstrip(".,)")
        if url.lower().startswith("http"):
            result["datasheet_url"] = url

    # Fallback: any PDF link in the text
    if not result["datasheet_url"]:
        pdf_match = re.search(r"(https?://[^\s\"'<>]+\.pdf[^\s\"'<>]*)", text, re.IGNORECASE)
        if pdf_match:
            result["datasheet_url"] = pdf_match.group(1)

    # ── TECHNICAL_SUMMARY ─────────────────────────────────────────────────────
    summary_match = re.search(
        r"TECHNICAL_SUMMARY[:\s]+(.*?)" + _SECTION_HEADERS,
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if summary_match:
        summary = re.sub(r"^\d+\.\s*", "", summary_match.group(1).strip())
        # Exclude "Not found" / "Unable to find" responses
        if summary and not re.search(r"not found|unable to find|no reliable", summary, re.IGNORECASE):
            result["technical_summary"] = summary[:800]

    # ── KEY_SPECS ─────────────────────────────────────────────────────────────
    specs_match = re.search(
        r"KEY_SPECS[:\s]+(.*?)" + _SECTION_HEADERS,
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if specs_match:
        specs = [
            _clean_list_line(line)
            for line in specs_match.group(1).splitlines()
            if line.strip() and not _is_section_header(line)
        ]
        result["key_specs"] = [s for s in specs if s][:5]

    # ── APPLICATIONS ──────────────────────────────────────────────────────────
    apps_match = re.search(
        r"APPLICATIONS[:\s]+(.*?)" + _SECTION_HEADERS,
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if apps_match:
        apps = [
            _clean_list_line(line)
            for line in apps_match.group(1).splitlines()
            if line.strip()
            and not _is_section_header(line)
            and not _is_spec_line(line)  # don't accidentally grab spec entries
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
                    "Always use the exact section headers requested, in the order given."
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
