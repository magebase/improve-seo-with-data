# SEO MCP Server Report Catalog

The `seo` MCP server provides **74 structured reports** organized across **9 categories**.
Every report outputs strictly typed evidence and recommendations with clear provenance.

---

## 1. Categories Overview

| Category | Purpose | Core Reports |
|----------|---------|--------------|
| **`crawl`** | Site exploration, crawler rules, page-level technical checks, and HTML parsing. | `site-crawl`, `audit-page`, `audit-urls`, `affected-urls`, `top-fixes`, `compare-crawls`, `redirect-trace` |
| **`ai-search`** | Generative Engine Optimization (GEO), AI search citations, and agent readiness. | `ai-readiness`, `agent-readiness`, `ai-search-scorecard`, `ai-mention-research`, `ai-prompt-observations`, `ai-referrals`, `content-optimization` |
| **`diagnosis`** | Diagnosing traffic drops, rank volatility, and segment movements. | `traffic-anomaly`, `update-correlation`, `segment-impact`, `decaying-pages`, `striking-distance` |
| **`opportunities`** | High-leverage ranking opportunities, competitor gaps, and query discovery. | `competitive-opportunities`, `competitor-keyword-gap`, `query-clusters`, `page-opportunities`, `serp-results`, `cannibalisation` |
| **`workflows`** | Orchestrated multi-step workflows combining crawl and performance data. | `search-performance-overview`, `refresh-priorities`, `technical-watch`, `update-postmortem` |
| **`monitoring`** | Continuous tracking of crawl diffs, Bing Webmaster data, and server access logs. | `crawl-diff`, `bing-webmaster-overview`, `server-log-analysis`, `redirect-trace` |
| **`reporting`** | Client-ready deliverables, executive summaries, and action plans. | `report`, `monthly-report`, `narrative-report`, `monthly-action-plan`, `second-page` |
| **`experiments`** | Formulating and tracking structured SEO A/B and title/meta tests. | `experiment-design`, `measure-change` |
| **`setup`** | Verifying local cache, Google credentials, and default project profiles. | `setup-check`, `doctor` |

---

## 2. Key Report Schemas & Invocations

### `site-crawl`
Performs a lightweight sitemap pass followed by a technical crawler pass.
- **Parameters:**
  ```json
  {
    "url": "https://example.com",
    "maxPages": 250,
    "respectRobots": true
  }
  ```
- **Returns:** List of crawled URLs, status codes, title tags, canonical targets, meta robots directives, and crawl issues.

### `audit-page`
Inspects a single URL in depth.
- **Parameters:**
  ```json
  {
    "url": "https://example.com/pricing/"
  }
  ```
- **Returns:** Response headers, TTFB, H1-H6 outline, OpenGraph tags, JSON-LD structured data blocks, internal/external links count, and image alt text coverage.

### `striking-distance`
Finds queries and URL pairs averaging positions 10.1 to 20.0 (Google Page 2).
- **Parameters:**
  ```json
  {
    "site": "sc-domain:example.com",
    "minImpressions": 50,
    "limit": 25
  }
  ```
- **Action:** Add query keywords to H2s, improve internal link anchor text from high-authority pages, and expand topical depth.

### `quick-wins`
Identifies ranking positions 1 to 7 with CTR below benchmark.
- **Parameters:**
  ```json
  {
    "site": "sc-domain:example.com",
    "minImpressions": 100
  }
  ```
- **Action:** Rewrite `<title>` tags to include compelling benefit hooks, numbers, and year stamps. Add FAQ Schema.

### `cannibalisation`
Detects multiple URLs competing for the same search query.
- **Parameters:**
  ```json
  {
    "site": "sc-domain:example.com",
    "threshold": 0.2
  }
  ```
- **Action:** Consolidate competing pages via 301 redirects or establish explicit canonical ownership.

### `ai-search-scorecard`
Scores technical readiness (0-100) for Perplexity, ChatGPT, Claude, and Google AI Overviews.
- **Parameters:**
  ```json
  {
    "url": "https://example.com"
  }
  ```
- **Action:** Add `llms.txt`, ensure robots.txt permits AI user agents, and enrich Schema.org JSON-LD.

---

## 3. How to Call via Antigravity MCP

In Antigravity CLI or multi-agent conversations:

```python
# 1. Discover all reports
call_mcp_tool(
    ServerName="seo",
    ToolName="seo_list_reports",
    Arguments={}
)

# 2. Describe report schema before running
call_mcp_tool(
    ServerName="seo",
    ToolName="seo_describe_report",
    Arguments={"id": "striking-distance"}
)

# 3. Run report with bounded parameters
call_mcp_tool(
    ServerName="seo",
    ToolName="seo_run_report",
    Arguments={
        "id": "striking-distance",
        "params": {
            "site": "sc-domain:example.com",
            "minImpressions": 50
        }
    }
)
```
