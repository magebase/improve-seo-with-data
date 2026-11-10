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

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


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
            if isinstance(response, int):  # test seams may return bare codes
                status: int | None = response
            else:
                status = getattr(response, "status", None)
                if status is None and hasattr(response, "getcode"):
                    status = response.getcode()
            return RewarmResult(
                path=path,
                status=int(status or 0) or None,
                attempts=attempt,
                error=None,
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
        )
        for path in targets.paths
    ]
    return RewarmSummary(results=tuple(results))
