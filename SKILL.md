---
name: improve-seo-with-data
description: >-
  Use this skill whenever you need to audit, diagnose, optimize, or scale a website's SEO, organic search visibility, or AI search footprint using real data. Triggers include "improve SEO", "SEO audit", "Search Console data", "ranking drop", "striking distance keywords", "CTR optimization", "cannibalization", "sitemap check", "robots.txt indexing", "programmatic SEO audit", "GEO / AI search readiness", "llms.txt", or schema.org structured data. Connects to the SEO MCP server and local verification engines to turn raw metrics into actionable, evidence-backed code changes.
---

# improve-seo-with-data

The authoritative, data-first SEO engineering skill for **Antigravity CLI (`agy`)**, **Claude Code**, and autonomous coding agents.

This skill eliminates speculative "best practices" and guesswork. Every recommendation and code change is grounded in authentic, first-party data: **Google Search Console (GSC)** performance, **technical crawler logs**, **live SERP snapshots**, and **AI search citations (GEO)**.

---

## Operating Invariants

1. **Evidence Before Action:** Never edit a title, canonical tag, or robots.txt file without first inspecting the data report.
2. **Never Promise Specific Ranks:** Search algorithms and competitive landscapes fluctuate. Optimize for crawlability, user intent, click-through-rate (CTR), and topical depth—never guarantee a specific ranking.
3. **Crawl Budget & Parameter Defense:** Guard crawler bandwidth by ensuring faceted query parameters (`?sort=`, `?filter=`, `?page=`) are governed by `Disallow: /*?*` in `robots.txt` and marked with `rel="nofollow"` on internal links, while keeping canonical URLs strictly static.
4. **Programmatic Utility Over Thin Slop:** Programmatic SEO (pSEO) pages must deliver authentic, interactive utility (live calculators, converters, lookups, comparison matrices)—never low-value doorway text.
5. **Generative Engine Optimization (GEO):** Ensure machine-readable documentation exists via [`llms.txt`](./templates/llms.txt), validated Schema.org JSON-LD is injected, and robots policies allow AI crawlers (`GPTBot`, `ClaudeBot`, `PerplexityBot`).
6. **Closed-Loop Verification:** Always re-run the matching audit report or crawler after implementing code changes to verify 0 regressions.

---

## 5-Phase Autonomous SEO Engine

```
[ Phase 1: Data Source & MCP Connect ]
         │ (GSC OAuth / Service Account / Local Cache)
         ▼
[ Phase 2: Technical & Crawl Health Audit ]
         │ (site-crawl, canonicals, robots.txt, Core Web Vitals)
         ▼
[ Phase 3: Demand & Performance Analysis ]
         │ (striking distance, CTR quick-wins, cannibalization, decay)
         ▼
[ Phase 4: Generative Engine Optimization (GEO) ]
         │ (llms.txt, Schema.org JSON-LD, agent readiness)
         ▼
[ Phase 5: Code Remediation & Verification Loop ]
           (templates, metadata, internal links, re-audit)
```

---

## Phase 1: Connection & MCP Health Verification

Before running reports, verify that the **`seo`** MCP server and CLI are connected and functioning.

### 1.1 Verify MCP Availability in Antigravity
The `seo` MCP server provides 74 structured reports. Test the connection:
```python
# Call via Antigravity MCP tool
call_mcp_tool(ServerName="seo", ToolName="seo_list_reports", Arguments={})
```

Alternatively, run the automated verification script:
```bash
python3 scripts/verify_mcp.py
```

### 1.2 Check CLI & Auth Status
Run the doctor command to inspect local database cache and Google credentials:
```bash
seo doctor --json
```

- When auditing a **live or local site without Search Console access**, crawl reports work out-of-the-box (`seo report --url <URL>`).
- When Search Console is connected, pass `--site sc-domain:<domain>` or `--site https://<domain>/`.

---

## Phase 2: Technical & Crawl Health Audit

Technical integrity is the foundation of all organic indexing. A page blocked by a misplaced `noindex`, broken canonical, or redirect chain will never rank.

### 2.1 Run Full Site or Single URL Audit
To audit a site and capture high-priority technical findings:
```bash
# Full technical crawl (zero third-party dependencies required)
seo report --url https://example.com --actions-only --json > /tmp/seo_audit.json

# Or audit specific high-priority URLs:
python3 scripts/run_audit.py --url https://example.com
```

With MCP:
```python
call_mcp_tool(
    ServerName="seo",
    ToolName="seo_run_report",
    Arguments={
        "id": "site-crawl",
        "params": {"url": "https://example.com", "maxPages": 250}
    }
)
```

### 2.2 Inspect Critical Technical Signals
1. **HTTP Status Codes:** Identify 404s, 500s, and 301/302 redirect hops using the `redirect-trace` report.
2. **Canonical Consistency:** Ensure `canonical` tags are self-referential on primary pages and never point to redirected or 404 targets.
3. **Indexation Guards:** Verify `<meta name="robots" content="index, follow">` is present on public pages and `noindex, nofollow` is restricted to administrative/auth routes.
4. **Facet Crawl Budget Shield:** Ensure query parameter facets are prevented from creating infinite duplicate URLs:
   ```txt
   # robots.txt standard
   User-agent: *
   Disallow: /*?*
   Disallow: /admin/
   Disallow: /api/
   Sitemap: https://example.com/sitemap.xml
   ```

---

## Phase 3: Demand & Performance Analysis (Search Console)

Translate first-party Search Console impressions and click metrics into direct ranking gains.

Run the automated GSC performance analyzer:
```bash
python3 scripts/gsc_analyzer.py --site sc-domain:example.com
```

### 3.1 Striking Distance Keywords (Positions 11 to 20)
Pages averaging positions 11 to 20 are on Google's Page 2. A modest relevance boost can push them to Page 1, creating exponential click gains.

- **MCP Report:** `striking-distance`
  ```python
  call_mcp_tool(
      ServerName="seo",
      ToolName="seo_run_report",
      Arguments={
          "id": "striking-distance",
          "params": {"site": "sc-domain:example.com", "minImpressions": 100}
      }
  )
  ```
- **Remediation Action:**
  - Inject the exact query phrasing into `<h2>` subheadings or opening paragraphs.
  - Add contextual internal links with matching anchor text from high-authority authority pages (e.g. homepage, category hubs).
  - Expand the section to directly answer secondary intent questions.

### 3.2 Low-CTR Quick Wins (High Impressions, Low Clicks)
Pages ranking in positions 1 to 5 with click-through-rates significantly below industry benchmarks (e.g. <3% on Pos 2-3) suffer from weak titles or snippets.

- **MCP Report:** `quick-wins`
- **Remediation Action:**
  - Rewrite `<title>` tags to include high-converting intent modifiers (`Best`, `Free`, `Calculator`, `Online`, Current Year).
  - Add emotional or utilitarian hooks in `<meta name="description">`.
  - Add Schema.org `FAQPage` or `SoftwareApplication` markup to trigger rich snippet real estate in SERPs.

### 3.3 Query Cannibalization
When multiple URLs rank for the identical query, Google divides page authority, causing both to underperform.

- **MCP Report:** `cannibalisation`
- **Remediation Action:**
  - Determine the single canonical owner for the topic.
  - Consolidate thin competing pages into the primary authority URL via 301 redirect or explicit canonical link.
  - Differentiate secondary pages by reframing their focus to distinct sub-topics.

### 3.4 Decaying Content Refresh
Identify pages whose 90-day search traffic has dropped $>20\%$ compared to the previous period.

- **MCP Report:** `decaying-pages`
- **Remediation Action:**
  - Refresh outdated data, statistics, and broken outbound references.
  - Add updated sections addressing current market changes.

---

## Phase 4: Generative Engine Optimization (GEO) & AI Search Readiness

Modern SEO requires optimizing not just for traditional crawler bots, but for LLM-powered answer engines: **Perplexity**, **ChatGPT Search**, **Claude**, and **Google AI Overviews**.

Run the AI readiness evaluator:
```bash
python3 scripts/geo_evaluator.py --url https://example.com
```

### 4.1 Deploy `llms.txt` and `llms-full.txt`
Place a standardized [`llms.txt`](./templates/llms.txt) in the site root (`/llms.txt`). This provides an authoritative, structured index for AI agents crawling the site.
- Include core company value proposition.
- Outline key products, tools, and programmatic endpoints.
- Provide clean links to full documentation and markdown resources.

### 4.2 Verify Robots.txt AI Bot Permissions
Ensure your `robots.txt` explicitly allows or configures access for AI user agents:
```txt
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /
```

### 4.3 Schema.org JSON-LD Structured Data
Inject rich JSON-LD markup on every template. See [`templates/schema_org.json`](./templates/schema_org.json) for:
- `Organization` & `WebSite` (with Sitelinks Searchbox) on the homepage.
- `SoftwareApplication` or `Product` on SaaS landing pages.
- `FAQPage` on landing and comparison pages.
- `BreadcrumbList` across all hierarchical routes.

---

## Phase 5: Code Remediation & Verification Loop

Once findings are identified, execute precise code modifications across the application layers:

### Step 1: Data Contracts & Templates
Update HTML templates, Django views, or frontend components to fix meta tags, headings, schema markup, or internal links.
- Preserve semantic HTML (`<main>`, `<article>`, `<header>`, `<footer>`).
- Ensure all images have descriptive `alt` tags and explicit dimensions (`width`, `height`).
- Replace Unicode emojis with clean IconKit vector SVGs (`aria-hidden="true"`).

### Step 2: Local Verification & Build Check
Before deploying or committing:
1. Verify template syntax and rendering:
   ```bash
   python manage.py check --deploy
   ```
2. Re-run local crawler against the development build:
   ```bash
   seo report --url http://127.0.0.1:8000 --actions-only --json
   ```
3. Confirm that previously flagged defects are resolved (`fixed`).

---

## Tool & Script Reference

| Tool / Script | Purpose |
|---------------|---------|
| [`scripts/verify_mcp.py`](./scripts/verify_mcp.py) | Verifies MCP server connection, available reports, and credentials. |
| [`scripts/run_audit.py`](./scripts/run_audit.py) | Runs technical crawl and single-page audits with action item extraction. |
| [`scripts/gsc_analyzer.py`](./scripts/gsc_analyzer.py) | Analyzes Search Console for striking distance, quick wins, and decay. |
| [`scripts/geo_evaluator.py`](./scripts/geo_evaluator.py) | Validates AI readiness, `llms.txt`, and structured data. |
| [`references/mcp_catalog.md`](./references/mcp_catalog.md) | Exhaustive catalog of all 74 MCP reports across 9 categories. |
| [`references/geo_playbook.md`](./references/geo_playbook.md) | Comprehensive Generative Engine Optimization guide. |
| [`references/gsc_optimization_runbook.md`](./references/gsc_optimization_runbook.md) | Query clustering, striking distance, and CTR tuning manual. |
| [`templates/llms.txt`](./templates/llms.txt) | Production-ready `llms.txt` template. |
| [`templates/schema_org.json`](./templates/schema_org.json) | Tested Schema.org JSON-LD templates. |
| [`templates/audit_report_template.html`](./templates/audit_report_template.html) | Standalone, accessible client audit report template. |
