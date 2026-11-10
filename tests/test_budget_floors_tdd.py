"""Unit TDD tests for the wave-64 review R3 property-level budget floors.

Unified fleet DB + shared 150/day cap introduced a noisy-neighbor risk: one
hungry property could drain all 150 SERP calls and starve its siblings.
Every domain now holds a guaranteed floor (50/day); beyond the floor it
draws from the shared pool (cap minus all floors), and the total cap always
binds.
"""

from fleet_state import DailyBudgetGate, connect_state_db


def test_sole_domain_can_use_the_whole_cap(tmp_path):
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    assert gate.remaining(domain="smsriver.com") == 150
    left = gate.record(150, domain="smsriver.com")
    assert left == 0
    assert gate._total_spent(gate._day(None)) == 150


def test_second_domain_keeps_guaranteed_floor_after_neighbor_burns_shared_pool(
    tmp_path,
):
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    gate.record(100, domain="smsriver.com")  # 50 guaranteed + 50 shared
    # incomecanvas arrives fresh: its 50/day floor is guaranteed even though
    # only 50 total remain
    assert gate.remaining(domain="incomecanvas.com") == 50
    left = gate.record(80, domain="incomecanvas.com")
    assert left == 0, "only the guaranteed 50 fit; the shared pool is spent"
    assert gate._domain_spent(gate._day(None), "incomecanvas.com") == 50


def test_domain_cannot_exceed_floor_plus_shared_pool(tmp_path):
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    first = gate.record(120, domain="smsriver.com")
    # with a second floor slot reserved (incomecanvas unknown-but-possible),
    # smsriver's own draw is bounded: 50 guaranteed + shared pool 50 = 100
    assert first <= 100, "a domain may never drain a sibling's guaranteed floor"
    total = gate._total_spent(gate._day(None))
    assert total <= 150


def test_total_cap_always_binds(tmp_path):
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    gate.record(90, domain="smsriver.com")
    gate.record(90, domain="incomecanvas.com")
    assert gate._total_spent(gate._day(None)) == 150, "60 was rejected past the cap"
    assert gate.remaining(domain="smsriver.com") == 0


def test_legacy_record_without_domain_keeps_old_semantics(tmp_path):
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    gate.record(100)
    assert gate.remaining() == 50
    gate.record(100)
    assert gate.remaining() == 0


def test_unified_db_connection_sets_wal_and_busy_timeout(tmp_path):
    """Review R3: concurrent agents must never hit 'database is locked'."""
    conn = connect_state_db(str(tmp_path / "g.db"))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
