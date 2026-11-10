"""
Unit TDD Test Suite for Cursor Hygiene & Task-Type Quotas (Wave 62 patches).

Wave 61's funnel (33 leased -> 3 shipped, 48 stranded LEASED) exposed four
gaps this suite locks down:

1. Pre-lease hygiene: Boolean-operator/URL junk queries are terminally
   REJECTED before they can burn lease quota or ranker slots; legitimate
   English queries containing "and"/"or" as WORDS must survive.
2. Pre-flight graduation: INJECT_* tasks whose query tokens are already
   covered by the route/country intent maps graduate to SHIPPED without a
   lease round-trip (no duplicate H2 bloat).
3. Task-type quota split: the stratified lease enforces per-action-code
   caps so waves carry D1 tables, inlinks, CTR hooks and route builds —
   not 30 identical heading checks.
4. Worktree lock registry: agents register route prefixes with a PID+TTL
   heartbeat; locked prefixes are skipped at pre-flight and deferred
   leases are released back to PENDING at closeout instead of waiting
   out the 1h TTL.

Rule 42: Strict Red -> Green -> Red TDD cycle.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cursor_hygiene import (
    is_clean_english_query,
    is_probably_non_english,
    preflight_hygiene,
    register_worktree_locks,
    active_locked_prefixes,
    release_worktree_locks,
    release_deferred_leases_on_closeout,
)
from fleet_state import (
    DEFAULT_TYPE_CAPS,
    connect_state_db,
    enqueue_tasks,
    lease_tasks,
    pending_count,
)


@pytest.fixture
def conn(tmp_path: Path):
    return connect_state_db(str(tmp_path / "hygiene.db"))


# ---------------------------------------------------------------- 1. scrubber


@pytest.mark.parametrize(
    "query",
    [
        "-site:facebook.com -site:reddit.com telnyx",
        'site:smsriver.com "receive sms"',
        "inurl:guides telnyx",
        "intitle:sms free",
        "https://smsriver.com/guides/",
        "www.smsriver.com receive sms",
        "telnyx OR twilio",
        "sms -free",
    ],
)
def test_junk_queries_are_rejected(query):
    assert not is_clean_english_query(query), f"junk survived: {query!r}"


@pytest.mark.parametrize(
    "query",
    [
        "send and receive sms online free",
        "receive sms online",
        "twilio vs infobip",
        "07770 area code",
        "or in a url query",  # 'or' lowercase inside words must NOT trigger
    ],
)
def test_legitimate_queries_survive_the_scrubber(query):
    assert is_clean_english_query(query), f"false positive on: {query!r}"


def test_dutch_route_query_is_flagged_non_english():
    assert is_probably_non_english("internationale landekoder telefon")
    assert not is_probably_non_english("receive sms online free")


def test_scrubber_bounds():
    assert not is_clean_english_query("ab")  # too short
    assert not is_clean_english_query(" ".join(["word"] * 11))  # too long
    assert not is_clean_english_query("смс онлайн бесплатно")  # non-ASCII


# ------------------------------------------------------- 2. pre-flight hygiene


def _enqueue(conn, rows):
    enqueue_tasks(conn, rows)
    conn.commit()
    return [
        r[0] for r in conn.execute("SELECT id FROM atomic_task_backlog ORDER BY id")
    ]


def test_preflight_rejects_junk_and_graduates_covered_tasks(conn):
    ids = _enqueue(
        conn,
        [
            {
                "page": "https://smsriver.com/a/",
                "query": "-site:x.com telnyx",
                "action_code": "INJECT_EXACT_TITLE_AND_H2",
                "file_target": "t/a.html",
            },
            {
                "page": "https://smsriver.com/verify/paypal/",
                "query": "paypal sms integration",
                "action_code": "INJECT_EXACT_TITLE_AND_H2",
                "file_target": "t/p.html",
            },
            {
                "page": "https://smsriver.com/b/",
                "query": "clean striking distance query",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "file_target": "t/b.html",
            },
        ],
    )
    report = preflight_hygiene(
        conn,
        route_intent_map={
            "https://smsriver.com/verify/paypal/": "PayPal SMS Integration: codes on public lines"
        },
    )
    statuses = {
        r[0]: r[1] for r in conn.execute("SELECT id, status FROM atomic_task_backlog")
    }
    assert report["rejected"] == 1
    assert statuses[ids[0]] == "REJECTED"
    assert report["graduated"] == 1
    assert statuses[ids[1]] == "SHIPPED"
    assert statuses[ids[2]] == "PENDING"  # clean + uncovered stays leasable


def test_preflight_graduation_requires_full_token_coverage(conn):
    _enqueue(
        conn,
        [
            {
                "page": "https://smsriver.com/x/",
                "query": "paypal sms integration",
                "action_code": "INJECT_EXACT_H2_AND_TITLE",
                "file_target": "t/x.html",
            }
        ],
    )
    preflight_hygiene(conn, route_intent_map={"https://smsriver.com/x/": "PayPal SMS"})
    status = conn.execute("SELECT status FROM atomic_task_backlog").fetchone()[0]
    assert status == "PENDING", "partial token coverage must NOT graduate"


def test_preflight_respects_locked_prefixes_and_intent_cap(conn):
    ids = _enqueue(
        conn,
        [
            {
                "page": "https://smsriver.com/country-codes/",
                "query": "0783 which network",
                "action_code": "INJECT_EXACT_TITLE_AND_H2",
                "file_target": "templates/smspool/country_codes_hub.html",
            },
            # 3rd intent task for the same page -> exceeds the per-URL cap
            # (distinct action codes: the cursor dedupes one-open-task per
            # page+action_code, so cap pressure must come from different codes)
            {
                "page": "https://smsriver.com/y/",
                "query": "intent one",
                "action_code": "INJECT_EXACT_TITLE_AND_H2",
                "file_target": "t/y1.html",
            },
            {
                "page": "https://smsriver.com/y/",
                "query": "intent two",
                "action_code": "INJECT_EXACT_H2_AND_TITLE",
                "file_target": "t/y2.html",
            },
            {
                "page": "https://smsriver.com/y/",
                "query": "intent three",
                "action_code": "INJECT_PAA_SEMANTIC_SECTIONS",
                "file_target": "t/y3.html",
            },
        ],
    )
    report = preflight_hygiene(
        conn,
        route_intent_map={},
        locked_path_prefixes=(
            "/country-codes/",
            "templates/smspool/country_codes_hub.html",
        ),
        max_intent_tasks_per_page=2,
    )
    statuses = {
        r[0]: r[1] for r in conn.execute("SELECT id, status FROM atomic_task_backlog")
    }
    assert report["locked"] == 1
    assert (
        statuses[ids[0]] == "PENDING"
    )  # locked tasks stay PENDING (agent-owned), not leased
    assert report["intent_capped"] == 1
    assert statuses[ids[3]] == "PENDING"
    assert statuses[ids[1]] == "PENDING" and statuses[ids[2]] == "PENDING"


def test_rejected_tasks_never_reenqueue(conn):
    ids = _enqueue(
        conn,
        [
            {
                "page": "https://smsriver.com/j/",
                "query": "site:smsriver.com junk",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "file_target": "t/j.html",
            }
        ],
    )
    preflight_hygiene(conn, route_intent_map={})
    assert (
        conn.execute(
            "SELECT status FROM atomic_task_backlog WHERE id=?", (ids[0],)
        ).fetchone()[0]
        == "REJECTED"
    )
    added = enqueue_tasks(
        conn,
        [
            {
                "page": "https://smsriver.com/j/",
                "query": "site:smsriver.com junk",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "file_target": "t/j.html",
            }
        ],
    )
    assert added == 0, "REJECTED is terminal: junk must never re-enter the cursor"


# ---------------------------------------------------------- 3. type-cap leasing


def test_lease_type_caps_force_task_diversity(conn):
    rows = []
    for i in range(6):
        rows.append(
            {
                "page": f"https://smsriver.com/inject/{i}/",
                "query": f"q inject {i}",
                "action_code": "INJECT_EXACT_TITLE_AND_H2",
                "file_target": f"t/i{i}.html",
            }
        )
    for i in range(6):
        rows.append(
            {
                "page": f"https://smsriver.com/table/{i}/",
                "query": f"q table {i}",
                "action_code": "ADD_D1_SPEC_COMPARISON_TABLE",
                "file_target": f"t/t{i}.html",
            }
        )
    for i in range(6):
        rows.append(
            {
                "page": f"https://smsriver.com/links/{i}/",
                "query": f"q links {i}",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "file_target": f"t/l{i}.html",
            }
        )
    enqueue_tasks(conn, rows)
    conn.commit()

    leased = lease_tasks(
        conn,
        limit=30,
        now=datetime.now(timezone.utc),
        type_caps={
            "INJECT_EXACT_TITLE_AND_H2": 2,
            "ADD_D1_SPEC_COMPARISON_TABLE": 2,
            "BOOST_CLUSTER_CROSS_LINKS": 2,
        },
    )
    from collections import Counter

    counts = Counter(t["action_code"] for t in leased)
    assert counts == {
        "INJECT_EXACT_TITLE_AND_H2": 2,
        "ADD_D1_SPEC_COMPARISON_TABLE": 2,
        "BOOST_CLUSTER_CROSS_LINKS": 2,
    }


def test_default_type_caps_reflect_the_wave62_split():
    assert DEFAULT_TYPE_CAPS["ADD_D1_SPEC_COMPARISON_TABLE"] == 8
    assert DEFAULT_TYPE_CAPS["OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA"] == 6
    # the inlink family shares the 8-slot slice across its two codes
    assert (
        DEFAULT_TYPE_CAPS["BOOST_CLUSTER_CROSS_LINKS"]
        + DEFAULT_TYPE_CAPS["STRENGTHEN_HUB_INTERNAL_LINKS"]
    ) == 8
    # the title/H2 family shares the 5-slot slice
    assert (
        DEFAULT_TYPE_CAPS["INJECT_EXACT_TITLE_AND_H2"]
        + DEFAULT_TYPE_CAPS["INJECT_EXACT_H2_AND_TITLE"]
    ) == 5
    assert DEFAULT_TYPE_CAPS["CREATE_PROGRAMMATIC_ROUTE"] == 3


def test_type_caps_combine_with_family_caps(conn):
    rows = [
        {
            "page": f"https://smsriver.com/n/{i}/",
            "query": f"q {i}",
            "action_code": "ADD_D1_SPEC_COMPARISON_TABLE",
            "file_target": f"t/n{i}.html",
        }
        for i in range(5)
    ]
    enqueue_tasks(conn, rows)
    conn.commit()
    leased = lease_tasks(
        conn,
        limit=10,
        now=datetime.now(timezone.utc),
        family_caps={"n": 2},
        default_family_cap=10,
        type_caps={"ADD_D1_SPEC_COMPARISON_TABLE": 8},
    )
    assert len(leased) == 2, "family cap must still bind inside the type quota"


# ------------------------------------------------------- 4. worktree lock registry


def test_worktree_lock_registry_lifecycle(tmp_path: Path):
    registry = tmp_path / "worktree_locks.json"
    pid = os.getpid()
    register_worktree_locks(
        ["/country-codes/", "templates/smspool/country_codes_hub.html"],
        agent_id="wave62-test",
        registry_path=registry,
        pid=pid,
    )
    prefixes = active_locked_prefixes(registry_path=registry)
    assert "/country-codes/" in prefixes
    assert "templates/smspool/country_codes_hub.html" in prefixes

    # a DEAD pid must expire immediately
    register_worktree_locks(
        ["/articles/"], agent_id="dead-agent", registry_path=registry, pid=999999999
    )
    assert "/articles/" not in active_locked_prefixes(registry_path=registry)

    # heartbeat TTL expiry
    register_worktree_locks(
        ["/stale/"], agent_id="old-agent", registry_path=registry, pid=pid
    )
    data = json.loads(registry.read_text())
    stale_entry = next(e for e in data["locks"] if e["agent_id"] == "old-agent")
    stale_entry["heartbeat"] = (
        datetime.now(timezone.utc) - timedelta(hours=3)
    ).isoformat()
    registry.write_text(json.dumps(data))
    assert "/stale/" not in active_locked_prefixes(registry_path=registry)

    release_worktree_locks("wave62-test", registry_path=registry)
    assert active_locked_prefixes(registry_path=registry) == ()


def test_release_deferred_leases_on_closeout(conn):
    enqueue_tasks(
        conn,
        [
            {
                "page": "https://smsriver.com/d/",
                "query": "deferred query",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "file_target": "t/d.html",
            }
        ],
    )
    conn.commit()
    leased = lease_tasks(conn, limit=5, now=datetime.now(timezone.utc))
    assert leased
    release_deferred_leases_on_closeout(conn, [leased[0]["id"]])
    status = conn.execute(
        "SELECT status FROM atomic_task_backlog WHERE id=?", (leased[0]["id"],)
    ).fetchone()[0]
    assert status == "PENDING"
    assert pending_count(conn) == 1


def test_fast_path_preflight_does_not_break_cursor_lease(tmp_path: Path, conn):
    """End-to-end: junk is rejected and clean tasks still lease in one pass."""
    rows = [
        {
            "page": "https://smsriver.com/j/",
            "query": "-site:x.com junk",
            "action_code": "BOOST_CLUSTER_CROSS_LINKS",
            "file_target": "t/j.html",
        },
        {
            "page": "https://smsriver.com/k/",
            "query": "clean leasable query",
            "action_code": "BOOST_CLUSTER_CROSS_LINKS",
            "file_target": "t/k.html",
        },
    ]
    enqueue_tasks(conn, rows)
    conn.commit()
    preflight_hygiene(conn, route_intent_map={})
    leased = lease_tasks(conn, limit=5, now=datetime.now(timezone.utc))
    assert [t["page"] for t in leased] == ["https://smsriver.com/k/"]


def test_score_backlog_fast_path_runs_preflight(tmp_path: Path):
    """CLI contract: the <1s cursor lease path scrubs junk before leasing."""
    from score_backlog import main as score_main

    db = tmp_path / "state.db"
    conn = connect_state_db(str(db))
    enqueue_tasks(
        conn,
        [
            {
                "page": "https://smsriver.com/j/",
                "query": "site:smsriver.com junk",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "file_target": "t/j.html",
            },
            {
                "page": "https://smsriver.com/k/",
                "query": "clean leasable query",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "file_target": "t/k.html",
            },
        ],
    )
    conn.commit()
    conn.close()
    out = tmp_path / "queue.json"
    rc = score_main(
        [
            "--state-db",
            str(db),
            "--lease-size",
            "1",
            "--replenish-below",
            "1",
            "--output",
            str(out),
            "--intent-map",
            "",
            "--no-lock-registry",
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["fast_path"] is True
    assert payload["hygiene"]["rejected"] == 1
    assert [t["page"] for t in payload["leased"]] == ["https://smsriver.com/k/"]
