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
    gate.record(100, domain="smsriver.com")  # 30 guaranteed + 70 shared
    # incomecanvas arrives fresh: its dynamic floor (min(30, 150//2) = 30)
    # is guaranteed even though only 50 total remain
    assert gate.remaining(domain="incomecanvas.com") == 50
    left = gate.record(80, domain="incomecanvas.com")
    assert left == 0, "only the guaranteed 30 + 20 shared fit"
    assert gate._domain_spent(gate._day(None), "incomecanvas.com") == 50


def test_big_first_draw_still_leaves_late_domain_its_floor(tmp_path):
    """The starvation invariant: however much early domains drew, a domain
    registering late keeps its guaranteed floor (bounded by the cap)."""
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    gate.record(120, domain="smsriver.com")
    # incomecanvas arrives late: floor 30, total_left 30 -> exactly its floor
    assert gate.remaining(domain="incomecanvas.com") == 30
    left = gate.record(80, domain="incomecanvas.com")
    assert left == 0
    assert gate._domain_spent(gate._day(None), "incomecanvas.com") == 30


def test_five_domains_each_keep_a_functional_floor(tmp_path):
    """Review follow-up math trap: a STATIC 50/day floor x 5 domains = 250
    > 150 cap, so domain #4 starved to 0 (static model: D1-D3 drew 150 and
    the cap closed). Dynamic floors (min(30, cap//N)) never sum past the
    cap: five domains x 30 = 150, every domain draws its full floor."""
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    domains = [
        "smsriver.com",
        "incomecanvas.com",
        "openfileconverter.com",
        "figiva.com",
        "crewelo.com",
    ]
    for i, dom in enumerate(domains):
        left = gate.record(30, domain=dom)
        assert gate._domain_spent(gate._day(None), dom) == 30, (
            f"domain {dom} (arriving #{i + 1}) starved below its floor"
        )
        if i < 4:
            assert left > 0, f"cap closed before {dom} drew its floor"
    assert gate._total_spent(gate._day(None)) == 150


def test_dynamic_floor_shrinks_gracefully_at_fleet_scale(tmp_path):
    gate = DailyBudgetGate(str(tmp_path / "g.db"), daily_cap=150)
    assert gate._dynamic_floor(1) == 35, "min(max_floor, cap//1)"
    assert gate._dynamic_floor(2) == 35
    assert gate._dynamic_floor(5) == 30, "min(35, 150//5)"
    assert gate._dynamic_floor(13) == 11, "150 // 13 -> 11/day per domain"
    for n in range(1, 26):
        assert gate._dynamic_floor(n) * n <= 150, f"floors oversubscribe at N={n}"


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
