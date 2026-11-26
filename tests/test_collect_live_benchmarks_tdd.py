"""Track 2 collector: real varying fields or no contract."""

from __future__ import annotations

import pytest
from collect_live_benchmarks import collect
from seo_factory import validate_page_contract


def _page(name: str, index: int) -> str:
    return f"""
    <html><head><title>{name} Server Benchmarks: Players, Ping, Uptime</title></head>
    <body><main><div data-role="game-benchmark">
      <span data-metric="online_count">{index + 3}</span>
      <span data-metric="total_players">{index * 17}</span>
      <span data-metric="avg_players">{index}.5</span>
      <span data-metric="median_ping">{index * 11} ms</span>
      <p>{name} unique observation {index}: map-{index} has {index + 3} servers;
      leader-{index} reports {index * 17} players.
      {(" ".join(f"{name.lower()}-token-{index}-{i}" for i in range(20)))}</p>
      <table><tr><td>map-{index}</td><td>{index + 3}</td></tr></table>
    </div></main></body></html>
    """


def test_collector_emits_only_valid_cross_sibling_contracts(monkeypatch):
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    urls = [f"https://example.com/benchmarks/{name.lower()}/" for name in names]

    def fake_fetch(url: str, timeout: int = 20) -> str:
        if url.endswith("sitemap.xml"):
            return (
                "<urlset>"
                + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
                + "</urlset>"
            )
        index = names.index(url.split("/")[-2].title())
        return _page(names[index], index)

    monkeypatch.setattr("collect_live_benchmarks._fetch", fake_fetch)
    contracts = collect("https://example.com/sitemap.xml", limit=5)

    assert len(contracts) == 5
    for contract in contracts:
        contract["cluster_id"] = "cl_test"
        assert contract["unique_data_fields"] >= 3
        assert contract["stripped_overlap_score"] <= 0.45
        result = validate_page_contract(contract)
        assert result["valid"] is True, (result, contract["stripped_overlap_score"])


def test_collector_refuses_constant_siblings(monkeypatch):
    def fake_fetch(url: str, timeout: int = 20) -> str:
        if url.endswith("sitemap.xml"):
            return "".join(
                f"<url><loc>https://example.com/benchmarks/{name}/</loc></url>"
                for name in ("a", "b", "c", "d", "e")
            )
        return '<div data-role="game-benchmark"><span data-metric="online_count">3</span></div>'

    monkeypatch.setattr("collect_live_benchmarks._fetch", fake_fetch)
    with pytest.raises(RuntimeError, match="varying metrics"):
        collect("https://example.com/sitemap.xml", limit=5)
