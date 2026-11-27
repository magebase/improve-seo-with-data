#!/usr/bin/env python3
"""Sweep header signer for authenticated production SEO verification probes."""

from __future__ import annotations

import argparse
import json
import sys

from seo_shared import sign_sweep_headers


def build_sweep_headers(url: str, secret: str | None = None, timestamp: int | None = None) -> dict[str, str]:
    """Returns signed sweep verification headers for the given target URL."""
    return sign_sweep_headers(url, secret=secret, timestamp=timestamp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate HMAC-signed SEO sweep verification headers.")
    parser.add_argument("--url", required=True, help="Target URL being probed")
    parser.add_argument("--secret", default=None, help="Optional HMAC secret (defaults to SEO_SWEEP_SECRET env)")
    args = parser.parse_args(argv)
    print(json.dumps(build_sweep_headers(args.url, secret=args.secret), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
