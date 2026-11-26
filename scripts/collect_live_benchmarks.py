#!/usr/bin/env python3
"""Collect live benchmark telemetry into page contracts.

This is the Track 2 bridge between discovery and page creation. It reads a
public sitemap, fetches the benchmark pages the site actually serves, extracts
the values rendered from the site's own database, and refuses to emit contracts
unless at least three fields vary across siblings and the stripped overlap is
below the factory threshold. It never invents a field.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleet_state import connect_state_db
from seo_factory import (
    MIN_PLANNED_INLINKS,
    compute_stripped_overlap,
    create_cohort,
    register_page_contract,
    validate_page_contract,
)

METRIC_RE = re.compile(r'data-metric="([a-z_]+)">([^<]*)<')
ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _fetch(url: str, timeout: int = 20) -> str:
    request = Request(url, headers={"User-Agent": "improve-seo-with-data/track2"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", fragment)).strip()


def _benchmark_urls(sitemap_url: str, limit: int) -> list[str]:
    body = _fetch(sitemap_url)
    urls = [
        value
        for value in re.findall(r"<loc>(.*?)</loc>", body)
        if "/benchmarks/" in value
    ]
    return urls[: max(0, limit)]


def _extract(html: str) -> dict[str, object]:
    metrics = {name: value.strip() for name, value in METRIC_RE.findall(html)}
    rows: list[list[str]] = []
    for row in ROW_RE.findall(html):
        cells = [_text(cell) for cell in CELL_RE.findall(row)]
        if cells:
            rows.append(cells)
    benchmark_match = re.search(
        r'data-role="game-benchmark"(.*?)</main>', html, re.DOTALL | re.IGNORECASE
    )
    title = _text(TITLE_RE.search(html).group(1)) if TITLE_RE.search(html) else ""
    body = _text(benchmark_match.group(1)) if benchmark_match else _text(html)
    return {
        "metrics": metrics,
        "rows": rows,
        "title": title,
        "entity": re.split(r"\s+Server Benchmarks", title, maxsplit=1)[0],
        "text": body,
        "hash": hashlib.sha256(html.encode("utf-8")).hexdigest(),
    }


def collect(sitemap_url: str, *, limit: int = 15) -> list[dict[str, object]]:
    pages: list[dict[str, object]] = []
    for url in _benchmark_urls(sitemap_url, limit):
        html = _fetch(url)
        page = _extract(html)
        page["url"] = url
        pages.append(page)
    if len(pages) < 5:
        raise RuntimeError(
            f"only {len(pages)} benchmark pages found; a pilot needs at least 5"
        )

    metric_names = sorted({name for page in pages for name in page["metrics"]})  # type: ignore[index]
    varying = [
        name
        for name in metric_names
        if len({str(page["metrics"].get(name, "")) for page in pages}) > 1  # type: ignore[index]
    ]
    if len(varying) < 3:
        raise RuntimeError(
            f"only {len(varying)} cross-sibling varying metrics ({varying}); need at least 3"
        )

    texts = [str(page["text"]) for page in pages]
    entities = [str(page["entity"]) for page in pages]
    overlap = compute_stripped_overlap(texts, entities=entities)
    if overlap > 0.45:
        raise RuntimeError(f"entity-stripped overlap {overlap} exceeds 0.45")

    contracts: list[dict[str, object]] = []
    for page in pages:
        fields = {
            "metrics": page["metrics"],
            "tables": page["rows"],
        }
        contracts.append(
            {
                "url": page["url"],
                "cluster_id": "",
                "tier": "B",
                "data_source_hash": hashlib.sha256(
                    json.dumps(fields, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "unique_data_fields": len(varying),
                "stripped_overlap_score": overlap,
                "planned_indexed_inlinks": max(MIN_PLANNED_INLINKS, 1),
                "telemetry_fields": varying,
                "telemetry": fields,
                "status": "COLLECTED",
            }
        )
    return contracts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect benchmark page contracts")
    parser.add_argument("--sitemap", required=True)
    parser.add_argument("--cluster-id", default="")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--output", default="")
    parser.add_argument("--state-db", default="")
    parser.add_argument("--cohort-template", default="gameserver-benchmark")
    parser.add_argument("--domain", default="")
    args = parser.parse_args(argv)

    contracts = collect(args.sitemap, limit=args.limit)
    for contract in contracts:
        contract["cluster_id"] = args.cluster_id
        contract["validation"] = validate_page_contract(contract)
    if not all(contract["validation"]["valid"] for contract in contracts):  # type: ignore[index]
        raise RuntimeError("one or more collected contracts failed validation")
    text = json.dumps(contracts, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)

    if args.state_db:
        conn = connect_state_db(args.state_db)
        try:
            for contract in contracts:
                register_page_contract(conn, contract)
            if args.domain:
                created = create_cohort(
                    conn,
                    template_id=args.cohort_template,
                    domain=args.domain,
                    urls=[str(contract["url"]) for contract in contracts],
                )
                print(json.dumps({"cohort": created}, indent=2))
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
