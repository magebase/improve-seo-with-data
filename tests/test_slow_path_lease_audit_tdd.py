"""
Unit TDD tests for the wave-64 slow-path lease audit fix: score_backlog's
slow path must record `leased` + `hygiene` in its output JSON exactly like
the fast path does (wave-63 gap: the executor could not see the lease).
"""

import json

import pytest

from score_backlog import merge_leased_into_output


def test_merge_leased_into_output_attaches_lease_and_hygiene(tmp_path):
    output = tmp_path / "action_queue.json"
    output.write_text(
        json.dumps({"site": "incomecanvas.com", "queue": [{"slot": 1}]}),
        encoding="utf-8",
    )
    leased = [
        {"id": 7, "page": "https://incomecanvas.com/article/x/", "action_code": "ACT"}
    ]
    hygiene = {"rejected": 1, "graduated": 0, "locked": 0, "intent_capped": 0}
    merge_leased_into_output(str(output), leased, hygiene)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["queue"] == [{"slot": 1}], "existing queue payload preserved"
    assert payload["leased"] == leased
    assert payload["hygiene"] == hygiene


def test_merge_leased_into_output_is_a_noop_without_lease(tmp_path):
    output = tmp_path / "action_queue.json"
    before = {"site": "smsriver.com"}
    output.write_text(json.dumps(before), encoding="utf-8")
    merge_leased_into_output(str(output), [], {})
    assert json.loads(output.read_text(encoding="utf-8")) == before
