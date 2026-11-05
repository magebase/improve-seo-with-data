# Improve SEO with Data (`improve-seo-with-data`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Antigravity Compatible](https://img.shields.io/badge/Antigravity-Skill-purple.svg)](https://github.com/magebase/improve-seo-with-data)
[![MCP Server: seo](https://img.shields.io/badge/MCP-74%20Reports-green.svg)](references/mcp_catalog.md)

Autonomous, data-driven SEO engineering, Observability, and Generative Engine Optimization (GEO) skill for **Google Antigravity CLI (`agy`)**, **Claude Code**, **Cursor**, and multi-agent developer fleets.

Governed by the **SEO Outcome Maximization Contract**: eliminates superficial "best practice" checklists and speculative keyword guessing. Every audit, diagnosis, code modification, and page generation is backed by authentic first-party data: **Google Search Console (GSC)** performance, **Microsoft Clarity** UX telemetry, **PostHog** conversion funnels, **Cloudflare** edge performance & Core Web Vitals, and **live SERP competitor DOMs**.

---

## 1. Where Most "Data-Driven" SEO Skills Fail

This skill is engineered to eliminate the 5 critical structural flaws common in automated SEO tools:
1. **Aggregating by Page or Query Alone:** Queries joint `["page", "query", "device"]` to detect multi-URL cannibalization and intent mismatch.
2. **Naive CTR Thresholds:** Replaces flat CTR filters with a mathematical **Position-Adjusted CTR Curve** ($Pos \le 1.0: 30\%, 2.0: 18\%, 3.0: 12\%, 5.0: 7\%, 10.0: 3\%$).
3. **Ignoring Period-over-Period Deltas:** Isolates decaying money pages via traffic change decomposition ($\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$).
4. **Optimizing Blind Without Competitor Context:** Scrapes live top 5 SERP titles, headings, and schema to find semantic gaps.
5. **No Verification Loop:** Logs baselines, timestamps deployment dates, and tracks 14-to-28-day post-change GSC rank consolidation.

---

## 2. The 4 High-Leverage Data Pipelines

| Target Metric | Pipeline Name | Exact Filter & Logic | Automated Action Taken |
| :--- | :--- | :--- | :--- |
| **CTR & Clicks** | **Pipeline 1: Position-Adjusted CTR Underperformers** | $Pos \le 5.5, Imp \ge 500, CTR < Expected \times 0.70$ | Rewrite `<title>` & description; frontload query tokens; audit competitor hooks; verify FAQ/Product schema. |
| **Position & Clicks** | **Pipeline 2: Striking-Distance Semantic Gaps** | $Pos 6.0–15.5, Imp \ge 200$, query absent from headings | Inject dedicated `<h2>` section answering query directly; extract missing competitor entities; add hub links. |
| **Impressions** | **Pipeline 3: Zero-Click / Emerging Cluster Expansion** | $Pos 16.0–35.0, +50\%$ MoM velocity, $\le 5$ clicks | Evaluate SERP overlap: $>60\%$ shared URLs = expand existing page; $<40\%$ = create new spoke page. |
| **Position & CTR** | **Pipeline 4: Cannibalization & Decay Triage** | Multiple URLs with $\ge 15\%$ impression share, or $>20\%$ click drop | Consolidate competing pages via 301/canonical; differentiate H1 targeting; refresh stale content. |

---

## 3. Multi-Platform Telemetry Fusion Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PLANE A: SEO & BUSINESS BI                      │
│   Google Search Console (SERP Demand, joint Page+Query, Indexation)   │
│   PostHog (Organic Conversion Funnels, Event Drop-offs, Activation)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                        PLANE B: USER EXPERIENCE (UX)                   │
│   Microsoft Clarity (Heatmaps, Rage Clicks, Dead Clicks, Scroll Depth) │
│   PostHog Session Replay (User Journey Recordings, Rage Clicks)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                    PLANE C: TECHNICAL RELIABILITY                      │
│   Cloudflare Edge (TTFB, LCP, INP, CLS, Edge 5xx/404, Worker Logs)     │
│   Better Stack (Uptime Incidents) · Grafana / Faro (Field RUM)         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               UNIFIED MULTI-PLATFORM OPTIMIZATION ENGINE               │
│                   (scripts/seo_optimizer_engine.py)                    │
│      Detect  ──▶  Diagnose  ──▶  Score  ──▶  Execute  ──▶  Verify      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Opportunity Scoring & Agentic Guardrails

### Expected Value & Impact Score Formula

$$\text{Potential Click Lift} = \text{Impressions} \times \left(\text{Expected CTR}(\max(1.0, \text{Pos} - 2.0)) - \text{Actual CTR}\right)$$

$$\text{Friction Penalty} = (\text{Rage Clicks} > 10) \times 20 + (\text{LCP} > 2.5\text{s}) \times 30 + (\text{TTFB} > 400\text{ms}) \times 15$$

$$\text{Potential Impact Score} = \text{Potential Click Lift} - \text{Friction Penalty}$$

### Strict Guardrails Against SEO Hallucinations
- **Never Change Established URLs or Slugs:** Preserves backlink equity and eliminates redirect penalties.
- **Winner Protection Invariant:** Pages with $\text{Actual CTR} \ge \text{Expected CTR} \times 1.20$ at Position $\le 3.0$ are locked against title or snippet changes.
- **Anti-Keyword Stuffing Invariant:** Prohibits repeating keywords more than twice across title and H1.
- **Deterministic Preprocessing:** Python computes all metrics and rankings before handing structured summaries to LLMs.

---

## 5. The 8-State Page-Level Diagnostic Decision Tree

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

## 6. Antigravity Installation & Setup

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

## 7. CLI & Automation Quickstarts

### 0. Run the Multi-Source Correlation Engine
```bash
# Correlate GSC, Clarity, PostHog, and Cloudflare into prioritized Action Queue
python3 scripts/seo_optimizer_engine.py \
    --site sc-domain:example.com \
    --output-json /tmp/action_queue.json \
    --output-md /tmp/action_queue.md
```

### 1. Run the Master Growth Intelligence Engine
```bash
# Live analysis against GSC property with EV scoring & diagnostic state classification
python3 scripts/seo_growth_intelligence.py --site sc-domain:example.com
```

### 2. Audit & Setup the Observability Stack
```bash
python3 scripts/setup_observability.py --url https://example.com
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

## 8. Repository Structure

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
│   ├── seo_optimizer_engine.py       # Multi-platform correlation engine (GSC + Clarity + PostHog + CF)
│   ├── seo_growth_intelligence.py    # Master decision engine with EV scoring, URL ownership & 8 states
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
