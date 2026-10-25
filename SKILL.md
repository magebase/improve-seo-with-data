---
name: improve-seo-with-data
description: >-
  The authoritative, data-first SEO Growth & Conversion Operating System. Use this skill whenever you need to audit, diagnose, optimize, or scale a website's organic search visibility, conversion funnels, or AI search presence using real data. Automatically fetches and joins Google Search Console (GSC queries, pages, countries, devices, search appearance, and historical trends), Google Analytics 4 (GA4 landing-page conversions and revenue), PostHog (funnels and A/B experiments), Microsoft Clarity (heatmaps, rage clicks, and dead clicks), Cloudflare (edge delivery, 5xx/404 errors, and crawler logs), Better Stack (uptime incidents), and Grafana (Core Web Vitals). Formulates prioritized, effort-adjusted Action Queues and executes rigorous SEO matched-cohort and CRO experiments.
---

# improve-seo-with-data: The SEO & Conversion Growth Operating System

An autonomous, data-first SEO engineering, conversion optimization, and Generative Engine Optimization (GEO) system for **Antigravity CLI (`agy`)**, **Claude Code**, and engineering fleets.

Eliminates speculative "best practices" and isolated dashboards. Turns multi-dimensional performance data into a prioritized, revenue-weighted growth engine that identifies where search visibility exists, diagnoses why it is not producing clicks or conversions, and continuously tests changes that compound business outcomes.

---

## Operating Invariants

1. **Observability Precedes Optimization:** If a website cannot observe its organic search visitors, crawler hits, rage clicks, and conversion funnels, it is flying blind. Audit and configure the telemetry stack before modifying code or metadata.
2. **The Growth Equation Over Vanity Metrics:**
   $$\text{Impressions} \longrightarrow \text{Clicks} \longrightarrow \text{Qualified Visits} \longrightarrow \text{Conversions \& Revenue}$$
   Every metric has a specific growth lever:
   - *Impressions:* Indexation, topical depth, sitemap inclusion, semantic coverage, internal links.
   - *Average Position:* Intent alignment, content depth, original calculation/data utility, authority.
   - *CTR:* Title tags, meta descriptions, intent modifiers, Schema rich snippet eligibility.
   - *Clicks:* Protecting winners, defending against cannibalization, expanding related clusters.
   - *Conversions:* Landing page intent match, mobile UX, frictionless CTAs, value propositions.
3. **Cross-Dimensional Synthesis (No Data Silos):** Never analyze queries, pages, countries, devices, search appearances, or dates in isolation. The highest-leverage opportunities emerge when you combine them (e.g., query cluster $\times$ landing page $\times$ device $\times$ GA4 conversion rate).
4. **Traffic Change Decomposition:** Always decompose click changes between periods into underlying components before diagnosing drops:
   $$\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$$
   Distinguish impression volume expansion/contraction from snippet engagement (CTR) shifts.
5. **Separate SEO Experiments from CRO Experiments:**
   - *SEO Experiments:* Matched URL cohorts evaluated via Difference-in-Differences (DiD). Never serve different HTML to Googlebot vs. human users.
   - *Conversion Experiments:* Visitor-level randomized A/B tests managed through PostHog.
6. **Query-Mix Adjustment:** Never infer sitewide snippet deterioration from an unadjusted drop in aggregate CTR. Hold query position, country, and device distributions constant to isolate true performance.
7. **Crawl Budget & Parameter Defense:** Guard crawler bandwidth by ensuring faceted query parameters (`?sort=`, `?filter=`, `?page=`) are governed by `Disallow: /*?*` in `robots.txt` and marked with `rel="nofollow"` on internal links, while keeping canonical URLs strictly static.
8. **Generative Engine Optimization (GEO):** Maintain machine-readable documentation via [`llms.txt`](./templates/llms.txt), validated Schema.org JSON-LD entity graphs, and explicit AI crawler permissions (`GPTBot`, `ClaudeBot`, `PerplexityBot`).
9. **Auditable Action State Machine:** Every recommendation must enter a structured action queue (`seo-action.schema.json`) and transition through:
   $$\text{Detected} \longrightarrow \text{Validated} \longrightarrow \text{Approved} \longrightarrow \text{Implemented} \longrightarrow \text{Evaluated} \longrightarrow \text{Learned}$$
10. **Closed-Loop Verification:** Always re-run the matching audit report, crawler pass, or telemetry evaluator after implementing code changes to verify 0 regressions.
11. **Direct Empirical Data Traceability (Zero Speculative Actions):** Every summary action, backlog card, queue item, and recommendation MUST track directly back to an empirical observation in data (e.g., specific GSC query, impressions, position, CTR vs benchmark, GSC issue report with date/URL, GA4 landing page session count & conversion rate, PostHog funnel step drop-off %, Clarity rage/dead click counts and target element, Cloudflare edge 5xx/404 counts or CWV LCP/INP/CLS metrics). Speculative "best practices", subjective design opinions, or orphan actions lacking a cited empirical data observation are strictly banned across all reports, queue tables, and code edits.
12. **Dual-Track Execution Mandate (Improve Existing AND Create New Every Run):** Every single invocation of this skill MUST execute BOTH tracks in parallel:
    - **Track 1: Improve Existing Pages:** Title optimization within display-width limits (~580px desktop, ~480px mobile), snippet appeal, content depth/utility, Schema.org rich data, internal links, and conversion CTA streamlining for existing URLs with impressions or CTR gaps.
    - **Track 2: Create New Pages:** Detect unmet query clusters (queries landing on generic hubs like `/`, `/articles/`, `/compare/`, `/tools/`, or queries with no dedicated target URL) that pass the URL ownership check and 7-factor quality gate. Automatically build and register them into production models, views, templates, sitemaps, and Gherkin acceptance specs across the 5 Standard Template Archetypes.
    Stopping after only improving existing pages, or only creating new pages without improving existing winners, is strictly prohibited. Every run must deliver both.
13. **The SEO Outcome Maximization Contract:**
    - **Primary Objective:** Maximize incremental organic clicks and meaningful business conversions through continuous diagnosis, implementation, measurement, and learning. Do NOT optimize for the number of pages published, changes made, tests passed, or words written.
    - **Clause 1 (Exhaustive Discovery):** Low volume is uncertainty, not a rejection threshold. Every detected opportunity results in a concrete action, a defined diagnostic step, or an explicit evidence-backed decision to defer.
    - **Clause 2 (Diagnose First):** Classify failure modes using the 8-State Page-Level Diagnostic Decision Tree before choosing code or content edits.
    - **Clause 3 (Expected Value Scoring):** Prioritize via $EV(a) = P(\text{success} \mid a) \times V(a) - Cost(a) - Risk(a)$ and $\text{Priority} = \frac{\max(0.1, EV) \times \text{Confidence}}{\text{Effort} + \text{Risk}}$ with empirical sample size uncertainty dampening.
    - **Clause 4 (Baseline & Change History):** Record pre-deployment metrics, date ranges, canonicals, and content version hashes before modifying live code.
    - **Clause 5 (Content & Technical Quality):** Enforce factual claim provenance, domain accuracy (e.g. telecom carriers vs mobile money), and verified competitor data.
    - **Clause 6 (Post-Deployment Measurement):** Track real search performance over 14–28 days. Automated unit/BDD tests prove regression safety; they do NOT prove SEO ranking growth.
    - **Clause 7 (Continuous Learning):** Maintain persistent outcome records to refine future probability estimates.
    - **Clause 8 (Execution Policy):** Batch safe changes; never report test completion or code delivery as proof of SEO growth.
14. **The URL Ownership Model & Anti-Cannibalization Gate:**
    Before creating or modifying a page, establish the mapping:
    $$\text{query\_cluster} \longrightarrow \text{intended\_url} \longrightarrow \text{actual\_ranking\_urls}$$
    If an existing non-hub URL already ranks at position $\le 15.0$ or receives the majority of impressions for a query cluster, **NEVER create a new competing page**. The correct action is to improve that existing URL (Recipe A), add a targeted sub-topic section, or strengthen internal links.
15. **Title SERP Display-Width Heuristics (~580px Desktop / ~480px Mobile):**
    Google truncates title links based on container rendering width in pixels (~580px desktop, ~480px mobile), not raw character counts. Keep 50–65 characters as a practical rule of thumb, but never reject titles based on an arbitrary character limit. Verify that the primary user intent and brand fit within display-width limits.
16. **Sitemap `lastmod` Timestamp Integrity:**
    XML sitemap `<lastmod>` timestamps must strictly reflect **substantive content, pricing, or functional updates**, never routine cron runs or automated deployment sweeps.
17. **Production Indexing Funnel Tracking:**
    Track pages through the complete search production funnel:
    $$\text{Published} \longrightarrow \text{Discovered \& Crawled} \longrightarrow \text{Eligible \& Indexed} \longrightarrow \text{Receiving Impressions} \longrightarrow \text{Generating Clicks \& Conversions}$$

---

## System Architecture: 3 Data Planes & 1 Decision Engine

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PLANE A: SEO & BUSINESS BI                      │
│               GSC (Search Demand)  ·  GA4 (Conversions)               │
│               PostHog (Funnels, Feature Adoption & A/B)                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                        PLANE B: USER EXPERIENCE (UX)                   │
│     Microsoft Clarity (Heatmaps, Rage Clicks, Dead Clicks, Scroll)     │
│             PostHog Session Replay  ·  Browser Field RUM               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                    PLANE C: TECHNICAL RELIABILITY                      │
│   Cloudflare (Edge Status, Bot Logs, Latency, WAF, Workers Analytics)   │
│       Better Stack (Uptime Incidents)  ·  Grafana / Faro (APM/CWV)     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  CANONICAL SEO DECISION & ACTION ENGINE                │
│       Detect  ──▶  Diagnose  ──▶  Score  ──▶  Approve  ──▶  Learn      │
│                (Prioritized Auditable Action Queue)                    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## The Core Mission: Turn SEO Data into Page-Level Decisions

When an agent is asked to **improve a domain or website**, its primary mission is governed by the **Dual-Track Execution Mandate**: systematically improving existing pages while concurrently discovering and building new pages for unmet search queries across **six page-level actions**:

1. **Improve an existing page** *(Track 1)*
2. **Create a new page** *(Track 2)*
3. **Improve a shared template** *(Track 1)*
4. **Build a new template** *(Track 2)*
5. **Consolidate overlapping pages** *(Track 1)*
6. **Make no change**

### 1. The Decision Matrix

| What the Data Tells You | What to Change (The Action) | What NOT to Do |
| :--- | :--- | :--- |
| A page ranks for relevant queries around positions 4–20. | **Improve the existing page's** usefulness, intent coverage, internal links, and result presentation. | Automatically create another page for the same topic. |
| High impressions but low CTR versus comparable results. | **Investigate and test the title**, page messaging, and snippet relevance on the existing page. | Change titles based only on a sitewide CTR benchmark. |
| A cluster of related queries is growing and existing page already addresses intent. | **Add useful sections, examples, comparisons, or an interactive tool** to the existing URL. | Split every keyword variation into a separate URL. |
| A valuable query cluster has a distinct intent and no suitable landing page. | **Create a new, purpose-built page** passing the 7-factor quality gate and URL ownership check. | Create a thin page that merely rephrases an existing one. |
| Hundreds of pages share the same structural or component problem. | **Improve the shared template**, after testing the change on a matched cohort. | Manually patch hundreds of URLs one at a time. |
| Several URLs target essentially the same search intent. | **Differentiate their purpose or consolidate** overlapping content via canonical/301. | Redirect pages just because their impressions are low. |
| Visitors click but rarely convert (high traffic, weak conversions). | **Improve the landing experience, offer, or funnel** (CTA, mobile layout, inputs). | Publish more informational articles to solve a conversion problem. |
| Pages are inaccessible, incorrectly canonicalized, or failing to render. | **Fix the underlying delivery, rendering, or technical defect**. | Keep generating pages that have the same technical blocker. |
| A page has no meaningful demand, unique value, or business purpose. | **Reassess its role; improve, consolidate, retire, or leave it alone**. | Keep expanding the site merely to increase URL count. |

### 2. The 8-State Page-Level Diagnostic Decision Tree

Before selecting an intervention, classify the diagnosed search state for the target URL or query cluster:

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

### 3. The 7 Standard Typed Action Contracts

Every emitted SEO action must follow one of the 7 typed implementation contracts:

| Action Type | Required Inputs | Verification & Completion Conditions |
| :--- | :--- | :--- |
| `title_optimization` | Baseline query data, current title, CTR vs benchmark, display-width metrics. | New title front-loads intent, fits ~580px desktop / ~480px mobile display limits, and matches visible H1. |
| `content_expansion` | Page content, unanswered user questions from GSC query variations, verified data sources. | New section or interactive utility directly resolves identified gap; verified against factual sources. |
| `internal_link_update` | Source category hub, target page, contextual anchor text rationale. | Valid crawlable standard HTML link (`<a href="...">`) deployed; verified in crawler pass. |
| `technical_fix` | Reproducible defect, Cloudflare/BetterStack telemetry, expected HTTP response. | Edge 5xx/404 eliminated, canonical inconsistency resolved, regression test passes. |
| `new_page_creation` | Query cluster, URL ownership analysis, content evidence payload, archetype selection. | Page passes 7-factor quality gate; registered in views, models, sitemaps, and test suites. |
| `content_consolidation` | Overlapping URLs, performance distribution, primary canonical designation. | Redirect/canonical deployed, split authority unified, verified in 28-day rank consolidation. |
| `measurement_only` | Uncertain hypothesis or low-confidence data where intervention has downside risk. | Telemetry tracking configured; wait for minimum observation window before code edits. |

### 4. The 4 Core Operational Recipes

- **Recipe A — Improve Rankings for Existing Pages (Positions 4–20):**
  Extract top query clusters, inspect live SERP formats (calculators, tools, directories, guides), add missing computational logic or verified benchmarks, link contextually from relevant category hubs, and deploy the smallest change that directly closes the gap.
- **Recipe B — Improve CTR Without Sacrificing Relevance:**
  Segment impressions by device and country, verify title display width (~580px desktop, ~480px mobile), align visible H1 with title, and evaluate over 28-day Difference-in-Differences against matched URL cohort.
- **Recipe C — Recover Pages That Are Not Gaining Impressions:**
  Classify in indexing funnel (Not Discovered vs Crawled Not Indexed vs Duplicate Canonical vs No Demand); deploy technical fixes for canonicals, add unique utility for weak content, or add internal links for isolated pages.
- **Recipe D — Scale Content That Has Demonstrated Value:**
  Track page-family health (% indexed, % receiving impressions, % generating clicks). If a page family succeeds, expand it using the same validated mechanisms and verified data; if it underperforms, fix the template defect before generating more URLs.

### 5. Content Evidence System & Factual Safeguards

Every programmatic or generated page must be backed by a structured evidence payload:
- **Verified Primary Sources:** Official ITU standards, API specifications, carrier documentation, or regulatory filings.
- **Telecom & Domain Accuracy:** Distinguish telecom carriers (e.g., Safaricom, AT&T) from mobile payment services (e.g., M-PESA).
- **Competitor Claim Verification:** Require source-backed verification for competitor pricing, API limits, and features.
- **Operational Reality:** On SMS/telecom pages, display real carrier health, live routing statuses, and tested latency rather than static marketing copy.

### 6. The Existing-Page Improvement Workflow
For each important URL, check and edit these 6 areas in strict order:
1. **Title & Search-Result Messaging:** Align `<title>`, `<meta name="description">`, and visible `<h1>`. Use accurate intent modifiers (`Free`, `Online`, `Calculator`, `Instant`, Current Year). *Do not inject FAQPage schema expecting FAQ rich snippets (Google removed FAQ rich snippets).*
2. **The First Screen of Content (Above the Fold):** Deliver immediate clarity—can visitors instantly see what the tool does, who it is for, and how to get the answer?
3. **Missing Topic Coverage:** Ingest GSC's actual query variations to add unanswered sub-topics, parameters, or edge-case explanations.
4. **Original Value & Interactive Utility:** Provide what competitors lack: a working deterministic calculator, verified data tables, comparison criteria, or proprietary benchmarks.
5. **Internal Links:** Add crawlable HTML links (`<a href="...">`) with concise, natural anchor text from relevant category hubs.
6. **Conversion Experience:** Fix mobile input reflow, remove dead/rage clicks identified in Clarity, and streamline the primary CTA.

### 7. The New-Page Decision Process & 7-Factor Quality Gate
> **The unit of page creation is a distinct search intent and user task, NOT an individual keyword query.**

A new page is created **ONLY** when an unmet query cluster exists and passes all 7 quality factors:
1. *Demand:* Verified relevant impressions in GSC.
2. *Intent Gap:* No existing page properly satisfies this specific user task.
3. *Business Value:* The audience has a clear, valuable next step (signup, calculation, checkout).
4. *Unique Value:* Adds original proprietary data, code, or interactive tool.
5. *Differentiation:* Distinct from existing URLs; zero cannibalization risk.
6. *Cost & Maintenance:* Can be maintained when underlying data shifts.
7. *Risk & Quality:* Zero thin doorway text; passes Google spam & helpful content standards.

### 8. The 5 Standard Template Archetypes
1. *Editorial / Guide Template:* For informational queries (answers, context, author, citations).
2. *Comparison Template:* For "A vs B" & "Best Alternative" queries (decision criteria, comparison matrix).
3. *Tool / Calculator Template:* For functional calculation queries (interactive inputs, instant outputs).
4. *Directory / Category Template:* For browsing and discovery queries (structured filters, crawlable detail links).
5. *Localized / Market-Specific Template:* For real regional differences (currencies, regulations, service areas).

### 9. Priority Execution Order & The 5 Mandatory Questions
Every single run MUST execute both tracks concurrently:

- **Track 1 (Existing Pages & Templates):**
  1. **P1: Technical Blockers First** (5xx errors, broken canonicals, robots indexation shields).
  2. **P2: Valuable Existing Pages Second** (CTR gaps, striking-distance positions 4–20, title display width optimization, conversion leakage).
  3. **P3: Shared Templates Third** (Fix component speed, layout shifts, or mobile UX across hundreds of pages).

- **Track 2 (New Pages & Unmet Demand):**
  4. **P4: New Pages & Tools Fourth** (Genuinely missing intents passing the URL ownership check and 7-factor quality gate, implemented across the 5 Standard Template Archetypes with full data models, views, templates, sitemaps, Gherkin specs, and tests).

Every recommendation and summary action emitted must answer:
1. *Target Scope:* Which specific URL, page cohort, or shared template should change?
2. *Page-Level Action & Implementation Contract:* Which of the 6 actions and 7 typed contracts is being executed?
3. *Direct Data Observation & Supporting Evidence:* What exact empirical data observation (telemetry source, metric value, date/period, baseline vs benchmark) triggered this action?
4. *Measurable Target Metric:* What exact measurable outcome should improve?
5. *Scale / Rollback Protocol:* How will you determine whether to scale, revise, or reverse the intervention?

---

## 7 Autonomous Operational Workflows

### Workflow 1: Multi-Dimensional GSC & GA4 Opportunity Discovery
Run the automated growth intelligence orchestrator to ingest GSC, GA4, and telemetry data:

```bash
# Automated live analysis against GSC property
python3 scripts/seo_growth_intelligence.py --site sc-domain:example.com

# Or ingest historical GSC + GA4 exports with custom conversion values
python3 scripts/seo_growth_intelligence.py \
    --gsc-file /path/to/gsc_export.json \
    --ga4-file /path/to/ga4_export.json \
    --telemetry-file /path/to/telemetry.json \
    --conv-value 25.0 \
    --output-json /tmp/action_queue.json \
    --output-md /tmp/action_queue.md
```

The orchestrator executes the **Dual-Track Growth Detectors**:
- **Track 1 Detectors (Improve Existing Pages & Shared Templates):**
  - **Detector A (CTR Opportunities):** Identifies positions 1–10 underperforming benchmark CTR (Recipe B).
  - **Detector B (Ranking Opportunities):** Targets striking distance queries (positions 4.0 to 20.0) with high organic impressions (Recipe A).
  - **Detector C (Conversion Leakage):** Flags organic landing pages earning clicks but converting below 50% of cluster average, or displaying high PostHog dropoff / Clarity rage clicks.
  - **Detector D (Technical Risk):** Detects Cloudflare 5xx spikes, Better Stack downtime, or failing Core Web Vitals (LCP > 2.5s, INP > 200ms, CLS > 0.1).
  - **Detector E (Cannibalization Consolidation):** Resolves queries split across multiple URLs and unifies split ranking authority.
- **Track 2 Detector (Create New Pages for Unmet Search Demand):**
  - **Detector F (Unmet Query & Template Archetype Synthesis):** Identifies high-intent queries landing on generic hubs (`/`, `/articles/`, `/compare/`, `/tools/`) lacking a dedicated URL, enforces URL ownership and the 7-factor quality gate, maps them to one of the 5 standard template archetypes, and generates end-to-end delivery specifications.

Every action item is prioritized via:
$$EV(a) = P(\text{success} \mid a) \times V(a) - Cost(a) - Risk(a) \qquad\text{Priority Score } P = \frac{\max(0.1, EV) \times q}{E + \text{Risk}}$$

---

### Workflow 2: Period-over-Period Traffic Change Decomposition
When diagnosing traffic gains or declines across 7-day, 28-day, or 90-day intervals:

```bash
python3 scripts/gsc_analyzer.py --compare-periods period0_baseline.json period1_recent.json
```

Separates impression volume changes from snippet engagement changes:
$$\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$$

---

### Workflow 3: Conversion Leakage & UX Friction Diagnosis
When search clicks fail to convert:
1. **GA4 Audit:** Locate landing pages where organic session volume is high but conversion rate ($r$) is depressed.
2. **PostHog Funnel Scan:** Inspect step-by-step drop-offs to determine where users abandon the journey.
3. **Clarity Friction Investigation:** Filter session recordings by affected landing page and device category; inspect rage clicks, dead clicks, and 50% scroll line placement.
4. **Formulate CRO Intervention:** Simplify mobile inputs, sticky-position primary CTA, and test via PostHog visitor-level A/B test.

---

### Workflow 4: Technical Reliability & Incident Correlation
Correlate operational failures with search crawl and ranking anomalies:
1. **Cloudflare Edge Logs:** Monitor 5xx response spikes and 404 error clusters; verify Googlebot via reverse DNS.
2. **Better Stack Downtime Correlation:** Map outage start/end timestamps against GSC crawl activity.
3. **Core Web Vitals Telemetry (Grafana / Faro):** Ensure LCP $\le 2.5\text{s}$, INP $\le 200\text{ms}$, and CLS $\le 0.1$.

---

### Workflow 5: Multi-Market & Device Gap Optimization
Segment performance across `country` and `device` dimensions:
```bash
python3 scripts/gsc_analyzer.py --export gsc_multi_dimensional.json
```
- **Geographic Arbitrage:** Localize snippets and currencies for high-impression, low-CTR regions.
- **Device Ergonomics:** If mobile CTR is $>25\%$ lower than desktop for the identical query position, audit mobile SERP snippet length (~480px mobile vs ~580px desktop) and touch targets (minimum 44x44px).

---

### Workflow 6: Experiment Design & Evaluation
Never guess whether an SEO or CRO change worked. Use structured experiment protocols:
1. **SEO Experiments (Matched URL Cohorts):**
   - Select 20 comparable URLs; assign 10 to **Treatment** and 10 to **Control (Holdout)**.
   - Apply title, schema, or content changes exclusively to the Treatment group.
   - Evaluate after 28 days using **Difference-in-Differences**:
     $$\text{Net Treatment Lift} = (\text{Treatment}_{t1} - \text{Treatment}_{t0}) - (\text{Control}_{t1} - \text{Control}_{t0})$$
2. **CRO Experiments (Visitor-Level A/B Tests):**
   - Use PostHog to randomize human visitors 50/50 across Control and Variant layouts while serving identical HTML to search crawlers.

---

### Workflow 7: Generative Engine Optimization (GEO) & Machine-Readable Discovery
Ensure search visibility across LLM answer engines (**ChatGPT Search**, **Perplexity**, **Claude**, **Google AI Overviews**):
```bash
python3 scripts/geo_evaluator.py --url https://example.com
```
1. Deploy [`llms.txt`](./templates/llms.txt) at `/llms.txt` and `/llms-full.txt`.
2. Permit AI Crawlers in `robots.txt` (`GPTBot`, `ClaudeBot`, `PerplexityBot`).
3. Structured Schema.org Entity Graphs: Homepage unified `@graph` (`Organization`, `WebSite`, `SoftwareApplication`) and dynamic `BreadcrumbList`.

---

## Tool & Script Inventory

| Tool / Script | Authoritative Function |
| :--- | :--- |
| [`scripts/seo_growth_intelligence.py`](./scripts/seo_growth_intelligence.py) | **The Master Engine:** Ingests multi-source telemetry, executes 6 opportunity detectors, classifies 8 diagnostic states, enforces URL ownership, computes $EV(a)$ expected values, and emits prioritized Action Queues. |
| [`scripts/gsc_analyzer.py`](./scripts/gsc_analyzer.py) | Multi-dimensional Search Console analyzer for queries, pages, countries, devices, and period-over-period traffic decomposition. |
| [`scripts/setup_observability.py`](./scripts/setup_observability.py) | Scans, validates, heals, and exports telemetry manifests (`DataSourceManifest`) and drop-in tracking snippets. |
| [`scripts/geo_evaluator.py`](./scripts/geo_evaluator.py) | Scores AI agent readiness, evaluates `llms.txt`, and validates Schema.org JSON-LD structured data. |
| [`scripts/run_audit.py`](./scripts/run_audit.py) | High-speed technical crawler pass for status codes, canonical consistency, and crawl budget parameter defense. |
| [`schemas/seo-action.schema.json`](./schemas/seo-action.schema.json) | Standardized JSON Schema for prioritized, auditable SEO and CRO action cards. |
| [`schemas/data-source-manifest.schema.json`](./schemas/data-source-manifest.schema.json) | Declares connection status, freshness watermarks, and capabilities across all 7 telemetry platforms. |
| [`references/page_level_decision_engine.md`](./references/page_level_decision_engine.md) | Exhaustive guide on the 8-state diagnostic decision tree, 7 typed action contracts, URL ownership model, and 4 recipes. |
| [`references/gsc_multidimensional_playbook.md`](./references/gsc_multidimensional_playbook.md) | Exhaustive guide on extracting maximum value from GSC dimensions, decomposition math, and query clustering. |
| [`references/seo_growth_os_architecture.md`](./references/seo_growth_os_architecture.md) | The 3-plane system architecture, Cloudflare hybrid storage model, and tool responsibility boundaries. |
| [`references/conversion_diagnosis_and_experimentation.md`](./references/conversion_diagnosis_and_experimentation.md) | Joining search demand to conversions, PostHog funnels, Clarity heuristics, and matched-cohort experimentation. |
| [`templates/seo_action_queue.md`](./templates/seo_action_queue.md) | Executive markdown template for the prioritized action queue. |
| [`templates/experiment_plan.md`](./templates/experiment_plan.md) | Pre-formatted test plan for SEO matched-cohort and CRO visitor-level experiments. |
