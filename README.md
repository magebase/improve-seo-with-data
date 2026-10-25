# Improve SEO with Data (`improve-seo-with-data`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Antigravity Compatible](https://img.shields.io/badge/Antigravity-Skill-purple.svg)](https://github.com/magebase/improve-seo-with-data)
[![MCP Server: seo](https://img.shields.io/badge/MCP-74%20Reports-green.svg)](references/mcp_catalog.md)

Autonomous, data-driven SEO engineering, Observability, and Generative Engine Optimization (GEO) skill for **Google Antigravity CLI (`agy`)**, **Claude Code**, **Cursor**, and multi-agent developer fleets.

Governed by the **SEO Outcome Maximization Contract**: eliminates superficial "best practice" checklists and speculative keyword guessing. Every audit, diagnosis, code modification, and page generation is backed by authentic first-party data: **Google Search Console (GSC)** performance, **real user monitoring (RUM)**, **server & crawler access logs**, **live SERP rankings**, and **LLM answer engine citations**.

---

## The SEO Outcome Maximization Contract

The system optimizes strictly for **incremental organic search clicks and meaningful business conversions**, never for pages published, changes made, tests passed, or words written:

1. **Exhaustive Opportunity Discovery:** Low volume is uncertainty, not a rejection threshold. Every detected opportunity results in a concrete action, a defined diagnostic step, or an explicit evidence-backed decision to defer.
2. **Diagnose Before Choosing an Intervention:** Classify failure modes using the 8-State Page-Level Diagnostic Decision Tree before choosing code or content edits.
3. **URL Ownership Model & Anti-Cannibalization Gate:** Query clusters are mapped to intended URL owners. If an existing non-hub URL ranks $\le 15.0$, creating a new competing page is strictly forbidden; route to Track 1 existing page improvement (Recipe A).
4. **Quantified Expected Value:** Prioritize via $EV(a) = P(\text{success} \mid a) \times V(a) - Cost(a) - Risk(a)$ and Priority $P = \frac{\max(0.1, EV) \times \text{Confidence}}{\text{Effort} + \text{Risk}}$ with sample size uncertainty dampening.
5. **Content Evidence System & Factual Verification:** Require source verification for domain concepts (e.g. telecom operators vs mobile money), carrier health, and competitor pricing before publication.
6. **Production Indexing Funnel Tracking:** Track pages through `Published -> Discovered & Crawled -> Eligible & Indexed -> Impressions -> Clicks -> Conversions`. Automated unit/BDD tests prove regression safety; they do NOT prove SEO ranking growth.
7. **Title Display-Width Heuristics:** Replace rigid character thresholds with SERP rendering physics (~580px desktop, ~480px mobile).
8. **Sitemap `lastmod` Integrity:** Advance `<lastmod>` timestamps only on substantive content, functional, or pricing changes, never on routine cron runs.

---

## Architecture: The 6-Phase Closed Loop

```
[ Phase 0: Observability & Logging Stack Gate ]
         │ (Audit GA4, Clarity, PostHog, IndexNow, RUM, Server Logs)
         ▼
[ Phase 1: Data Source & MCP Connect ]
         │ (GSC OAuth / Service Account / Local Cache / 74 Reports)
         ▼
[ Phase 2: Technical & Crawl Health Pass ]
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

## The 8-State Page-Level Diagnostic Decision Tree

| State | Search State Diagnosis | Primary Underlying Cause | Prescribed Action Family | Implementation Contract Type |
| :---: | :--- | :--- | :--- | :--- |
| **State 1** | **Discovered / Crawled, Not Indexed** | Technical blockage, canonical mismatch, 404/5xx error, or low perceived value. | Technical & Delivery Remediation | `technical_fix` |
| **State 2** | **Indexed, Zero Impressions** | No search demand, or page buried too deep in crawl architecture. | Reassess Role / Internal Links / Consolidate | `internal_link_update` or `content_consolidation` |
| **State 3** | **Impressions, Position > 30** | Weak topical relevance, low domain authority, or mismatched search intent. | Topic Re-architecture or Specialized Page Creation | `content_expansion` or `new_page_creation` |
| **State 4** | **Striking Distance Stage 2 (Pos 11–30)** | Page has baseline relevance but lacks topical depth, edge cases, or authority. | Topical Depth & Sub-Topic Coverage | `content_expansion` |
| **State 5** | **Striking Distance Stage 1 (Pos 4–10)** | Page ranks on Page 1 but is held back by missing computational utility or internal links. | Add Original Calculator/Utility & Hub Links | `content_expansion` & `internal_link_update` |
| **State 6** | **Top 3, Below Benchmark CTR** | Snippet is underperforming; title or description fails to match searcher promise. | Title & SERP Snippet Optimization | `title_optimization` |
| **State 7** | **Good Traffic, Low Conversions** | Search intent satisfied but landing UX, mobile layout, or CTA is broken. | Conversion Funnel Optimization (CRO) | `content_expansion` (UX/Funnel) |
| **State 8** | **Multi-URL Cannibalization** | Multiple URLs compete for identical queries, splitting authority and ranking. | Canonical Designation & Content Differentiation | `content_consolidation` |

---

## 7 Standard Typed Action Contracts

Every emitted SEO action follows a strict implementation contract:

1. `title_optimization`: Optimizes title tags within display width (~580px desktop, ~480px mobile) to front-load intent modifiers while aligning with visible `<h1>`.
2. `content_expansion`: Deepens topic coverage with answers to real GSC query variations and original interactive calculation tools.
3. `internal_link_update`: Adds crawlable standard HTML links (`<a href="...">`) from high-authority category hubs with descriptive anchor text.
4. `technical_fix`: Remediates edge 5xx/404 errors, canonical tag inconsistencies, or failing Core Web Vitals.
5. `new_page_creation`: Builds purpose-built pages for unmet query clusters passing the 7-factor quality gate and URL ownership check.
6. `content_consolidation`: Resolves multi-URL keyword cannibalization by designating canonical topic owners and 301-redirecting thin duplicates.
7. `measurement_only`: Sets up telemetry observation windows for uncertain hypotheses where premature code modification carries downside risk.

---

## 4 Core Operational Recipes

- **Recipe A — Improve Rankings for Existing Pages (Positions 4–20):** Extract top query clusters, inspect live SERP formats (calculators, tools, directories, guides), add missing computational logic or verified benchmarks, link contextually from relevant category hubs, and deploy the smallest change that directly closes the gap.
- **Recipe B — Improve CTR Without Sacrificing Relevance:** Segment impressions by device and country, verify title display width (~580px desktop, ~480px mobile), align visible H1 with title, and evaluate over 28-day Difference-in-Differences against matched URL cohort.
- **Recipe C — Recover Pages That Are Not Gaining Impressions:** Classify in indexing funnel (Not Discovered vs Crawled Not Indexed vs Duplicate Canonical vs No Demand); deploy technical fixes for canonicals, add unique utility for weak content, or add internal links for isolated pages.
- **Recipe D — Scale Content That Has Demonstrated Value:** Track page-family health (% indexed, % receiving impressions, % generating clicks). If a page family succeeds, expand it using the same validated mechanisms and verified data; if it underperforms, fix the template defect before generating more URLs.

---

## Antigravity Installation & Setup

### 1. Connect the SEO MCP Server
Antigravity automatically connects to the `seo` MCP server. Ensure your `~/.gemini/antigravity/mcp_config.json` (or `~/.gemini/config/mcp_config.json`) includes:

```json
{
  "mcpServers": {
    "seo": {
      "command": "seo",
      "args": ["mcp", "serve"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
      }
    }
  }
}
```

*Note: For local crawl audits and technical site inspections, zero Google credentials are required.*

### 2. Install Skill into Antigravity

```bash
# Global Antigravity installation (recommended)
git clone https://github.com/magebase/improve-seo-with-data.git /home/aqua/skills/improve-seo-with-data
ln -sf /home/aqua/skills/improve-seo-with-data ~/.gemini/config/skills/improve-seo-with-data

# Workspace installation (project-specific)
mkdir -p .agents/skills
ln -sf /home/aqua/skills/improve-seo-with-data .agents/skills/improve-seo-with-data
```

---

## CLI & Automation Quickstarts

### 0. Run the Master Growth Intelligence Engine
```bash
# Live analysis against GSC property with EV scoring & diagnostic state classification
python3 scripts/seo_growth_intelligence.py --site sc-domain:example.com

# Ingest historical GSC + GA4 exports with custom conversion values
python3 scripts/seo_growth_intelligence.py \
    --gsc-file gsc_export.json \
    --ga4-file ga4_export.json \
    --telemetry-file telemetry_export.json \
    --conv-value 25.0 \
    --output-json /tmp/action_queue.json \
    --output-md /tmp/action_queue.md
```

### 1. Audit & Setup the Observability Stack
```bash
python3 scripts/setup_observability.py --url https://example.com
```

### 2. Verify Environment & MCP Health
```bash
python3 scripts/verify_mcp.py
```

### 3. Run Technical Crawl Audit
```bash
python3 scripts/run_audit.py --url https://example.com --output /tmp/audit.json
```

### 4. Evaluate AI Search Readiness (GEO)
```bash
python3 scripts/geo_evaluator.py --url https://example.com
```

---

## Repository Structure

```text
improve-seo-with-data/
├── SKILL.md                          # Antigravity skill specification & runbook
├── README.md                         # Architecture & quickstart guide
├── LICENSE                           # MIT License
├── mcp_config.json                   # MCP server definition schema
├── schemas/
│   ├── seo-action.schema.json        # Schema with typed actions, EV math, and diagnostic states
│   └── data-source-manifest.schema.json
├── scripts/
│   ├── seo_growth_intelligence.py    # Master engine with EV scoring, URL ownership & 8 diagnostic states
│   ├── setup_observability.py        # Observability & telemetry stack auditor & setup tool
│   ├── verify_mcp.py                 # MCP and CLI diagnostic runner
│   ├── run_audit.py                  # Technical crawl & single-page audit engine
│   ├── gsc_analyzer.py               # GSC performance, striking distance & CTR tool
│   └── geo_evaluator.py              # AI search readiness & llms.txt validator
├── references/
│   ├── page_level_decision_engine.md # 8-state tree, 7 typed actions, URL ownership & 4 recipes
│   ├── observability_stack_guide.md  # Modern $0 Observability & Telemetry architecture manual
│   ├── mcp_catalog.md                # Complete 74-report catalog and schemas
│   ├── geo_playbook.md               # Generative Engine Optimization manual
│   └── gsc_optimization_runbook.md   # Query clustering & CTR tuning runbook
└── templates/
    ├── telemetry_snippet.html        # High-performance multi-provider analytics & RUM snippet
    ├── llms.txt                      # Production-grade AI agent documentation
    ├── schema_org.json               # Validated JSON-LD rich snippet templates
    └── audit_report_template.html    # Standalone, clean client audit deliverable
```

---

## License

MIT © [Magebase](https://github.com/magebase)
