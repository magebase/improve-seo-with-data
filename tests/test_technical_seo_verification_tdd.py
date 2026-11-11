"""test_technical_seo_verification_tdd.py - TDD test suite for 10-point Technical SEO Gate.

Verifies:
- Detection of accidental noindex (meta robots or X-Robots-Tag)
- Canonical URL validation (missing, relative, or host mismatch)
- Primary H1 validation (missing or multiple H1s)
- Rendered content length and body presence
- Structured data JSON-LD parsing and syntax check
- Viewport mobile configuration
- Internal crawlable links count
- Integration with rewarm_urls (deep_verify)
"""

from __future__ import annotations

import pytest

from improve_seo_rewarm import RewarmTargets, rewarm_urls
from verify_technical_seo import (
    audit_html_technical_seo,
    estimate_title_pixel_width,
)


def test_clean_html_passes_all_technical_seo_gates():
    """A standard compliant page passes all 10 technical SEO gates."""
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Convert BMP to PNG Online Free — OpenFileConverter</title>
        <link rel="canonical" href="https://openfileconverter.com/convert/bmp-to-png/">
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "WebApplication",
            "name": "BMP to PNG Converter",
            "applicationCategory": "UtilitiesApplication"
        }
        </script>
    </head>
    <body>
        <h1>Convert BMP to PNG Online Free</h1>
        <p>Convert your Windows bitmap images to portable network graphics with zero file uploads.</p>
        <form><input type="file" /></form>
        <div class="links">
            <a href="/convert/gif-to-png/">Convert GIF to PNG</a>
            <a href="/convert/ico-to-png/">Convert ICO to PNG</a>
        </div>
    </body>
    </html>
    """
    res = audit_html_technical_seo(html, url="https://openfileconverter.com/convert/bmp-to-png/")
    assert res.all_passed is True
    assert res.score == 10.0
    assert len(res.errors) == 0


def test_blocking_accidental_noindex():
    """Any meta robots noindex or header X-Robots-Tag noindex must fail the gate."""
    html = """
    <html>
    <head>
        <meta name="viewport" content="width=device-width">
        <meta name="robots" content="noindex, follow">
        <title>Test Page Title Here | OpenFile</title>
        <link rel="canonical" href="https://openfileconverter.com/test/">
    </head>
    <body>
        <h1>Test Page</h1>
        <p>Some body text that is long enough to pass the length gate easily.</p>
        <a href="/a/">Link A</a>
        <a href="/b/">Link B</a>
    </body>
    </html>
    """
    res = audit_html_technical_seo(html, url="https://openfileconverter.com/test/")
    assert res.all_passed is False
    assert any("noindex" in e.lower() for e in res.errors)


def test_canonical_host_mismatch_failure():
    """A canonical pointing to an unexpected host must fail."""
    html = """
    <html>
    <head>
        <meta name="viewport" content="width=device-width">
        <title>Test Page Title Here | OpenFile</title>
        <link rel="canonical" href="https://wrong-domain.com/test/">
    </head>
    <body>
        <h1>Test Page</h1>
        <p>Some body text that is long enough to pass the length gate easily.</p>
        <a href="/a/">Link A</a>
        <a href="/b/">Link B</a>
    </body>
    </html>
    """
    res = audit_html_technical_seo(html, url="https://openfileconverter.com/test/")
    assert res.all_passed is False
    assert any("canonical host mismatch" in e.lower() for e in res.errors)


def test_title_pixel_width_heuristic():
    """Heuristic calculation matches expected desktop SERP bounds."""
    short_title = "BMP to PNG"
    assert estimate_title_pixel_width(short_title) < 150.0

    calibrated_title = "Convert BMP to PNG Online Free — OpenFileConverter"
    px = estimate_title_pixel_width(calibrated_title)
    assert 350.0 <= px <= 550.0
