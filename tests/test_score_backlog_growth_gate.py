"""A non-positive growth plan must not leave a title/CTR queue behind."""

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from score_backlog import _enforce_growth_guarantee  # noqa: E402


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_indexation_prerequisite_suppresses_title_queue(tmp_path):
    output = tmp_path / "action_queue.json"
    _write(
        output,
        {
            "queue": [{"action_code": "REWRITE_SNIPPET_AND_TOP_300PX"}],
            "leased": [{"action_code": "INJECT_EXACT_H2_AND_TITLE"}],
        },
    )

    suppressed = _enforce_growth_guarantee(
        str(output), {"guarantee": "indexation_prerequisite"}
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert suppressed == 2
    assert payload["queue"] == []
    assert payload["leased"] == []
    assert payload["suppressed_reason"] == "indexation_prerequisite"


def test_positive_growth_plan_keeps_queue(tmp_path):
    output = tmp_path / "action_queue.json"
    _write(output, {"queue": [{"action_code": "REWRITE_SNIPPET_AND_TOP_300PX"}]})

    suppressed = _enforce_growth_guarantee(
        str(output), {"guarantee": "positive_expected_click_lift"}
    )

    assert suppressed == 0
    assert json.loads(output.read_text())["queue"]
