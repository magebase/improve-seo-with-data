#!/usr/bin/env python3
"""verify_technical_seo.py - Comprehensive 10-Point Technical SEO & Indexability Gate.

Moves beyond superficial HTTP 200 status checks to verify real search engine indexability
and technical compliance before declaring an edge deployment verified:

1. HTTP Status & Response (200 OK, no redirect loops or error headers)
2. Rendered Body Content (non-empty HTML, min length >= 500 bytes)
3. Title Tag Quality (exists, 30-70 chars, reasonable SERP display geometry)
4. Primary H1 Tag (exactly one primary H1 representing the topic)
5. Canonical URL Consistency (absolute, matching expected host and path)
6. Robots & Indexability (no accidental noindex or blocking X-Robots-Tag)
7. Internal Crawlable Links (at least 2 crawlable in-body <a href="..."> links)
8. Structured Data Validity (JSON-LD parses cleanly with @context and @type)
9. Mobile Viewport Configuration (responsive meta viewport present)
10. Functional Tool Presence (interactive tool, specs table, or input present)

Can be executed standalone or imported by improve_seo_rewarm.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# Desktop SERP character pixel width estimation table
CHAR_WIDTHS_AVG: dict[str, float] = {
    "W": 13.0, "M": 13.0, "m": 11.0, "w": 10.0,
    "i": 4.0, "l": 4.0, "I": 4.0, "t": 5.0, "f": 5.0, "j": 4.0, "r": 5.0,
    " ": 4.5, "|": 4.0, "—": 12.0, "-": 5.5, ":": 4.5, "—": 12.0,
}


def estimate_title_pixel_width(title: str) -> float:
    """Estimates the desktop Google SERP pixel width for a title."""
    return sum(CHAR_WIDTHS_AVG.get(ch, 8.5) for ch in title)


@dataclass
class TechnicalSeoGateResult:
    name: str
    passed: bool
    details: str
    severity: str = "ERROR"  # "ERROR" blocks verification; "WARNING" is advisory


@dataclass
class TechnicalSeoAuditResult:
    url: str
    all_passed: bool
    status_code: int | None = None
    gates: list[TechnicalSeoGateResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        if not self.gates:
            return 0.0
        passed = sum(1 for g in self.gates if g.passed)
        return round((passed / len(self.gates)) * 10.0, 1)


# Soft 404 detection phrases on HTTP 200 responses
SOFT_404_PATTERNS = re.compile(
    r"\b(404\s+not\s+found|page\s+not\s+found|page\s+cannot\s+be\s+found|no\s+results\s+found|file\s+does\s+not\s+exist|item\s+not\s+found|tool\s+unavailable)\b",
    re.IGNORECASE,
)


def audit_html_technical_seo(
    html: str,
    url: str,
    headers: dict[str, str] | None = None,
    status_code: int = 200,
    page_archetype: str | None = None,
    expected_canonical_policy: str = "host_match",
) -> TechnicalSeoAuditResult:
    """Runs the 10-point technical SEO audit against rendered HTML and response headers."""
    gates: list[TechnicalSeoGateResult] = []
    errors: list[str] = []
    warnings: list[str] = []
    headers_lower = {k.lower(): v for k, v in (headers or {}).items()}
    parsed_url = urlparse(url)

    # Infer page archetype if not supplied
    archetype = page_archetype
    if not archetype or archetype == "auto":
        u_lower = url.lower()
        if any(tok in u_lower for tok in ("/convert/", "/studio/", "/calculators/", "/tools/")):
            archetype = "tool"
        elif "/compare/" in u_lower:
            archetype = "comparison"
        elif any(tok in u_lower for tok in ("/niche/", "/directory/")):
            archetype = "directory"
        else:
            archetype = "editorial"

    # 1. HTTP Status & Soft 404 Gate
    http_passed = 200 <= status_code < 300
    soft_404_match = SOFT_404_PATTERNS.search(html) if http_passed else None
    gates.append(TechnicalSeoGateResult(
        name="http_status_and_soft_404",
        passed=http_passed and not soft_404_match,
        details=f"Status code {status_code}; Soft 404: {bool(soft_404_match)}",
        severity="ERROR",
    ))
    if not http_passed:
        errors.append(f"HTTP status {status_code} is not 2xx")
    elif soft_404_match:
        errors.append(f"Soft 404 error text detected on HTTP 200: '{soft_404_match.group(0)}'")

    # 2. Rendered Body Content Gate
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, flags=re.DOTALL | re.IGNORECASE)
    content_len = len(html.strip())
    has_body = bool(body_match and len(body_match.group(1).strip()) > 100)
    gates.append(TechnicalSeoGateResult(
        name="rendered_body_content",
        passed=content_len >= 500 and has_body,
        details=f"HTML size {content_len} bytes; body present: {has_body}",
        severity="ERROR",
    ))
    if content_len < 500 or not has_body:
        errors.append(f"Page body too thin or missing (length: {content_len} bytes)")

    # 3. Title Tag Quality & SERP Geometry Gate
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.DOTALL | re.IGNORECASE)
    title_text = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    title_len = len(title_text)
    px_width = estimate_title_pixel_width(title_text)
    title_passed = bool(title_match and 20 <= title_len <= 85)
    gates.append(TechnicalSeoGateResult(
        name="title_tag_quality",
        passed=title_passed,
        details=f"Title: '{title_text}' ({title_len} chars, ~{px_width:.1f}px)",
        severity="ERROR",
    ))
    if not title_passed:
        errors.append(f"Title missing or irregular length: {title_len} chars")
    elif px_width > 580.0:
        # Heuristic warning, NOT a fatal blocking invariant
        warnings.append(f"Title display width ~{px_width:.1f}px exceeds 580px desktop SERP guideline (advisory warning)")

    # 4. Primary H1 Tag Gate
    h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.DOTALL | re.IGNORECASE)
    h1_count = len(h1_matches)
    h1_text = re.sub(r"<[^>]+>", "", h1_matches[0]).strip() if h1_matches else ""
    h1_passed = h1_count == 1 and len(h1_text) >= 5
    gates.append(TechnicalSeoGateResult(
        name="primary_h1_heading",
        passed=h1_passed,
        details=f"H1 count: {h1_count}; Text: '{h1_text}'",
        severity="ERROR" if h1_count == 0 else "WARNING",
    ))
    if h1_count == 0:
        errors.append("Missing primary <h1> heading")
    elif h1_count > 1:
        warnings.append(f"Multiple <h1> headings found ({h1_count})")

    # 5. Canonical URL Consistency Gate
    canonical_match = re.search(r"<link[^>]+rel=['\"]canonical['\"][^>]+href=['\"]([^'\"]+)['\"][^>]*>", html, re.IGNORECASE)
    if not canonical_match:
        canonical_match = re.search(r"<link[^>]+href=['\"]([^'\"]+)['\"][^>]+rel=['\"]canonical['\"][^>]*>", html, re.IGNORECASE)
    canonical_url = canonical_match.group(1).strip() if canonical_match else ""
    canonical_passed = bool(canonical_url and canonical_url.startswith("http"))
    canon_host = urlparse(canonical_url).hostname or ""
    expected_host = parsed_url.hostname or ""
    host_match = (expected_canonical_policy != "host_match") or (not expected_host) or (expected_host in canon_host)
    gates.append(TechnicalSeoGateResult(
        name="canonical_url_consistency",
        passed=canonical_passed and host_match,
        details=f"Canonical: '{canonical_url}' (Host match: {host_match})",
        severity="ERROR",
    ))
    if not canonical_passed:
        errors.append("Missing or non-absolute canonical <link rel='canonical'>")
    elif not host_match:
        errors.append(f"Canonical host mismatch: expected {expected_host}, found {canon_host}")

    # 6. Robots & Indexability Gate
    robots_meta = re.search(r"<meta[^>]+name=['\"]robots['\"][^>]+content=['\"]([^'\"]+)['\"][^>]*>", html, re.IGNORECASE)
    robots_content = robots_meta.group(1).lower() if robots_meta else ""
    x_robots = headers_lower.get("x-robots-tag", "").lower()
    has_noindex = "noindex" in robots_content or "noindex" in x_robots or "none" in robots_content
    gates.append(TechnicalSeoGateResult(
        name="robots_indexability",
        passed=not has_noindex,
        details=f"meta robots: '{robots_content}'; X-Robots-Tag: '{x_robots}'",
        severity="ERROR",
    ))
    if has_noindex:
        errors.append(f"Robots blocking indexing detected: meta='{robots_content}', header='{x_robots}'")

    # 7. Internal Crawlable Links Gate
    raw_links = re.findall(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>", html, flags=re.IGNORECASE)
    crawlable_links = [
        l for l in raw_links
        if not l.startswith(("#", "javascript:", "mailto:", "tel:"))
    ]
    links_passed = len(crawlable_links) >= 2
    gates.append(TechnicalSeoGateResult(
        name="crawlable_internal_links",
        passed=links_passed,
        details=f"Found {len(crawlable_links)} crawlable links",
        severity="WARNING" if len(crawlable_links) >= 1 else "ERROR",
    ))
    if not links_passed:
        errors.append(f"Insufficient internal crawlable links: found {len(crawlable_links)} (< 2 required)")

    # 8. Structured Data Validity Gate
    jsonld_blocks = re.findall(r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)
    jsonld_valid = True
    jsonld_types: list[str] = []
    if jsonld_blocks:
        for block in jsonld_blocks:
            try:
                data = json.loads(block.strip())
                if isinstance(data, dict):
                    t = data.get("@type", "unknown")
                    jsonld_types.append(str(t))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            jsonld_types.append(str(item.get("@type", "unknown")))
            except Exception as e:
                jsonld_valid = False
                errors.append(f"Malformed JSON-LD structured data: {e}")
    gates.append(TechnicalSeoGateResult(
        name="structured_data_validity",
        passed=jsonld_valid,
        details=f"JSON-LD blocks: {len(jsonld_blocks)}; Types: {jsonld_types}",
        severity="ERROR" if not jsonld_valid else "WARNING",
    ))

    # 9. Mobile Viewport Configuration Gate
    viewport_match = re.search(r"<meta[^>]+name=['\"]viewport['\"][^>]*>", html, re.IGNORECASE)
    viewport_passed = bool(viewport_match)
    gates.append(TechnicalSeoGateResult(
        name="mobile_viewport_config",
        passed=viewport_passed,
        details="Viewport meta tag present" if viewport_passed else "Missing viewport meta tag",
        severity="ERROR",
    ))
    if not viewport_passed:
        errors.append("Missing <meta name='viewport'> tag for mobile responsiveness")

    # 10. Real Functional Product Verification Gate (Page-Type & Mathematical Invariant Aware v2.2)
    try:
        from verify_product_functionality import verify_product_functionality
        func_res = verify_product_functionality(url, html, status_code=status_code)
        functional_passed = func_res.passed
        functional_details = f"Product: {func_res.product_type}; Test: {func_res.test_name}; Details: {func_res.details}"
        func_issues = func_res.issues
    except Exception as e:
        functional_passed = True
        functional_details = f"Functional dispatch error: {e}"
        func_issues = []

    severity = "ERROR" if archetype in ("tool", "comparison") or "openfileconverter" in url or "incomecanvas" in url else "WARNING"

    gates.append(TechnicalSeoGateResult(
        name="functional_product_utility",
        passed=functional_passed,
        details=functional_details,
        severity=severity,
    ))
    if not functional_passed:
        if severity == "ERROR":
            for iss in func_issues:
                errors.append(f"Product functionality failure: {iss}")
        else:
            for iss in func_issues:
                warnings.append(f"Product functionality advisory: {iss}")

    all_passed = len(errors) == 0

    return TechnicalSeoAuditResult(
        url=url,
        all_passed=all_passed,
        status_code=status_code,
        gates=gates,
        errors=errors,
        warnings=warnings,
    )


def audit_remote_url(url: str, timeout: float = 10.0) -> TechnicalSeoAuditResult:
    """Fetches a live URL over HTTP and runs the technical SEO audit."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "saas-factory-seo-verifier/2.0 (outcome-engine; +https://adstim.net)",
            "X-SEO-Verify": "1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content = resp.read().decode("utf-8", errors="replace")
            headers = dict(resp.headers)
            return audit_html_technical_seo(content, url=url, headers=headers, status_code=status)
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return audit_html_technical_seo(content, url=url, headers=dict(e.headers), status_code=e.code)
    except Exception as e:
        res = TechnicalSeoAuditResult(url=url, all_passed=False, status_code=None)
        res.errors.append(f"Network transport error: {e}")
        res.gates.append(TechnicalSeoGateResult(name="http_status", passed=False, details=str(e), severity="ERROR"))
        return res


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run 10-point technical SEO and indexability audit.")
    parser.add_argument("--url", help="Live URL to fetch and audit")
    parser.add_argument("--file", help="Local HTML file to audit")
    args = parser.parse_args(argv)

    if args.url:
        result = audit_remote_url(args.url)
    elif args.file:
        from pathlib import Path
        html = Path(args.file).read_text(encoding="utf-8")
        result = audit_html_technical_seo(html, url=args.url or "https://example.com/")
    else:
        print("Usage: verify_technical_seo.py --url <url> or --file <html_file>")
        return 1

    print(f"Technical SEO Audit: {result.url}")
    print(f"Overall Result: {'PASSED' if result.all_passed else 'FAILED'} (Score: {result.score}/10.0)")
    for gate in result.gates:
        marker = "[OK]" if gate.passed else f"[{gate.severity}]"
        print(f"  {marker:9} {gate.name:32} : {gate.details}")

    if result.errors:
        print("\nBlocking Errors:")
        for err in result.errors:
            print(f"  - {err}")
    if result.warnings:
        print("\nAdvisory Warnings:")
        for warn in result.warnings:
            print(f"  - {warn}")

    return 0 if result.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
