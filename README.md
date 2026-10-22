# Improve SEO with Data (`improve-seo-with-data`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Antigravity Compatible](https://img.shields.io/badge/Antigravity-Skill-purple.svg)](https://github.com/magebase/improve-seo-with-data)
[![MCP Server: seo](https://img.shields.io/badge/MCP-74%20Reports-green.svg)](references/mcp_catalog.md)

Autonomous, data-driven SEO engineering and Generative Engine Optimization (GEO) skill for **Google Antigravity CLI (`agy`)**, **Claude Code**, **Cursor**, and multi-agent developer fleets.

Eliminates superficial "best practice" checklists and speculative keyword guessing. Every audit, diagnosis, and code modification is backed by authentic first-party data: **Google Search Console (GSC)** performance, **technical crawler logs**, **live SERP rankings**, and **LLM answer engine citations**.

---

## Architecture: The 5-Phase Closed Loop

```
[ Phase 1: Data Source & MCP Connect ]
         │ (GSC OAuth / Service Account / Local Cache)
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

## Key Capabilities

1. **Striking Distance Optimization (Positions 11 to 20):** Identifies keywords sitting on Google Page 2 that have high impressions and delivers targeted subheading, topical content, and internal link improvements to push them to Page 1.
2. **Low-CTR Quick Wins:** Discovers pages ranking in positions 1 to 7 with CTR below position benchmarks and optimizes title tag hooks, meta descriptions, and rich snippet markup.
3. **Generative Engine Optimization (GEO):** Audits and optimizes discoverability across Perplexity, ChatGPT Search, Claude, and Google AI Overviews using structured [`llms.txt`](templates/llms.txt), validated Schema.org JSON-LD, and AI crawler permissions.
4. **Crawl Budget & Facet Defense:** Protects search index health by ensuring faceted query parameters (`?filter=`, `?page=`) are blocked via `Disallow: /*?*` and flagged with `rel="nofollow"`, eliminating index bloat.
5. **Programmatic SEO (pSEO) Quality Gates:** Enforces interactive, high-utility tools (calculators, formatters, diagnostic lookups) over thin doorway content.
6. **Query Cannibalization Resolution:** Detects multiple URLs competing for identical queries and provides clean 301 consolidation or canonical ownership runbooks.

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

## Claude Code & Cursor Setup

### Claude Code
Add the MCP server via CLI:
```bash
claude mcp add seo seo mcp serve
```

### Cursor (`~/.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "seo": {
      "command": "seo",
      "args": ["mcp", "serve"]
    }
  }
}
```

---

## CLI & Automation Quickstarts

### 1. Verify Environment & MCP Health
```bash
python3 scripts/verify_mcp.py
```
Validates the local database cache, Google credentials, and verifies that all 74 reports across 9 categories are ready to run.

### 2. Run Technical Crawl Audit
```bash
python3 scripts/run_audit.py --url https://example.com --output /tmp/audit.json
```
Performs a fast sitemap health pass and technical crawl, categorizing findings into High, Medium, and Low severity with copy-paste remediation actions.

### 3. Analyze Search Console Performance
```bash
# Live Search Console query
python3 scripts/gsc_analyzer.py --site sc-domain:example.com

# Offline / exported JSON or CSV
python3 scripts/gsc_analyzer.py --export gsc_export.json
```
Extracts Page 2 striking distance queries and low-CTR quick wins.

### 4. Evaluate AI Search Readiness (GEO)
```bash
python3 scripts/geo_evaluator.py --url https://example.com
```
Audits `/llms.txt`, `robots.txt` AI crawler rules (GPTBot, ClaudeBot, PerplexityBot), Schema.org JSON-LD completeness, and semantic HTML structure.

---

## Repository Structure

```text
improve-seo-with-data/
├── SKILL.md                          # Antigravity skill specification & runbook
├── README.md                         # Architecture & quickstart guide
├── LICENSE                           # MIT License
├── mcp_config.json                   # MCP server definition schema
├── scripts/
│   ├── verify_mcp.py                 # MCP and CLI diagnostic runner
│   ├── run_audit.py                  # Technical crawl & single-page audit engine
│   ├── gsc_analyzer.py               # GSC performance, striking distance & CTR tool
│   └── geo_evaluator.py              # AI search readiness & llms.txt validator
├── references/
│   ├── mcp_catalog.md                # Complete 74-report catalog and schemas
│   ├── geo_playbook.md               # Generative Engine Optimization manual
│   └── gsc_optimization_runbook.md   # Query clustering & CTR tuning runbook
└── templates/
    ├── llms.txt                      # Production-grade AI agent documentation
    ├── schema_org.json               # Validated JSON-LD rich snippet templates
    └── audit_report_template.html    # Standalone, clean client audit deliverable
```

---

## Core Invariants

- **Evidence-First:** Every recommendation links to an authentic finding ID, URL inventory, or Search Console metric.
- **Never Promise Ranks:** Algorithms and competitors fluctuate; optimize for crawlability, intent, and CTR.
- **No Unicode Emojis in UI:** Production web interfaces and reports strictly use clean vector SVGs or text markers.
- **Closed-Loop Verification:** Always re-run the matching report after editing code to prove zero regressions.

---

## License

MIT © [Magebase](https://github.com/magebase)
