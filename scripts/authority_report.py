#!/usr/bin/env python3
"""Measure the off-page authority gap for a domain and its competitors."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataforseo_client import DataForSEOClient, resolve_credentials


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DataForSEO Backlinks summary for a target and competitors."
    )
    parser.add_argument("--target", required=True, help="domain, e.g. smsriver.com")
    parser.add_argument(
        "--competitors",
        default="",
        help="CSV of competitor domains to compare",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    login, password = resolve_credentials()
    client = DataForSEOClient(login, password)
    targets = [args.target.strip()] + [
        part.strip() for part in args.competitors.split(",") if part.strip()
    ]
    rows = [client.backlinks_summary(target) for target in targets]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(
        f"{'domain':28} {'rank':>6} {'ref_domains':>12} {'backlinks':>10} {'spam':>5}"
    )
    for row in rows:
        print(
            f"{str(row['target']):28} {str(row['rank']):>6} "
            f"{str(row['referring_domains']):>12} {str(row['backlinks']):>10} "
            f"{str(row['backlinks_spam_score']):>5}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
