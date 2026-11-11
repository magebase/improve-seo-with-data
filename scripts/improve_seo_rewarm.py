"""Post-enrichment cache re-warm client (Invariant E, fleet deploy safety).

When a D1 content-mutation wave (ADD_D1_SPEC_COMPARISON_TABLE & friends)
touches URLs whose bot HTML is pre-warmed in the edge caches (L1 Cache API,
L2 KV `figiva:bothtml:vN:<path>`), the wave MUST atomically overwrite those
caches upon task completion — otherwise Googlebot crawls the stale
pre-enrichment HTML until the 6h TTL or a global CACHE_KEY_VERSION bump.

Mechanism: fire a `X-SEO-Verify: 1` GET per mutated URL. The worker's
`bypass_edge_cache_reads()` skips BOTH the L1 Cache API read and the L2 KV
read, freshly renders the current (enriched) DOM, and stores it — L1 put +
KV overwrite — in the same request. No spoofed crawler UA is ever sent
(sweeps must not poison crawl-velocity telemetry; the verify header opts
into the bot render/store path by itself).

Usage (wave completion hook):

    from improve_seo_rewarm import RewarmTargets, rewarm_urls

    summary = rewarm_urls(
        RewarmTargets(host="figiva.com", paths=[t.url_path for t in shipped]),
    )
    if not summary.all_ok:
        print("re-warm incomplete; failing URLs:", summary.failures)

Only 2xx statuses count as ok; every failure is isolated, retried
(`max_attempts`, bounded backoff), and reported — a dead origin must
degrade to a reported failure, never an exception in the wave runner.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

VERIFY_HEADER = "X-SEO-Verify"
VERIFY_VALUE = "1"
#: Never a spoofed crawler UA: the X-SEO-Verify header alone opts the request
#: into the bot render/store path without polluting crawler telemetry.
SWEEP_USER_AGENT = "saas-factory-seo-sweep/1.0 (cache re-warm; +https://figiva.com)"


@dataclass(frozen=True)
class RewarmTargets:
    """The mutated URLs of one completed wave (host + canonical pathnames)."""

    host: str
    paths: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        for path in self.paths:
            if not path.startswith("/"):
                raise ValueError(
                    f"path must be canonical (leading /): {path!r}"
                )


@dataclass(frozen=True)
class RewarmResult:
    path: str
    status: int | None
    attempts: int
    error: str | None
    technical_audit: Any | None = None

    @property
    def ok(self) -> bool:
        base_ok = self.status is not None and 200 <= self.status < 300
        if not base_ok:
            return False
        if self.technical_audit is not None and hasattr(self.technical_audit, "all_passed"):
            return bool(self.technical_audit.all_passed)
        return True


@dataclass(frozen=True)
class RewarmSummary:
    results: tuple[RewarmResult, ...]

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and self.fail_count == 0

    @property
    def failures(self) -> list[RewarmResult]:
        return [r for r in self.results if not r.ok]


def _rewarm_one(
    url: str,
    *,
    opener: Any,
    timeout_seconds: float,
    max_attempts: int,
    retry_backoff_seconds: float,
    sleep: Callable[[float], None],
    deep_verify: bool = False,
) -> RewarmResult:
    last_error: str | None = None
    path = urlparse(url).path or "/"
    for attempt in range(1, max_attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                method="GET",
                headers={
                    VERIFY_HEADER: VERIFY_VALUE,
                    "User-Agent": SWEEP_USER_AGENT,
                },
            )
            response = opener.open(request, timeout=timeout_seconds)
            body_content: str | None = None
            resp_headers: dict[str, str] = {}
            if isinstance(response, int):  # test seams may return bare codes
                status: int | None = response
            else:
                status = getattr(response, "status", None)
                if status is None and hasattr(response, "getcode"):
                    status = response.getcode()
                if deep_verify and hasattr(response, "read"):
                    try:
                        raw_bytes = response.read()
                        body_content = raw_bytes.decode("utf-8", errors="replace")
                        if hasattr(response, "headers"):
                            resp_headers = dict(response.headers)
                    except Exception:
                        pass

            tech_audit = None
            if deep_verify and body_content:
                from verify_technical_seo import audit_html_technical_seo
                tech_audit = audit_html_technical_seo(
                    body_content,
                    url=url,
                    headers=resp_headers,
                    status_code=int(status or 200),
                )

            return RewarmResult(
                path=path,
                status=int(status or 0) or None,
                attempts=attempt,
                error=None,
                technical_audit=tech_audit,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
            # transport layer: isolate, retry, report (never a blind except —
            # a coding bug must surface, not vanish into a retry loop)
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < max_attempts and retry_backoff_seconds:
                sleep(retry_backoff_seconds)
    return RewarmResult(path=path, status=None, attempts=max_attempts, error=last_error)


def rewarm_urls(
    targets: RewarmTargets,
    *,
    opener: Any | None = None,
    timeout_seconds: float = 15.0,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    deep_verify: bool = False,
) -> RewarmSummary:
    """Re-warm every mutated URL via X-SEO-Verify GETs. Never raises."""
    real_opener = opener if opener is not None else urllib.request.build_opener()
    results = [
        _rewarm_one(
            f"https://{targets.host}{path}",
            opener=real_opener,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            sleep=sleep,
            deep_verify=deep_verify,
        )
        for path in targets.paths
    ]
    return RewarmSummary(results=tuple(results))


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Re-warm mutated URLs via X-SEO-Verify GETs.")
    parser.add_argument("--host", default="figiva.com", help="Target hostname (default: figiva.com)")
    parser.add_argument("--urls", nargs="+", help="Full URLs to re-warm")
    parser.add_argument("--paths", nargs="+", help="Canonical paths to re-warm")
    parser.add_argument("--deep-verify", action="store_true", help="Run full 10-point technical SEO audit on responses")
    args = parser.parse_args()

    paths: list[str] = []
    host = args.host
    if args.urls:
        for u in args.urls:
            p = urlparse(u)
            if p.netloc:
                host = p.netloc
            paths.append(p.path or "/")
    elif args.paths:
        paths = args.paths

    if not paths:
        print("Usage: improve_seo_rewarm.py --urls <url1> <url2>... or --paths <p1> <p2>...")
        sys.exit(1)

    print(f"Re-warming {len(paths)} paths on {host} (deep_verify={args.deep_verify})...")
    summary = rewarm_urls(RewarmTargets(host=host, paths=paths), deep_verify=args.deep_verify)
    for r in summary.results:
        status_str = f"{r.status}" if r.status else f"ERR: {r.error}"
        audit_note = ""
        if r.technical_audit is not None:
            audit_note = f" [SEO: {'PASS' if r.technical_audit.all_passed else 'FAIL'} ({r.technical_audit.score}/10)]"
        print(f"  [{status_str}] {r.path} (attempts={r.attempts}){audit_note}")
    print(f"Summary: {summary.ok_count}/{len(paths)} OK, {summary.fail_count} failed.")
    sys.exit(0 if summary.all_ok else 1)

