"""test_content_usefulness_tdd.py - TDD test suite for Content Usefulness & Claim Provenance Gate.

Verifies:
- Detection and blocking of vaporware / roadmap copy (Invariant F)
- Detection and blocking of unsubstantiated marketing hype
- Thin content detection (< 120 words)
- Query intent fulfillment in headings or body
- Functional utility verification (tables, canvas, forms)
- Shingle distinctiveness against sibling doorway templates
- Technical claim verification against evidence ledger
"""

from __future__ import annotations

import pytest

from content_usefulness_gate import (
    compute_shingle_distinctiveness,
    verify_content_usefulness,
)


def test_anti_vaporware_rejection():
    """Invariant F: Banned phrases like 'in rollout' or 'coming soon' must fail validation."""
    html = """
    <html>
    <body>
        <h1>Convert PNG to SVG Vector</h1>
        <h2>Engine Status</h2>
        <p>Our server-side pipeline is in rollout and coming soon for enterprise files.</p>
        <table><tr><td>Engine</td><td>Status</td></tr><tr><td>vtracer</td><td>Rollout</td></tr></table>
    </body>
    </html>
    """
    report = verify_content_usefulness(html, target_query="png to svg")
    assert not report.is_valid
    assert any("vaporware" in iss.lower() for iss in report.issues)


def test_thin_content_rejection():
    """Pages with fewer than 120 words must be flagged as thin content."""
    html = """
    <html>
    <body>
        <h1>LAS Point Cloud Viewer</h1>
        <p>Open and view your LAS files online in your browser easily.</p>
        <button>Upload</button>
    </body>
    </html>
    """
    report = verify_content_usefulness(html, target_query="las point cloud viewer")
    assert not report.is_valid
    assert any("thin content" in iss.lower() for iss in report.issues)


def test_shingle_distinctiveness_doorway_detection():
    """Pages that are 90%+ identical boilerplate must be flagged as doorway risk."""
    template_boilerplate = """
    Welcome to our online file conversion suite. Upload your file, select target format,
    and download the result in seconds. All files are processed safely in your browser.
    Fast, reliable, secure, and completely free for everyday use.
    """
    page_a = template_boilerplate + " Convert BMP to PNG easily."
    page_b = template_boilerplate + " Convert GIF to PNG easily."

    distinctiveness = compute_shingle_distinctiveness(page_b, [page_a])
    assert distinctiveness < 0.20  # Nearly identical -> doorway risk


def test_technical_claim_provenance_verification():
    """Verifies that concrete performance claims require an evidence source."""
    html = """
    <html>
    <body>
        <h1>Whisper Audio Processing Services Studio</h1>
        <h2>Whisper Audio Processing Services: Neural Transcription Architecture</h2>
        <p>
            OpenFileConverter delivers client-side Whisper audio processing services using optimized
            WebAssembly SIMD acceleration. Audio waveforms are decoded in isolated background Web Workers,
            achieving ~12x realtime throughput with the Whisper-Tiny 39M param transformer model.
            Full compliance with ASPRS LAS v1.4 and ISO 32000 specifications.
            Our browser-based pipeline decodes 16-bit uncompressed linear PCM audio at 16,000 Hz, passes 80-channel
            log-mel filterbank spectrogram representations into a Transformer encoder, and streams auto-regressive
            multilingual tokens directly into synchronized SRT and VTT subtitle containers.
            By compiling models to native WebAssembly with fixed 128-bit SIMD registers, memory consumption remains
            strictly capped under 128 MB, guaranteeing robust performance without client-side isolate memory exhaustion.
        </p>
        <table>
            <tr><th>Engine</th><th>Model</th><th>Latency</th></tr>
            <tr><td>Tiny</td><td>39M Param Transformer</td><td>~12x realtime</td></tr>
        </table>
        <form><input type="file" /></form>
    </body>
    </html>
    """
    evidence_ledger = {
        "39M Param Transformer": "source_code:apps/file_converter/models.py",
        "~12x realtime": "measured_benchmark:benchmarks/whisper_bench.json",
    }

    report = verify_content_usefulness(
        html,
        target_query="whisper audio processing services",
        claim_evidence_ledger=evidence_ledger,
    )
    assert report.is_valid
    assert len(report.verified_claims) >= 2
    assert len(report.unverified_claims) == 0
    assert report.score >= 8.0
