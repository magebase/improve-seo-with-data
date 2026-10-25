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

When an agent is asked to **improve a domain or website**, its primary mission is to translate every meaningful pattern across GSC, GA4, PostHog, Clarity, and technical telemetry into one of **six mutually exclusive page-level actions**:

1. **Improve an existing page**
2. **Create a new page**
3. **Improve a shared template**
4. **Build a new template**
5. **Consolidate overlapping pages**
6. **Make no change**

### 1. The Decision Matrix

| What the Data Tells You | What to Change (The Action) | What NOT to Do |
| :--- | :--- | :--- |
| A page ranks for relevant queries around positions 5–20. | **Improve the existing page's** usefulness, intent coverage, internal links, and result presentation. | Automatically create another page for the same topic. |
| High impressions but low CTR versus comparable results. | **Investigate and test the title**, page messaging, and snippet relevance on the existing page. | Change titles based only on a sitewide CTR benchmark. |
| A cluster of related queries is growing and existing page already addresses intent. | **Add useful sections, examples, comparisons, or an interactive tool** to the existing URL. | Split every keyword variation into a separate URL. |
| A valuable query cluster has a distinct intent and no suitable landing page. | **Create a new, purpose-built page** passing the 7-factor quality gate. | Create a thin page that merely rephrases an existing one. |
| Hundreds of pages share the same structural or component problem. | **Improve the shared template**, after testing the change on a matched cohort. | Manually patch hundreds of URLs one at a time. |
| Several URLs target essentially the same search intent. | **Differentiate their purpose or consolidate** overlapping content via canonical/301. | Redirect pages just because their impressions are low. |
| Visitors click but rarely convert (high traffic, weak conversions). | **Improve the landing experience, offer, or funnel** (CTA, mobile layout, inputs). | Publish more informational articles to solve a conversion problem. |
| Pages are inaccessible, incorrectly canonicalized, or failing to render. | **Fix the underlying delivery, rendering, or technical defect**. | Keep generating pages that have the same technical blocker. |
| A page has no meaningful demand, unique value, or business purpose. | **Reassess its role; improve, consolidate, retire, or leave it alone**. | Keep expanding the site merely to increase URL count. |

### 2. The Existing-Page Improvement Workflow
For each important URL, check and edit these 6 areas in strict order:
1. **Title & Search-Result Messaging:** Align `<title>`, `<meta name="description">`, and visible `<h1>`. Use accurate intent modifiers (`Free`, `Online`, `Calculator`, `Instant`, Current Year). *Do not inject FAQPage schema expecting FAQ rich snippets (Google removed FAQ rich snippets).*
2. **The First Screen of Content (Above the Fold):** Deliver immediate clarity—can visitors instantly see what the tool does, who it is for, and how to get the answer?
3. **Missing Topic Coverage:** Ingest GSC's actual query variations to add unanswered sub-topics, parameters, or edge-case explanations.
4. **Original Value & Interactive Utility:** Provide what competitors lack: a working deterministic calculator, verified data tables, comparison criteria, or proprietary benchmarks.
5. **Internal Links:** Add crawlable HTML links (`<a href="...">`) with concise, natural anchor text from relevant category hubs.
6. **Conversion Experience:** Fix mobile input reflow, remove dead/rage clicks identified in Clarity, and streamline the primary CTA.

### 3. The New-Page Decision Process & 7-Factor Quality Gate
> **The unit of page creation is a distinct search intent and user task, NOT an individual keyword query.**

A new page is created **ONLY** when an unmet query cluster exists and passes all 7 quality factors:
1. *Demand:* Verified relevant impressions in GSC.
2. *Intent Gap:* No existing page properly satisfies this specific user task.
3. *Business Value:* The audience has a clear, valuable next step (signup, calculation, checkout).
4. *Unique Value:* Adds original proprietary data, code, or interactive tool.
5. *Differentiation:* Distinct from existing URLs; zero cannibalization risk.
6. *Cost & Maintenance:* Can be maintained when underlying data shifts.
7. *Risk & Quality:* Zero thin doorway text; passes Google spam & helpful content standards.

### 4. The 5 Standard Template Archetypes
1. *Editorial / Guide Template:* For informational queries (answers, context, author, citations).
2. *Comparison Template:* For "A vs B" & "Best Alternative" queries (decision criteria, comparison matrix).
3. *Tool / Calculator Template:* For functional calculation queries (interactive inputs, instant outputs).
4. *Directory / Category Template:* For browsing and discovery queries (structured filters, crawlable detail links).
5. *Localized / Market-Specific Template:* For real regional differences (currencies, regulations, service areas).

### 5. Priority Execution Order & The 5 Mandatory Questions
Always execute in this sequence:
1. **P1: Technical Blockers First** (5xx errors, broken canonicals, robots indexation shields).
2. **P2: Valuable Existing Pages Second** (CTR gaps, striking-distance positions 5–20).
3. **P3: Shared Templates Third** (Fix component speed, layout shifts, or mobile UX across hundreds of pages).
4. **P4: New Pages & Tools Fourth** (Genuinely missing intents passing the 7-factor quality gate).

Every recommendation and summary action emitted must answer:
1. *Target Scope:* Which specific URL, page cohort, or shared template should change?
2. *Page-Level Action:* Which of the 6 actions is being executed?
3. *Direct Data Observation & Supporting Evidence:* What exact empirical data observation (telemetry source, metric value, date/period, baseline vs benchmark) triggered this action?
4. *Measurable Target Metric:* What exact measurable outcome should improve?
5. *Scale / Rollback Protocol:* How will you determine whether to scale, revise, or reverse the intervention?

> [!IMPORTANT]
> **Summary Action Traceability Mandate:**
> Every action in an Executive Summary table, Action Queue, or audit report MUST include a dedicated `Direct Data Observation` column and track back to an explicit empirical data point. An action row without a direct data observation is strictly prohibited:
>
> | Priority | Action ID | Decision | Target URL | Direct Data Observation | Proposed Action | Target Metric |
> | :---: | :--- | :--- | :--- | :--- | :--- | :--- |
> | **P1** | `SEO-TECH-001` | `Consolidate Overlapping` | `www.example.com/*` | GSC 2026-10-18: 7 duplicate URLs in "Alternative page with proper canonical tag" | Enforce permanent 301 redirect to apex canonical | 0 duplicate warnings; consolidated authority |
> | **P1** | `SEO-TECH-002` | `Improve Existing Page` | `/receive-sms/pl/` | GSC 2026-10-23: Unparsable structured data (ContactPoint in ItemList) | Convert ContactPoint to ListItem schema | Zero syntax errors; rich result eligibility |
> | **P2** | `SEO-CTR-001` | `Improve Existing Page` | `/calculators/fmcg/` | GSC 28d: query 'fmcg calc' pos 2.1, 1000 imp, CTR 5.0% vs benchmark 15.0% (-10% gap) | Front-load intent modifier in `<title>` & snippet | +100 qualified organic clicks |

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

The orchestrator executes the **5 Specialized Opportunity Detectors**:
- **Detector A (CTR Opportunities):** Identifies positions 1–10 underperforming benchmark CTR:
  $$\Delta C_{\text{CTR}} = I \times \max(0, \text{CTR}_{\text{benchmark}} - \text{CTR}_{\text{current}})$$
- **Detector B (Ranking Opportunities):** Targets striking distance queries (positions 5.0 to 20.0) with high organic impressions.
- **Detector C (Conversion Leakage):** Flags organic landing pages earning clicks but converting below 50% of cluster average, or displaying high PostHog dropoff / Clarity rage clicks.
- **Detector D (Technical Risk):** Detects Cloudflare 5xx spikes, Better Stack downtime, or failing Core Web Vitals (LCP > 2.5s, INP > 200ms, CLS > 0.1).
- **Detector E (Content Expansion & Cannibalization):** Resolves queries split across multiple URLs and identifies rising query clusters lacking authoritative pages.

Every action item is prioritized via:
$$V = \Delta C \times r \times v \qquad\text{Priority Score } P = \frac{V \times q}{E + \text{Risk}}$$

---

### Workflow 2: Period-over-Period Traffic Change Decomposition
When diagnosing traffic gains or declines across 7-day, 28-day, or 90-day intervals:

```bash
python3 scripts/gsc_analyzer.py --compare-periods period0_baseline.json period1_recent.json
```

Separates impression volume changes from snippet engagement changes:
$$\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$$

- **Impression Effect $> 0$, CTR Effect $\ge 0$:** Organic demand or indexation expansion.
- **Impression Effect $\ge 0$, CTR Effect $< 0$:** Snippet appeal deterioration or SERP layout displacement.
- **Impression Effect $< 0$, CTR Effect $\ge 0$:** Broader search demand contraction or lost keyword rankings.
- **Compound Decline:** Critical algorithmic or technical indexation penalty.

---

### Workflow 3: Conversion Leakage & UX Friction Diagnosis
When search clicks fail to convert:

1. **GA4 Audit:** Locate landing pages where organic session volume is high but conversion rate ($r$) is depressed.
2. **PostHog Funnel Scan:** Inspect step-by-step drop-offs to determine where users abandon the journey.
3. **Clarity Friction Investigation:**
   - Filter Clarity session recordings by the affected landing page and device category (`MOBILE` vs. `DESKTOP`).
   - Inspect **Rage Clicks** (repeated rapid clicks on unresponsive controls) and **Dead Clicks** (clicks on unlinked cards or non-interactive headings).
   - Inspect **Scroll Depth**: check if the primary value proposition or CTA is placed below the 50% scroll dropoff line.
4. **Formulate CRO Intervention:** Simplify mobile inputs, sticky-position the primary CTA, or reconcile mismatched search intent.

---

### Workflow 4: Technical Reliability & Incident Correlation
Correlate operational failures with search crawl and ranking anomalies:

1. **Cloudflare Edge Logs:**
   - Monitor 5xx response spikes and 404 error clusters.
   - Verify Googlebot identity using official IP reverse DNS lookups; never trust raw User-Agent headers alone.
2. **Better Stack Downtime Correlation:**
   - Map outage start and end timestamps against GSC crawl activity and impression trendlines.
3. **Core Web Vitals Telemetry (Grafana / Faro):**
   - Ensure LCP $\le 2.5\text{s}$, INP $\le 200\text{ms}$, and CLS $\le 0.1$.
   - Prioritize speed fixes on high-impression commercial pages first.

---

### Workflow 5: Multi-Market & Device Gap Optimization
Segment performance across `country` and `device` dimensions:

```bash
python3 scripts/gsc_analyzer.py --export gsc_multi_dimensional.json
```

- **Geographic Arbitrage:**
  - *High impressions, low CTR in Country X:* Localize snippets, currencies, and vernacular terminology.
  - *High clicks, low conversions in Country X:* Evaluate local pricing elasticity, payment gateway availability, or shipping/language mismatches.
  - *High conversions, modest traffic in Country X:* Prime target for international directory expansion or dedicated localized subdomains.
- **Device Ergonomics:**
  - If mobile CTR is $>25\%$ lower than desktop for the identical query position, audit mobile SERP snippet length (Google truncates mobile titles at ~480px vs ~580px desktop).
  - If mobile conversion rate collapses while desktop thrives, audit responsive form inputs, sticky overlays, and touch target sizes (minimum 44x44px).

---

### Workflow 6: Experiment Design & Evaluation
Never guess whether an SEO or CRO change worked. Use structured experiment protocols:

1. **SEO Experiments (Matched URL Cohorts):**
   - Select 20 comparable URLs; assign 10 to **Treatment** and 10 to **Control (Holdout)**.
   - Apply title, schema, or content changes exclusively to the Treatment group.
   - Evaluate after 28 days using **Difference-in-Differences**:
     $$\text{Net Treatment Lift} = (\text{Treatment}_{t1} - \text{Treatment}_{t0}) - (\text{Control}_{t1} - \text{Control}_{t0})$$
2. **CRO Experiments (Visitor-Level A/B Tests):**
   - Use PostHog to randomize human visitors 50/50 across Control and Variant layouts.
   - Keep underlying HTML markup, headings, and indexable text identical for search crawlers.
   - Measure signup/purchase conversion lift at $p < 0.05$.

---

### Workflow 7: Generative Engine Optimization (GEO) & Machine-Readable Discovery
Ensure search visibility across LLM answer engines (**ChatGPT Search**, **Perplexity**, **Claude**, **Google AI Overviews**):

```bash
# Validate AI search readiness
python3 scripts/geo_evaluator.py --url https://example.com
```

1. **Deploy [`llms.txt`](./templates/llms.txt):** Serve a standardized, markdown-formatted directory at `/llms.txt` and `/llms-full.txt` detailing capabilities, products, and calculation APIs.
2. **Permit AI Crawlers in `robots.txt`:**
   ```txt
   User-agent: GPTBot
   Allow: /

   User-agent: ClaudeBot
   Allow: /

   User-agent: PerplexityBot
   Allow: /
   ```
3. **Structured Schema.org Entity Graphs:**
   - Homepage: Injected unified `@graph` containing `Organization`, `WebSite` with `SearchAction` sitelinks template, and `SoftwareApplication`.
   - Tool & Content Pages: Dynamic `BreadcrumbList` hierarchy and `FAQPage` JSON-LD schema matching visible, accessible FAQ accordions.

---

## Tool & Script Inventory

| Tool / Script | Authoritative Function |
| :--- | :--- |
| [`scripts/seo_growth_intelligence.py`](./scripts/seo_growth_intelligence.py) | **The Master Engine:** Ingests multi-source telemetry, executes 5 opportunity detectors, computes expected values, and emits prioritized Action Queues. |
| [`scripts/gsc_analyzer.py`](./scripts/gsc_analyzer.py) | Multi-dimensional Search Console analyzer for queries, pages, countries, devices, and period-over-period traffic decomposition. |
| [`scripts/setup_observability.py`](./scripts/setup_observability.py) | Scans, validates, heals, and exports telemetry manifests (`DataSourceManifest`) and drop-in tracking snippets. |
| [`scripts/geo_evaluator.py`](./scripts/geo_evaluator.py) | Scores AI agent readiness, evaluates `llms.txt`, and validates Schema.org JSON-LD structured data. |
| [`scripts/run_audit.py`](./scripts/run_audit.py) | High-speed technical crawler pass for status codes, canonical consistency, and crawl budget parameter defense. |
| [`schemas/seo-action.schema.json`](./schemas/seo-action.schema.json) | Standardized JSON Schema for prioritized, auditable SEO and CRO action cards. |
| [`schemas/data-source-manifest.schema.json`](./schemas/data-source-manifest.schema.json) | Declares connection status, freshness watermarks, and capabilities across all 7 telemetry platforms. |
| [`references/gsc_multidimensional_playbook.md`](./references/gsc_multidimensional_playbook.md) | Exhaustive guide on extracting maximum value from GSC dimensions, decomposition math, and query clustering. |
| [`references/seo_growth_os_architecture.md`](./references/seo_growth_os_architecture.md) | The 3-plane system architecture, Cloudflare hybrid storage model, and tool responsibility boundaries. |
| [`references/conversion_diagnosis_and_experimentation.md`](./references/conversion_diagnosis_and_experimentation.md) | Joining search demand to conversions, PostHog funnels, Clarity heuristics, and matched-cohort experimentation. |
| [`templates/seo_action_queue.md`](./templates/seo_action_queue.md) | Executive markdown template for the prioritized action queue. |
| [`templates/experiment_plan.md`](./templates/experiment_plan.md) | Pre-formatted test plan for SEO matched-cohort and CRO visitor-level experiments. |
