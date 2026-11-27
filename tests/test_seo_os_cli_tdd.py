"""The unified CLI must forward stage flags to the delegated script."""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import growth_loop  # noqa: E402
import seo_os  # noqa: E402


def test_plan_forwards_domain_and_limit(monkeypatch):
    captured = {}

    def fake_main(extra):
        captured["extra"] = list(extra)
        return 0

    monkeypatch.setattr(growth_loop, "main", fake_main)

    code = seo_os.main(
        ["plan", "--domain", "smsriver.com", "--limit", "5", "--keep-urls", "keep.json"]
    )

    assert code == 0
    assert captured["extra"] == [
        "plan",
        "--domain",
        "smsriver.com",
        "--limit",
        "5",
        "--keep-urls",
        "keep.json",
    ]
