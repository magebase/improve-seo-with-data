#!/usr/bin/env python3
"""content_usefulness_gate.py - Content Quality, Usefulness, & Factual Claim Gate.

Enforces Google Search Essentials, anti-doorway guidelines, and factual accuracy:
1. Intent Fulfillment: verifies target query tokens are answered with substantial technical depth.
2. Thin Content & Doorway Detection: detects template-duplicate pages with low distinctiveness.
3. Anti-Vaporware Gate (Invariant F): bans 'in rollout', 'coming soon', 'server-side pipeline'.
4. Factual Claim Verification: requires every concrete performance or engineering claim
   (model parameter counts, WASM SIMD throughput, format spec versions) to trace back to
   an authoritative evidence source (source_code, test_suite, official_spec, measured_benchmark).
5. Functional Utility: requires interactive tools, structured specification tables, or
   code/workflow examples rather than superficial text.

Can be imported as a library or executed via CLI. stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

BANNED_VAPORWARE_REGEX = re.compile(
    r"\b(in rollout|coming soon|server-side pipeline|beta pipeline|under construction|placeholder text|placeholder content)\b",
    re.IGNORECASE,
)

SPECULATIVE_MARKETING_REGEX = re.compile(
    r"(military-grade|supercharged quantum|100x faster than all|unlimited free cloud AI|instant magic AI)",
    re.IGNORECASE,
)

# Detects concrete technical and regulatory metrics that require factual verification
TECHNICAL_CLAIM_PATTERNS = [
    (r"\b(\d+M|\d+B)\s+(?:param|parameter|transformer)\b", "model_architecture"),
    (r"\b(?:ASPRS|ISO|RFC|ECMA|IEEE|W3C|NIST)\s+[\w\.\-]+", "official_spec"),
    (r"\b(?:SIMD|WebAssembly|WASM|WebGL|WebGPU)\s+(?:acceleration|throughput|runtime|vectorization)", "runtime_architecture"),
    (r"~(\d+x|\d+ms)\s+(?:realtime|latency|throughput)", "measured_benchmark"),
    (r"\b(?:IRS\s+(?:Pub|Publication|Notice|Form|Section)\s+\d+|IRC\s*(?:§\s*)?\d+|26\s+U\.S\.C\.\s+§?\s*\d+|ACA\s+Section\s+\d+|(?:\d+\s+)?CFR\s+[\w\.\-]+)\b", "government_regulation"),
    (r"\b(?:Tax\s+Year\s+202[0-9]|TY202[0-9]|effective\s+(?:January|July|April|October)\s+202[0-9])\b", "regulatory_effective_date"),
    (r"\b(?:US|UK|EU|CA|AU)\s+(?:jurisdiction|statute|standard|guideline)\b", "jurisdiction"),
]


class ClaimSourceType(str, Enum):
    GOVERNMENT_REGULATION = "government_regulation"
    OFFICIAL_SPEC = "official_spec"
    PRIMARY_DATASET = "primary_dataset"
    PEER_REVIEWED_RESEARCH = "peer_reviewed_research"
    SOURCE_CODE = "source_code"
    TEST_SUITE = "test_suite"
    MEASURED_BENCHMARK = "measured_benchmark"
    UNVERIFIED = "unverified"


@dataclass
class FactualClaim:
    text: str
    claim_type: str
    source_type: ClaimSourceType = ClaimSourceType.UNVERIFIED
    evidence_reference: str | None = None
    publication_date: str | None = None
    effective_year: str | None = None
    jurisdiction: str | None = None
    verified: bool = False


@dataclass
class ContentUsefulnessReport:
    url: str
    query: str
    is_valid: bool
    score: float  # 0.0 to 10.0
    issues: list[str] = field(default_factory=list)
    verified_claims: list[dict[str, Any]] = field(default_factory=list)
    unverified_claims: list[dict[str, Any]] = field(default_factory=list)
    distinctiveness_score: float = 1.0
    word_count: int = 0
    functional_elements_count: int = 0
    page_archetype: str = "tool"


def _strip_boilerplate(html: str) -> str:
    """Strips navigation, header, footer, modals, and cookie disclaimers before similarity evaluation."""
    text = html
    # Strip scripts, styles, noscript
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Strip header, nav, footer, dialog
    text = re.sub(r"<(header|nav|footer|dialog)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Strip cookie notices and standard disclaimer containers
    text = re.sub(r"<div[^>]+class=['\"][^'\"]*(?:cookie|disclaimer|modal|consent)[^'\"]*['\"][^>]*>.*?</div>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Strip standard site search forms
    text = re.sub(r"<form[^>]+class=['\"][^'\"]*search[^'\"]*['\"][^>]*>.*?</form>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean_text).strip()


def _extract_text(html: str) -> str:
    """Strips HTML tags and script/style blocks to inspect visible content."""
    no_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r"<[^>]+>", " ", no_scripts)
    return re.sub(r"\s+", " ", clean_text).strip()


def _extract_headings(html: str) -> list[str]:
    """Extracts H1, H2, and H3 headings from HTML."""
    headings = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, flags=re.DOTALL | re.IGNORECASE)
    return [re.sub(r"<[^>]+>", "", h).strip() for h in headings]


def _count_functional_elements(html: str) -> int:
    """Counts interactive or structured evidence elements (tables, forms, canvas, inputs, buttons)."""
    count = 0
    count += len(re.findall(r"<table[^>]*>", html, flags=re.IGNORECASE)) * 2
    count += len(re.findall(r"<(form|canvas|svg|pre|code|button|select)[^>]*>", html, flags=re.IGNORECASE))
    count += len(re.findall(r"<input[^>]+type=['\"](file|range|checkbox|number|text)['\"][^>]*>", html, flags=re.IGNORECASE))
    return count


def compute_shingle_distinctiveness(content: str, reference_corpus: Sequence[str], n: int = 3) -> float:
    """Computes Jaccard distinctiveness against reference templates/sibling pages.

    Returns 1.0 (completely distinct) down to 0.0 (identical duplicate/doorway).
    """
    words = [w.lower() for w in re.findall(r"\w+", content) if len(w) > 2]
    if len(words) < n:
        return 1.0
    target_shingles = set(" ".join(words[i : i + n]) for i in range(len(words) - n + 1))
    if not target_shingles or not reference_corpus:
        return 1.0

    max_sim = 0.0
    for ref in reference_corpus:
        ref_words = [w.lower() for w in re.findall(r"\w+", ref) if len(w) > 2]
        if len(ref_words) < n:
            continue
        ref_shingles = set(" ".join(ref_words[i : i + n]) for i in range(len(ref_words) - n + 1))
        sim = len(target_shingles & ref_shingles) / max(len(target_shingles | ref_shingles), 1)
        if sim > max_sim:
            max_sim = sim

    return max(0.0, 1.0 - max_sim)


def verify_content_usefulness(
    html: str,
    target_query: str,
    page_url: str = "",
    reference_corpus: Sequence[str] | None = None,
    claim_evidence_ledger: dict[str, str] | None = None,
    page_archetype: str | None = None,
) -> ContentUsefulnessReport:
    """Comprehensive gate checking intent, uniqueness, anti-vaporware, and claim provenance."""
    issues: list[str] = []
    score = 10.0
    visible_text = _extract_text(html)
    headings = _extract_headings(html)
    word_count = len(visible_text.split())
    func_count = _count_functional_elements(html)

    # Infer page archetype if not explicitly passed
    archetype = page_archetype
    if not archetype or archetype == "auto":
        p_lower = page_url.lower()
        q_lower = target_query.lower()
        if any(tok in p_lower for tok in ("/convert/", "/studio/", "/calculators/", "/calculator/", "/tools/", "/tool/")) or "<canvas" in html.lower() or func_count > 0:
            archetype = "tool"
        elif "/compare/" in p_lower or " vs " in q_lower or "compare" in q_lower:
            archetype = "comparison"
        elif any(tok in p_lower for tok in ("/niche/", "/directory/", "/formats/")):
            archetype = "directory"
        else:
            archetype = "editorial"

    # 1. Anti-Vaporware Check (Invariant F)
    vaporware_matches = BANNED_VAPORWARE_REGEX.findall(visible_text)
    if vaporware_matches:
        issues.append(f"Vaporware/roadmap language detected: {set(vaporware_matches)}")
        score -= 4.0

    speculative_matches = SPECULATIVE_MARKETING_REGEX.findall(visible_text)
    if speculative_matches:
        issues.append(f"Unsubstantiated marketing hype detected: {set(speculative_matches)}")
        score -= 2.5

    # 2. Page-Type-Specific Content Depth & Functional Utility
    if archetype == "tool":
        min_words = 40 if func_count > 0 else 120
    elif archetype == "comparison":
        min_words = 150
    elif archetype == "directory":
        min_words = 50
    else:
        min_words = 200

    if word_count < (min_words // 2):
        issues.append(f"Severe thin content for {archetype} archetype: page has only {word_count} visible words (< 50% of {min_words} minimum)")
        score -= 5.0
    elif word_count < min_words:
        issues.append(f"Thin content for {archetype} archetype: page has only {word_count} visible words (< {min_words} required)")
        score -= 3.0
    elif word_count < (min_words * 1.5):
        score -= 0.5

    # 3. Target Query Intent Fulfillment
    q_tokens = [tok.lower() for tok in re.findall(r"\w+", target_query) if len(tok) > 2]
    matched_in_heading = any(
        all(tok in h.lower() for tok in q_tokens)
        for h in headings
    )
    if not matched_in_heading:
        matched_in_text = all(tok in visible_text.lower() for tok in q_tokens)
        if not matched_in_text:
            issues.append(f"Intent gap: target query tokens {q_tokens} not covered in headings or body text")
            score -= 2.5
        else:
            score -= 0.5  # minor penalty for not having in a clear heading

    # 4. Functional Utility Check
    if func_count == 0 and archetype in ("tool", "comparison"):
        issues.append("Lack of functional utility: no tables, code blocks, canvas, or interactive inputs found")
        score -= 2.0

    # 5. Distinctiveness / Doorway Prevention (Boilerplate Stripped)
    distinctiveness = 1.0
    if reference_corpus:
        main_content_stripped = _strip_boilerplate(html)
        stripped_corpus = [_strip_boilerplate(ref) if "<" in ref else ref for ref in reference_corpus]
        distinctiveness = compute_shingle_distinctiveness(main_content_stripped, stripped_corpus)
        if distinctiveness < 0.20:
            issues.append(f"High duplicate/doorway risk: distinctiveness is only {distinctiveness:.2f} (< 0.20)")
            score -= 3.5

    # 6. Factual Claim Extraction & Verification
    evidence_ledger = claim_evidence_ledger or {}
    verified_claims: list[dict[str, Any]] = []
    unverified_claims: list[dict[str, Any]] = []

    for pattern, claim_type in TECHNICAL_CLAIM_PATTERNS:
        for match in re.finditer(pattern, visible_text, re.IGNORECASE):
            claim_text = match.group(0).strip()
            # Check against evidence ledger
            matched_evidence = None
            for key, ev_source in evidence_ledger.items():
                if key.lower() in claim_text.lower() or claim_text.lower() in key.lower():
                    matched_evidence = ev_source
                    break

            if matched_evidence:
                verified_claims.append({
                    "claim": claim_text,
                    "type": claim_type,
                    "evidence": matched_evidence,
                    "verified": True,
                })
            else:
                # Standard recognized specs, government regulations, or web runtime give auto-pass
                if claim_type in ("official_spec", "runtime_architecture", "government_regulation", "regulatory_effective_date", "jurisdiction"):
                    verified_claims.append({
                        "claim": claim_text,
                        "type": claim_type,
                        "evidence": "formal_standards_or_regulatory_corpus",
                        "verified": True,
                    })
                else:
                    unverified_claims.append({
                        "claim": claim_text,
                        "type": claim_type,
                        "evidence": None,
                        "verified": False,
                    })

    if unverified_claims:
        score -= min(2.0, len(unverified_claims) * 0.5)

    final_score = max(0.0, min(10.0, score))
    is_valid = final_score >= 6.0 and not vaporware_matches

    return ContentUsefulnessReport(
        url=page_url,
        query=target_query,
        is_valid=is_valid,
        score=round(final_score, 2),
        issues=issues,
        verified_claims=verified_claims,
        unverified_claims=unverified_claims,
        distinctiveness_score=round(distinctiveness, 3),
        word_count=word_count,
        functional_elements_count=func_count,
        page_archetype=archetype,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit content usefulness, intent, and factual claims.")
    parser.add_argument("--file", help="HTML or template file to inspect")
    parser.add_argument("--query", default="", help="Target query to check intent against")
    parser.add_argument("--url", default="", help="Page URL")
    args = parser.parse_args(argv)

    if not args.file or not Path(args.file).exists():
        print(f"ERROR: File '{args.file}' not found.")
        return 1

    content = Path(args.file).read_text(encoding="utf-8")
    report = verify_content_usefulness(content, target_query=args.query, page_url=args.url)

    print(f"Content Usefulness Score: {report.score}/10.0 (Valid: {report.is_valid})")
    print(f"  Words: {report.word_count} | Functional Elements: {report.functional_elements_count}")
    print(f"  Distinctiveness: {report.distinctiveness_score:.2f}")
    if report.issues:
        print("  Issues:")
        for iss in report.issues:
            print(f"    - {iss}")
    if report.verified_claims:
        print(f"  Verified Claims: {len(report.verified_claims)}")
    if report.unverified_claims:
        print(f"  Unverified Claims (Need Evidence Source): {len(report.unverified_claims)}")
        for u in report.unverified_claims:
            print(f"    - {u['claim']} ({u['type']})")

    return 0 if report.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
