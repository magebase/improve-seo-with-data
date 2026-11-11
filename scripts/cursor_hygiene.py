"""Cursor hygiene: pre-lease junk scrubbing, intent pre-flight, lock registry.

Wave 61's funnel (33 tasks leased -> 3 pages shipped, 48 leases stranded)
proved the cursor was feeding agents tasks that could never convert into a
shipped page in the same run:

- Boolean-operator and URL junk queries (``-site:facebook.com x``, ``a OR b``,
  ``https://...``) are NOT single-heading-addressable; leasing them burns the
  wave quota. They are terminally ``REJECTED`` before the lease.
- ``INJECT_*`` tasks whose query tokens are already fully covered by the
  route/country intent maps (the H2s shipped in waves 60/61) graduate to
  ``SHIPPED`` without leasing - no duplicate heading bloat, no quota burn.
- Route prefixes owned by a concurrent agent worktree (lock registry with a
  2h PID heartbeat) are skipped, not leased - no cross-worktree merge fights.
- Tasks deferred by agent judgment mid-wave are released back to ``PENDING``
  at closeout instead of waiting out the 1h stale-lease TTL (the 48-strand).

All state flips are single-statement CAS updates against the same state
machine in ``fleet_state`` (PENDING -> REJECTED/SHIPPED, LEASED -> PENDING);
``REJECTED`` is terminal and never re-enters the cursor (``enqueue_tasks``
skips ``(page, action_code)`` pairs that were already rejected).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

DEFAULT_LOCK_REGISTRY = Path.home() / ".seo_fleet" / "worktree_locks.json"
LOCK_HEARTBEAT_TTL_HOURS = 2

# Operators and URL fragments that make a query non-addressable by a single
# heading edit. Case-insensitive: site:/inurl:/intitle:/filetype:, raw URLs,
# www. hosts, and negation terms (-word). A mid-query "-free" style token is
# only ever a Boolean negation in telemetry, never prose.
JUNK_QUERY_RE = re.compile(r"(?i)(\bsite:|\binurl:|\bintitle:|\bfiletype:|https?://|www\.|(^|\s)-\w)")

# Boolean operators are only junk when typed UPPERCASE (the operator form);
# lowercase "and"/"or" are ordinary English words ("send and receive sms").
BOOLEAN_OPERATOR_RE = re.compile(r"\b(OR|AND)\b")

# Foreign-language function/content markers observed in real GSC telemetry
# (Dutch, German, Romance languages). A query hitting one of these while
# carrying NO common English token is treated as non-English: the route
# intents it implies are real future routes, but they are not actionable by
# this wave's English heading work, so they must not consume lease quota.
_NON_ENGLISH_MARKERS = frozenset(
    {
        # nl / de / da: 'telefon' & 'landekoder' came from real wave-61 telemetry
        "landekoder",
        "telefoonnummer",
        "telefoonnummers",
        "gratis",
        "telefon",
        "und",
        "der",
        "die",
        "das",
        "für",
        "mit",
        "von",
        "kostenlos",
        "nummern",
        # es / pt
        "para",
        "como",
        "una",
        "por",
        "recibir",
        # fr / it
        "pour",
        "des",
        "une",
        "les",
        "gratuit",
        "per",
        "come",
        "delle",
    }
)
_ENGLISH_MARKERS = frozenset(
    {
        "the",
        "for",
        "with",
        "how",
        "what",
        "why",
        "free",
        "online",
        "best",
        "vs",
        "and",
        "or",
        "to",
        "of",
        "in",
        "is",
        "on",
        "get",
        "your",
        "can",
        "app",
        "number",
        "numbers",
        "code",
        "codes",
        "sms",
        "receive",
        "send",
        "text",
        "verify",
        "verification",
        "phone",
        "lookup",
        "usa",
        "uk",
    }
)


def is_probably_non_english(query: str) -> bool:
    """True when the query carries a non-English marker and no English one.

    ``sms`` appears in both marker sets on purpose: it is never sufficient on
    its own, so ``recibir sms gratis`` (no English token) is flagged while
    ``receive sms online free`` is not.
    """
    tokens = set(re.findall(r"[a-zà-öø-ÿ]+", query.lower()))
    if not tokens:
        return False
    if tokens & _ENGLISH_MARKERS:
        return False
    return bool(tokens & _NON_ENGLISH_MARKERS)


def is_clean_english_query(query: str) -> bool:
    """True when a query is single-heading-addressable English work.

    Rejects: operator/URL junk, uppercase Boolean operators, negation terms,
    queries outside the 4-60 char / <=10 word band, >15% non-ASCII text, and
    probable non-English queries.
    """
    if not query or not query.strip():
        return False
    query = query.strip()
    if len(query) < 4 or len(query) > 60:
        return False
    if len(query.split()) > 10:
        return False
    if JUNK_QUERY_RE.search(query) or BOOLEAN_OPERATOR_RE.search(query):
        return False
    letters = [c for c in query if c.isalpha()]
    if letters:
        non_ascii = sum(1 for c in letters if ord(c) > 127)
        if non_ascii / len(letters) > 0.15:
            return False
    return not is_probably_non_english(query)


# --------------------------------------------------------------- pre-flight


def _tokens_covered(query: str, text: str) -> bool:
    """Every query token must appear in the page text (case-insensitive)."""
    tokens = {t for t in re.split(r"\s+", query.lower()) if t}
    if not tokens:
        return False
    haystack = " " + re.sub(r"[^\w\s]", " ", text.lower()) + " "
    return all(f" {token} " in haystack for token in tokens)


def enforce_url_title_lock(conn: sqlite3.Connection, cooldown_days: int = 21) -> int:
    """Prevents secondary queries in later waves from overwriting a URL's primary calibrated <title>.

    Downgrades pending title mutations on recently shipped URLs to H2/table-only enrichments,
    merging secondary queries and keeping max priority_score to prevent token loss on deduplication.
    """
    cur = conn.cursor()
    # Find all recently shipped pages with title mutations
    cur.execute(
        """
        SELECT DISTINCT page
        FROM atomic_task_backlog
        WHERE status = 'SHIPPED'
          AND action_code IN ('INJECT_EXACT_TITLE_AND_H2', 'REWRITE_SNIPPET_AND_TOP_300PX', 'CREATE_PROGRAMMATIC_ROUTE')
          AND shipped_at >= datetime('now', ?)
        """,
        (f"-{cooldown_days} days",),
    )
    shipped_pages = {row[0] for row in cur.fetchall()}
    if not shipped_pages:
        return 0

    downgraded = 0

    for page in shipped_pages:
        # Find all pending title mutations on this page, highest priority first
        cur.execute(
            """
            SELECT id, query, priority_score, lgbm_score
            FROM atomic_task_backlog
            WHERE status = 'PENDING'
              AND action_code IN ('INJECT_EXACT_TITLE_AND_H2', 'REWRITE_SNIPPET_AND_TOP_300PX', 'CREATE_PROGRAMMATIC_ROUTE')
              AND page = ?
            ORDER BY priority_score DESC, id ASC
            """,
            (page,),
        )
        pending_title_tasks = cur.fetchall()
        if not pending_title_tasks:
            continue

        # Check if there is already an open INJECT_SECONDARY_H2_ONLY task for this page
        cur.execute(
            """
            SELECT id, query, priority_score, lgbm_score, status
            FROM atomic_task_backlog
            WHERE status IN ('PENDING', 'LEASED')
              AND action_code = 'INJECT_SECONDARY_H2_ONLY'
              AND page = ?
            ORDER BY priority_score DESC, id ASC
            """,
            (page,),
        )
        existing_secondary = cur.fetchone()

        if existing_secondary:
            # We already have an open INJECT_SECONDARY_H2_ONLY task on this page.
            # Merge candidate queries into existing task to preserve keyword context.
            surviving_id, ex_query, ex_p_score, ex_lgbm_score, _ = existing_secondary

            existing_queries = [q.strip() for q in (ex_query or "").split("|") if q.strip()]
            queries_set = {q.lower() for q in existing_queries}

            max_p_score = float(ex_p_score or 0.0)
            max_lgbm = float(ex_lgbm_score or 0.0)

            for cand_id, cand_query, cand_p_score, cand_lgbm in pending_title_tasks:
                for q in (cand_query or "").split("|"):
                    q_clean = q.strip()
                    if q_clean and q_clean.lower() not in queries_set:
                        existing_queries.append(q_clean)
                        queries_set.add(q_clean.lower())
                if float(cand_p_score or 0.0) > max_p_score:
                    max_p_score = float(cand_p_score or 0.0)
                if float(cand_lgbm or 0.0) > max_lgbm:
                    max_lgbm = float(cand_lgbm or 0.0)
                # Delete the redundant pending title task
                cur.execute("DELETE FROM atomic_task_backlog WHERE id = ?", (cand_id,))

            merged_query_str = " | ".join(existing_queries)
            assertion = f"assert a new <h2> or <table> section covers '{merged_query_str}' without altering the established <title>"
            cur.execute(
                """
                UPDATE atomic_task_backlog
                SET query = ?, priority_score = ?, lgbm_score = ?, tdd_assertion = ?
                WHERE id = ?
                """,
                (merged_query_str, max_p_score, max_lgbm, assertion, surviving_id),
            )
            downgraded += len(pending_title_tasks)
        else:
            # No existing INJECT_SECONDARY_H2_ONLY task.
            # Pick the top priority task as the surviving task, and merge remaining candidates into it.
            top_task = pending_title_tasks[0]
            surviving_id, top_query, top_p_score, top_lgbm = top_task

            collected_queries = [q.strip() for q in (top_query or "").split("|") if q.strip()]
            queries_set = {q.lower() for q in collected_queries}
            max_p_score = float(top_p_score or 0.0)
            max_lgbm = float(top_lgbm or 0.0)

            for cand_id, cand_query, cand_p_score, cand_lgbm in pending_title_tasks[1:]:
                for q in (cand_query or "").split("|"):
                    q_clean = q.strip()
                    if q_clean and q_clean.lower() not in queries_set:
                        collected_queries.append(q_clean)
                        queries_set.add(q_clean.lower())
                if float(cand_p_score or 0.0) > max_p_score:
                    max_p_score = float(cand_p_score or 0.0)
                if float(cand_lgbm or 0.0) > max_lgbm:
                    max_lgbm = float(cand_lgbm or 0.0)
                # Delete the redundant pending title task
                cur.execute("DELETE FROM atomic_task_backlog WHERE id = ?", (cand_id,))

            merged_query_str = " | ".join(collected_queries)
            assertion = f"assert a new <h2> or <table> section covers '{merged_query_str}' without altering the established <title>"
            cur.execute(
                """
                UPDATE atomic_task_backlog
                SET action_code = 'INJECT_SECONDARY_H2_ONLY',
                    query = ?,
                    priority_score = ?,
                    lgbm_score = ?,
                    tdd_assertion = ?
                WHERE id = ?
                """,
                (merged_query_str, max_p_score, max_lgbm, assertion, surviving_id),
            )
            downgraded += len(pending_title_tasks)

    conn.commit()
    return downgraded


def preflight_hygiene(
    conn: sqlite3.Connection,
    route_intent_map: Optional[Dict[str, str]] = None,
    locked_path_prefixes: Sequence[str] = (),
    max_intent_tasks_per_page: int = 2,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """Scrub the PENDING cursor BEFORE the stratified lease runs.

    Returns a report dict: ``rejected`` (junk -> REJECTED, terminal),
    ``graduated`` (INJECT_* tasks whose tokens the intent maps already cover
    -> SHIPPED), ``locked`` (page/file_target under another worktree's
    registered prefix -> left PENDING), ``intent_capped`` (would exceed the
    per-URL intent-heading cap -> left PENDING) and ``leasable`` (clean,
    uncovered, unowned candidates handed to ``lease_tasks``).
    """
    stamp = _iso(now)
    from candidate_hygiene import is_valid_property_host
    from fleet_state import canonicalize_backlog_action_codes

    canonicalize_backlog_action_codes(conn)
    title_locked = enforce_url_title_lock(conn)
    rows = conn.execute(
        "SELECT id, page, query, action_code, file_target, domain FROM atomic_task_backlog WHERE status = 'PENDING'"
    ).fetchall()
    report = {
        "rejected": 0,
        "graduated": 0,
        "locked": 0,
        "intent_capped": 0,
        "leasable": 0,
        "title_locked": title_locked,
    }
    intent_counts: Dict[str, int] = {}
    if max_intent_tasks_per_page > 0:
        for (page,) in conn.execute(
            "SELECT page FROM atomic_task_backlog WHERE action_code LIKE 'INJECT_%' AND status IN ('SHIPPED', 'LEASED')"
        ):
            intent_counts[page] = intent_counts.get(page, 0) + 1

    for task_id, page, query, action_code, file_target, domain in rows:
        if domain and page and page.startswith("http") and not is_valid_property_host(page, domain):
            _cas_status(conn, task_id, "REJECTED", shipped=False, stamp=stamp)
            report["rejected"] += 1
            continue
        if not is_clean_english_query(query or ""):
            _cas_status(conn, task_id, "REJECTED", shipped=False, stamp=stamp)
            report["rejected"] += 1
            continue
        page_path = urlparse(page).path if "://" in (page or "") else (page or "")
        if page_path in ("", "/") and (action_code or "") in (
            "WIRE_HUB_AND_FOOTER_INLINKS",
            "STRENGTHEN_HUB_INTERNAL_LINKS",
            "RESCUE_ORPHAN_ROUTE_INLINKS",
            "BOOST_CLUSTER_CROSS_LINKS",
        ):
            _cas_status(conn, task_id, "REJECTED", shipped=False, stamp=stamp)
            report["rejected"] += 1
            continue
        intent_text = (route_intent_map or {}).get(page, "")
        if (action_code or "").startswith("INJECT_") and intent_text and _tokens_covered(query or "", intent_text):
            _cas_status(conn, task_id, "SHIPPED", shipped=True, stamp=stamp)
            report["graduated"] += 1
            continue
        if _is_locked(page, file_target, locked_path_prefixes):
            report["locked"] += 1
            continue
        if (action_code or "").startswith("INJECT_") and max_intent_tasks_per_page > 0:
            current = intent_counts.get(page, 0) + 1
            if current > max_intent_tasks_per_page:
                report["intent_capped"] += 1
                continue
            intent_counts[page] = current
        report["leasable"] += 1
    conn.commit()
    return report


def _is_locked(page: str, file_target: Optional[str], prefixes: Sequence[str]) -> bool:
    for prefix in prefixes:
        if prefix and ((page or "").startswith(prefix) or (file_target or "").startswith(prefix)):
            return True
    return False


def _cas_status(
    conn: sqlite3.Connection,
    task_id: int,
    status: str,
    shipped: bool,
    stamp: Optional[str],
) -> bool:
    if shipped:
        cursor = conn.execute(
            "UPDATE atomic_task_backlog SET status = ?, shipped_at = ? WHERE id = ? AND status = 'PENDING'",
            (status, stamp, task_id),
        )
    else:
        cursor = conn.execute(
            "UPDATE atomic_task_backlog SET status = ? WHERE id = ? AND status = 'PENDING'",
            (status, task_id),
        )
    return cursor.rowcount == 1


def _iso(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


# --------------------------------------------------- deferred-lease release


def release_deferred_leases_on_closeout(
    conn: sqlite3.Connection,
    deferred_ids: Iterable[int],
) -> int:
    """Returns agent-deferred LEASED tasks to PENDING immediately.

    Called at wave closeout for tasks the agent judged unfit this run
    (registry violations, pseudo-pages, typo queries). Without this they
    strand as LEASED for the full 1h stale-lease TTL, inflating the lease
    count and blocking their file_targets for other agents.
    """
    ids = [int(i) for i in deferred_ids]
    if not ids:
        return 0
    placeholders = ", ".join("?" * len(ids))
    cursor = conn.execute(
        "UPDATE atomic_task_backlog SET status = 'PENDING', leased_at = NULL "
        f"WHERE id IN ({placeholders}) AND status = 'LEASED'",
        ids,
    )
    conn.commit()
    return cursor.rowcount


# ------------------------------------------------------ worktree lock registry


def register_worktree_locks(
    prefixes: Sequence[str],
    agent_id: str,
    registry_path: os.PathLike | str = DEFAULT_LOCK_REGISTRY,
    pid: Optional[int] = None,
    now: Optional[datetime] = None,
) -> None:
    """Registers this worktree's owned route/template prefixes.

    Other agents' pre-flight skips these prefixes while the heartbeat is
    fresh (2h TTL) and the PID is alive; the entry self-expires otherwise.
    """
    registry_path = Path(registry_path)
    data = _load_registry(registry_path)
    live = _live_entries(data.get("locks", []), now=now)
    entry = {
        "agent_id": agent_id,
        "prefixes": [p for p in prefixes if p],
        "pid": pid,
        "heartbeat": _iso(now),
    }
    live = [e for e in live if e.get("agent_id") != agent_id]
    live.append(entry)
    _save_registry(registry_path, {"locks": live})


def release_worktree_locks(
    agent_id: str,
    registry_path: os.PathLike | str = DEFAULT_LOCK_REGISTRY,
) -> None:
    """Removes this agent's lock entries (wave closeout / teardown)."""
    registry_path = Path(registry_path)
    data = _load_registry(registry_path)
    live = [e for e in data.get("locks", []) if e.get("agent_id") != agent_id]
    _save_registry(registry_path, {"locks": live})


def active_locked_prefixes(
    registry_path: os.PathLike | str = DEFAULT_LOCK_REGISTRY,
    now: Optional[datetime] = None,
) -> tuple:
    """All prefixes currently held by live agent worktrees."""
    data = _load_registry(Path(registry_path))
    prefixes: set = set()
    for entry in _live_entries(data.get("locks", []), now=now):
        prefixes.update(entry.get("prefixes") or [])
    return tuple(sorted(prefixes))


def _load_registry(registry_path: Path) -> Dict[str, Any]:
    try:
        return json.loads(registry_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"locks": []}


def _save_registry(registry_path: Path, data: Dict[str, Any]) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(data, indent=2))


def _live_entries(entries: list, now: Optional[datetime]) -> list:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cutoff = moment - timedelta(hours=LOCK_HEARTBEAT_TTL_HOURS)
    live = []
    for entry in entries:
        try:
            heartbeat = datetime.fromisoformat(str(entry.get("heartbeat", "")))
        except ValueError:
            continue
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        if heartbeat < cutoff:
            continue
        pid = entry.get("pid")
        if pid and not _pid_alive(int(pid)):
            continue
        live.append(entry)
    return live


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive but owned by another user
    except OSError:
        return False
    return True


def main(argv: Optional[list[str]] = None) -> int:
    """Executor-facing CLI for the wave closeout and lock lifecycle.

    Examples:
        python cursor_hygiene.py --state-db ~/.seo_fleet/fleet_state.db \\
            --release-deferred 101,102,103
        python cursor_hygiene.py --register-locks /country-codes/ \\
            templates/smspool/country_code_detail.html
        python cursor_hygiene.py --show-locks
        python cursor_hygiene.py --release-locks
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-db", default="", help="SQLite fleet state DB")
    parser.add_argument(
        "--release-deferred",
        default="",
        help="comma-separated task ids to return to PENDING",
    )
    parser.add_argument("--register-locks", nargs="*", default=None, help="prefixes to register")
    parser.add_argument("--show-locks", action="store_true")
    parser.add_argument("--release-locks", action="store_true")
    args = parser.parse_args(argv)

    agent_id = os.environ.get("SEO_AGENT_ID") or f"pid-{os.getpid()}"
    if args.release_deferred:
        if not args.state_db:
            parser.error("--release-deferred requires --state-db")
        from fleet_state import connect_state_db

        ids = [int(x) for x in args.release_deferred.split(",") if x.strip()]
        conn = connect_state_db(args.state_db)
        released = release_deferred_leases_on_closeout(conn, ids)
        conn.close()
        print(f"Released {released} deferred LEASED task(s) back to PENDING.")
    if args.register_locks is not None:
        register_worktree_locks(args.register_locks, agent_id=agent_id)
        print(f"Registered locks: {', '.join(args.register_locks) or '(none)'}")
    if args.show_locks:
        prefixes = active_locked_prefixes()
        print(f"Active locked prefixes ({len(prefixes)}):")
        for prefix in prefixes:
            print(f"  {prefix}")
    if args.release_locks:
        release_worktree_locks(agent_id)
        print("Released this agent's locks.")
    if not any(
        [
            args.release_deferred,
            args.register_locks is not None,
            args.show_locks,
            args.release_locks,
        ]
    ):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
