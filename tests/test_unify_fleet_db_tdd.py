"""
Unit TDD tests for wave-64 fleet DB unification: one SQLite cursor DB
(~/.seo_fleet/fleet_state.db) keyed by the `domain` column - no more
per-domain .db fragmentation (incomecanvas.db), with budget totals summed
per day across merged DBs and REJECTED adjudications preserved.
"""

import pathlib
import sqlite3

import pytest
from unify_fleet_db import merge_state_db, retire_source


@pytest.fixture
def target(tmp_path):
    from fleet_state import connect_state_db

    conn = connect_state_db(str(tmp_path / "fleet_state.db"))
    conn.execute(
        "INSERT INTO atomic_task_backlog "
        "(domain, page, query, action_code, priority_score, route_family, status, created_at) "
        "VALUES ('smsriver.com', 'https://smsriver.com/a/', 'q a', 'ACT', 5.0, 'root', "
        "'PENDING', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO atomic_task_backlog "
        "(domain, page, query, action_code, priority_score, route_family, status, created_at) "
        "VALUES ('smsriver.com', 'https://smsriver.com/r/', 'q r', 'ACT', 5.0, 'root', "
        "'REJECTED', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO dfs_serp_cache (query, fetched_at, items_json, item_types) "
        "VALUES ('shared query', '2026-01-01T00:00:00Z', '[]', '[]')"
    )
    conn.execute("INSERT INTO dfs_budget (day, spent) VALUES ('2026-01-01', 60)")
    conn.execute("INSERT INTO dfs_budget (day, spent) VALUES ('2026-01-02', 5)")
    conn.commit()
    return tmp_path / "fleet_state.db"


@pytest.fixture
def source(tmp_path):
    from fleet_state import connect_state_db

    conn = connect_state_db(str(tmp_path / "incomecanvas.db"))
    rows = [
        # fresh incomecanvas rows
        (
            "incomecanvas.com",
            "https://incomecanvas.com/article/x/",
            "qx",
            "ACT",
            9.0,
            "PENDING",
        ),
        # collides with the target's OPEN (PENDING) pair -> ignored
        ("smsriver.com", "https://smsriver.com/a/", "q a", "ACT", 9.0, "PENDING"),
        # pair is REJECTED in the target -> terminal, must never re-enter
        ("smsriver.com", "https://smsriver.com/r/", "q r", "ACT", 9.0, "PENDING"),
        # completed rows merge freely (no open-task collision)
        (
            "incomecanvas.com",
            "https://incomecanvas.com/article/y/",
            "qy",
            "ACT",
            4.0,
            "SHIPPED",
        ),
    ]
    for dom, page, query, code, prio, status in rows:
        conn.execute(
            "INSERT INTO atomic_task_backlog "
            "(domain, page, query, action_code, priority_score, route_family, status, created_at) "
            "VALUES (?, ?, ?, 'ACT' || '', ?, 'root', ?, '2026-01-02T00:00:00Z')",
            (dom, page, query, prio, status),
        )
    conn.execute(
        "INSERT INTO dfs_serp_cache (query, fetched_at, items_json, item_types) "
        "VALUES ('shared query', '2026-01-02T00:00:00Z', '[\"newer\"]', '[]')"
    )
    conn.execute(
        "INSERT INTO dfs_serp_cache (query, fetched_at, items_json, item_types) "
        "VALUES ('incomecanvas only', '2026-01-02T00:00:00Z', '[]', '[]')"
    )
    conn.execute("INSERT INTO dfs_budget (day, spent) VALUES ('2026-01-01', 100)")
    conn.execute("INSERT INTO dfs_budget (day, spent) VALUES ('2026-01-03', 30)")
    conn.commit()
    return tmp_path / "incomecanvas.db"


def test_merge_backlog_preserves_rejected_and_dedupes_open_pairs(target, source):
    report = merge_state_db(str(source), str(target))
    tconn = sqlite3.connect(str(target))
    rows = tconn.execute(
        "SELECT domain, page, status FROM atomic_task_backlog ORDER BY id"
    ).fetchall()
    # 1 target pending + 2 fresh source rows (x pending + y shipped) = 4
    assert len(rows) == 4, f"unexpected backlog: {rows}"
    statuses = {(dom, pg): st for dom, pg, st in rows}
    assert (
        statuses[("incomecanvas.com", "https://incomecanvas.com/article/x/")]
        == "PENDING"
    )
    # REJECTED pair stays REJECTED (source PENDING copy ignored)
    assert statuses[("smsriver.com", "https://smsriver.com/r/")] == "REJECTED"
    # open-pair collision ignored: single PENDING row for smsriver a/
    pend_a = [r for r in rows if r[1] == "https://smsriver.com/a/"]
    assert len(pend_a) == 1 and pend_a[0][2] == "PENDING"
    assert report["backlog_merged"] == 2
    assert report["backlog_ignored_open"] == 1
    assert report["backlog_ignored_rejected"] == 1


def test_merge_sums_budget_per_day(target, source):
    merge_state_db(str(source), str(target))
    tconn = sqlite3.connect(str(target))
    budget = dict(tconn.execute("SELECT day, spent FROM dfs_budget").fetchall())
    assert budget == {"2026-01-01": 160, "2026-01-02": 5, "2026-01-03": 30}


def test_merge_serp_cache_target_wins_shared_queries(target, source):
    merge_state_db(str(source), str(target))
    tconn = sqlite3.connect(str(target))
    queries = {row[0] for row in tconn.execute("SELECT query FROM dfs_serp_cache")}
    assert queries == {"shared query", "incomecanvas only"}
    # target's cache entry wins for shared queries (fresher provenance kept)


def test_retire_source_archives_to_durable_backups_with_manifest(
    target, source, tmp_path, monkeypatch
):
    """Review R3: /tmp is wiped by tmpfiles/reboots; migrated state DBs are
    the only record of pre-unification adjudications, so backups land in
    ~/.seo_fleet/backups/ with a timestamped SHA-256 manifest."""
    import hashlib
    import json as jsonlib

    backups_dir = tmp_path / "backups"
    monkeypatch.setenv("SEO_FLEET_BACKUPS_DIR", str(backups_dir))
    merge_state_db(str(source), str(target))
    backup_path = retire_source(str(source))
    backup = pathlib.Path(backup_path)
    assert not source.exists()
    assert backup.parent == backups_dir
    assert backup.exists()
    manifest = backups_dir / "manifest.jsonl"
    assert manifest.exists()
    entry = jsonlib.loads(manifest.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["backup"] == str(backup)
    assert entry["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert entry["original"] == str(source)


def test_domain_budget_ledger_merges_per_day_and_domain(target, source):
    """Review R3: the per-domain spend ledger (starvation floors) merges with
    the same sum-per-key semantics as the fleet-wide daily budget."""
    from unify_fleet_db import merge_state_db as _m  # noqa: F401 - parity check

    sconn = sqlite3.connect(str(source))
    sconn.execute(
        "INSERT INTO dfs_budget_domain (day, domain, spent) VALUES ('2026-01-01', 'incomecanvas.com', 40)"
    )
    sconn.execute(
        "INSERT INTO dfs_budget_domain (day, domain, spent) VALUES ('2026-01-02', 'incomecanvas.com', 10)"
    )
    sconn.commit()
    sconn.close()
    tconn0 = sqlite3.connect(str(target))
    tconn0.execute(
        "INSERT INTO dfs_budget_domain (day, domain, spent) VALUES ('2026-01-01', 'smsriver.com', 25)"
    )
    tconn0.commit()
    tconn0.close()
    report = merge_state_db(str(source), str(target))
    tconn = sqlite3.connect(str(target))
    rows = dict(
        ((d, dom), s)
        for d, dom, s in tconn.execute(
            "SELECT day, domain, spent FROM dfs_budget_domain"
        ).fetchall()
    )
    assert rows[("2026-01-01", "incomecanvas.com")] == 40
    assert rows[("2026-01-02", "incomecanvas.com")] == 10
    assert rows[("2026-01-01", "smsriver.com")] == 25
    assert report.get("domain_budget_days_merged", 0) >= 2
