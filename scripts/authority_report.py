#!/usr/bin/env python3
"""Measure the off-page authority gap for a domain and its competitors."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataforseo_client import DataForSEOClient, resolve_credentials
from growth_loop import is_flagged_pbn_domain


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
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove flagged PBN/spam referring domains from the count",
    )
    args = parser.parse_args(argv)

    login, password = resolve_credentials()
    client = DataForSEOClient(login, password)
    targets = [args.target.strip()] + [
        part.strip() for part in args.competitors.split(",") if part.strip()
    ]
    rows = [client.backlinks_summary(target) for target in targets]
    if args.clean:
        for row in rows:
            try:
                backlinks = client.backlinks_list(str(row["target"]))
            except Exception:  # noqa: BLE001 - authority is advisory evidence
                row["legitimate_referring_domains"] = None
                continue
            clean = {
                item["domain_from"].lower()
                for item in backlinks
                if item.get("domain_from")
                and not is_flagged_pbn_domain(item["domain_from"])
                and float(item.get("backlink_spam_score") or 0) < 60
            }
            row["legitimate_referring_domains"] = len(clean)
            row["flagged_referring_domains"] = max(
                0, int(row.get("referring_domains") or 0) - len(clean)
            )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(
        f"{'domain':28} {'rank':>6} {'ref_domains':>12} {'clean_rd':>9} "
        f"{'backlinks':>10} {'spam':>5}"
    )
    for row in rows:
        print(
            f"{row['target']!s:28} {row['rank']!s:>6} "
            f"{row['referring_domains']!s:>12} "
            f"{row.get('legitimate_referring_domains', '-')!s:>9} "
            f"{row['backlinks']!s:>10} {row['backlinks_spam_score']!s:>5}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
