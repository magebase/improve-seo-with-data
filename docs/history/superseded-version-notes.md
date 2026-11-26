# Superseded improve-seo-with-data version notes

Preserved verbatim from SKILL.md on 2026-11-26. These sections describe earlier v2.x iterations and are not the active operating contract.

## 11. Wave 64+ Execution Upgrades

Post-wave-63 hardening directives. Every execution wave from wave 64 onward MUST observe these invariants.

### 11.1 Candidate Hygiene Runs Before Enrichment and Scoring (Mandatory)

Resolve redirects BEFORE scoring and SERP enrichment. Never lease a 301/302 URL: a legacy path and its canonical target are the SAME page, and leasing both wastes SERP credits, splits demand signal, and produces duplicate edits. Hard-block utility routes and brand-typo queries pre-DataForSEO.

- `scripts/candidate_hygiene.py` runs inside `collect_features.py` between candidate assembly and the enrichment selection:
  - `resolve_redirects` probes the live site (no-follow) so legacy 301/302 URLs map to canonical; product-side redirect tables (`urls.py` / `RedirectView` / middleware) are supplied by the EXECUTOR via `--redirect-map` JSON (the skill cannot import the saas-factory codebase) and take precedence over live probes; `~/.seo_fleet/redirect_map.json` is auto-loaded when present.
  - `is_valid_seo_candidate` rejects `NON_SEO_PATH_RE` utility/legal/auth/system routes (`/privacy`, `/terms`, `/api`, `/admin`, ...) and brand-stem typos (`incomecanvascom`, `wwwincomecanvascom`, `brand login`) that are navigational, never informational.
  - `canonicalize_and_dedupe_candidates` collapses duplicate `(page, query)` rows post-redirect, SUMMING impressions and clicks and keeping the BEST (minimum) position, so demand signal is de-duplicated, never lost.
- `score_backlog.py` applies the same validity gate as a second defense before leasing.

### 11.2 Two-Tier Lease Backfill (Empty Quota Buckets No Longer Shrink Waves)

Wave-63 leased 21 slots whose quota buckets could not fill the wave; adjudication collapsed to 4 real edits. `lease_tasks` now ranks rows `quota_pass ASC, priority_score DESC`: rows within their type cap are tier 0 (preferred), rows beyond it are tier 1 (backfill), and the wave ALWAYS fills to `limit` from the highest-scoring remaining rows. Family caps and file-target locks stay HARD. At most one task per canonical URL + `action_code` pair exists per wave.

### 11.3 One Unified Fleet Cursor DB (No Per-Domain Fragmentation)

All properties share ONE SQLite cursor: `~/.seo_fleet/fleet_state.db`, keyed by the `domain` column. Per-domain DBs (e.g. wave-63's `incomecanvas.db`) are forbidden: they fragment the backlog cursor, fork the SERP cache, and hide fleet-wide budget burn. `scripts/unify_fleet_db.py` merges legacy per-domain DBs (preserving REJECTED adjudications, summing daily budgets) and retires the source as `<name>.migrated-bak`. The daily DataForSEO budget gate is FLEET-WIDE: ≤150 SERPs/day across all properties (`DEFAULT_DAILY_SERP_BUDGET = 150`).

### 11.4 Stale-Export GSC Fallback Tagging

When GSC access is 403/DENIED (property not verified in the authenticated account), fall back to the newest local export and tag every emitted task and queue with `gsc_source_mode = "stale_export:<YYYY-MM-DD>"` so downstream waves know the demand data is frozen. Max 2 GSC-dependent orphan re-runs on the same static export; after that, shift the property to Tier 3/4 work (orphan routes, internal links, technical hygiene) until live access is restored.

### 11.5 Deterministic Title Tie-Breaker (Demand Frontloading Wins the Stem)

On any title-contract conflict, demand frontloading ALWAYS wins the stem: the `<title>` must START with the demand query stem. When appending the brand suffix (`| Income Canvas`, `| SMSRiver`, ...) pushes the rendered title over 65 characters, the template/title helper MUST auto-drop or abbreviate the suffix (e.g. `| IC`) when the base meta_title alone exceeds 50 characters. Never truncate the demand stem to fit the suffix. Legacy hardcoded assertions that pinned suffix-included lengths get updated to this rule, not deleted.

### 11.6 Scoped Formatting Discipline (Hard Rule)

NEVER run a directory-wide formatter (`ruff format scripts/`, `ruff format .`) in a shared checkout: it rewrites files owned by OTHER agents and either pollutes their uncommitted work or gets swept into your commit. Only format files you are about to stage: `git diff --name-only | xargs ruff format` (or pass your own file list explicitly). Before committing, verify you have not touched foreign files: `git status --short` must list ONLY your task's paths (plus pre-existing churn you never staged).

### 11.7 Deploy Pre-Flight Gate (Hard Rule)

A deploy command MUST be gated on the code it actually ships. Before any worker deploy fires, either (a) assert the checkout IS the integration tip: `[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]` after a fresh `git fetch`, or (b) run the deploy from an explicit detached worktree off `origin/main` (`git worktree add --detach /tmp/deploy-$(date +%s) origin/main`) with runtime config provisioned. A deploy from a stale local ref silently ships the PREVIOUS wave's code while reporting success - caught live in wave 64 only because the rendered-title verification failed. Live verification after every deploy is mandatory, not optional.

### 11.8 Property-Level Budget Floors (No Noisy Neighbors)

The unified cursor DB shares ONE daily SERP budget (`DEFAULT_DAILY_SERP_BUDGET = 150`) across all properties. Every domain holds a GUARANTEED DYNAMIC floor: `floor = min(35, daily_cap // max(1, active_domains))` - 35/day at 1-4 properties, 30/day at 5, 11/day at 13 - so the floors NEVER sum past the total cap (a static 50/day floor starved domain #4 once three domains consumed 3 x 50 = 150; capping at 35 preserves headroom for the shared pool). A property may always spend up to its floor, anything beyond draws from the shared pool (cap minus all active floors), and the total cap always binds. Per-domain spend lives in `dfs_budget_domain (day, domain, spent)`. One hungry domain can never starve a sibling below its floor. Connections already run `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`; never remove them.

### 11.9 Durable Migration Backups (Never /tmp)

Migrated per-domain state DBs are the only record of pre-unification adjudications. `unify_fleet_db.retire_source` archives them into `~/.seo_fleet/backups/<UTC-stamp>_<name>` with a SHA-256 row in `~/.seo_fleet/backups/manifest.jsonl`. NEVER park fleet state backups in `/tmp` (systemd-tmpfiles and reboots wipe it).

### 11.10 Anti-Inflation Impression Aggregation

`candidate_hygiene.canonicalize_and_dedupe_candidates` never blind-SUMs impressions across redirect variants: rows with a `date`/`day` field are MAX-aggregated per `(date, page, query)` and summed across days; dateless rows (aggregated export windows) MAX across twins (an index transition serves one URL variant per impression, so blind SUM inflates volume and deflates true CTR). Clicks SUM (real events) and `ctr` re-derives from the aggregate. Live redirect probes run with `max_hops=3`, a 2.0s timeout cap, and tracking params (`utm_*`, `fbclid`, `gclid`) stripped before canonical lookup.

---

## 12. Outcome-Driven SEO Engine v2: Architectural Specification & Operating Directives

Transforming automated SEO execution into an evidence-driven, outcome-optimizing system. The objective of this engine is not mere code deployment or passing tests, but measurable incremental organic traffic, durable ranking gains, and business conversions.

### 12.1 The Closed-Loop 5-Stage Lifecycle

Every optimization cycle operates through a verified 5-stage closed loop:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   STAGE 1: INGEST & EVIDENCE EXPANSION                 │
│  Multi-tenant isolated GSC data · DataForSEO Standard Queue SERP intel  │
│  Canonical candidate hygiene · Redirect collapse · Zero cross-talk     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                STAGE 2: OPPORTUNITY INTELLIGENCE (EV & LTR)            │
│  Mathematical Expected Value EV(a) · Query Ownership anti-cannibalism   │
│  Decision Classes: SHIP | EXPERIMENT | OBSERVE | NO_ACTION             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│             STAGE 3: CONTENT USEFULNESS & TECHNICAL GATES               │
│  120+ word substantive depth · Anti-vaporware regex check (Invariant F) │
│  Factual claim provenance verification · Doorway distinctiveness       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│           STAGE 4: DEPLOYMENT & 10-POINT TECHNICAL SEO GATE            │
│  Git origin/main sync · Safe deploy · Signed X-SEO-Verify: 1 re-warm   │
│  verify_technical_seo.py (HTTP 200, Title, H1, Canonical, Schema, Tool)│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│            STAGE 5: OUTCOME TRACKING & ADAPTIVE FLEET LEARNING         │
│  Persistent experiment_ledger · Difference-in-Differences vs Controls   │
│  Googlebot recrawl verification · Action win-rate stats feedback loop  │
│  Two-Part Scorecard: Engineering Quality vs Measured SEO Effectiveness │
└────────────────────────────────────────────────────────────────────────┘
```

### 12.2 P0: Outcome Measurement Engine & Difference-in-Differences Experiment Ledger

1. **Persistent Experiment Ledger (`experiment_ledger`):**
   Every deployed task is registered into `experiment_ledger` in `~/.seo_fleet/fleet_state.db` at deployment time (`record_shipped_experiments`). The ledger records:
   - Task metadata: `id`, `domain`, `page`, `query`, `action_code`, `route_family`, `commit_sha`.
   - Baseline performance: `baseline_clicks_28d`, `baseline_impressions_28d`, `baseline_position`, `baseline_ctr`.
   - Deployment timestamps and post-deploy checkpoints (7d, 14d, 28d, 56d).
   - Recrawl proof: `recrawled_at`, `recrawl_evidence_type` (`gsc_impression` or `url_inspection`).
   - Post-deployment metrics: `post_clicks_28d`, `post_impressions_28d`, `post_position`, `post_ctr`.
   - Difference-in-Differences controls: `matched_control_pages` (sibling URLs in the same route family that received no changes).
   - Lift & Confidence: `incremental_clicks_lift`, `incremental_impressions_lift`, `attribution_confidence`.

2. **Googlebot Recrawl Verification (`update_experiment_recrawl`):**
   Evaluating SEO impact before Google recrawls a URL trains models on phantom zeros. A task transitions from `PENDING_RECRAWL` to `RECRAWL_DETECTED` only when:
   - Fresh post-deployment GSC impressions appear on the target URL, or
   - GSC URL Inspection confirms `lastCrawlTime > deployed_at`.

3. **Difference-in-Differences (DiD) Cohort Evaluation (`update_experiment_outcomes`):**
   To isolate genuine SEO lift from sitewide seasonality or Google core algorithm updates, the engine pairs treatment pages with matched control pages:
   $$\Delta_{\text{treatment}} = M_{t,\text{post}} - M_{t,\text{pre}}$$
   $$\Delta_{\text{control}} = M_{c,\text{post}} - M_{c,\text{pre}}$$
   $$\text{DiD Lift} = \Delta_{\text{treatment}} - \Delta_{\text{control}}$$
   Outcomes are evaluated at the end of the 28-day observation window, populating `incremental_clicks_lift` and updating action priors.

### 12.3 P1: Opportunity Intelligence & Economic Expected Value

Instead of raw heuristic ordering, opportunities are scored by mathematical **Economic Expected Value ($EV$)**:

$$EV(a) = P(\text{indexing}) \times P(\text{rank\_improvement}) \times \Delta\text{clicks} \times V(\text{conversion})$$

1. **Parameters & Mathematical Priors:**
   - $P(\text{indexing})$: $0.95$ for existing active routes, $0.70$ for newly created programmatic routes.
   - $P(\text{rank\_improvement})$: $0.75$ for striking-distance queries (positions 4.0–15.0); $0.45$ for positions 15.1–30.0; $0.25$ for positions $>30.0$ or $<4.0$ (already top).
   - $\Delta\text{clicks}$: Estimated from the mathematical position-adjusted CTR curve ($\text{TargetCTR} - \text{CurrentCTR}$) scaled by impression volume.
   - $V(\text{conversion})$: Conversion multiplier ($1.5\times$ for high-intent actions like `convert`, `viewer`, `tool`, `calculator`; $1.0\times$ for informational/navigational).
   - $\text{CannibalizationRisk}$: Looked up dynamically against `query_ownership_map`.
   - $\text{Confidence}$: Derived from sample size (impressions $\ge 100 \implies 0.90$, $\ge 20 \implies 0.75$, $< 20 \implies 0.50$).

2. **Explicit Decision Classes:**
   - **`SHIP`:** High $EV$, low cannibalization risk, high confidence. Proceed with TDD implementation.
   - **`EXPERIMENT`:** Moderate $EV$, testing novel intent or schema variations. Monitored closely via DiD.
   - **`OBSERVE`:** Page was modified within the last 28 days or is currently awaiting recrawl. Zero code changes permitted.
   - **`NO_ACTION`:** Low $EV$, high cannibalization risk, or page is already a top-decile CTR winner. **`NO_ACTION` is a first-class, high-frequency outcome that protects page equity and prevents harmful title churn.**

3. **Priority Score Formulation:**
   $$\text{Priority Score} = \frac{EV \times (1 - \text{CannibalizationRisk}) \times \text{Confidence}}{\text{Implementation Effort}}$$

### 12.4 P2: Query Ownership & Anti-Cannibalization Architecture

To eliminate doorway pages and cross-template cannibalization, each property maintains a persistent `query_ownership_map` in `fleet_state.db`:

1. **Mapping Invariant:** Each distinct query cluster is assigned to exactly ONE primary canonical URL (`upsert_query_ownership`).
2. **Matching Engine (`get_query_owner`):**
   - Exact query match against existing clusters.
   - Cluster containment: if $\ge 75\%$ of the cluster's core tokens are contained within the candidate query, it belongs to the same cluster.
   - Fuzzy Jaccard token similarity ($\ge 0.75$ threshold).
3. **Cannibalization Enforcement:**
   - If a candidate query maps to an owner URL that differs from the candidate page, `cannibalization_risk` is set to $0.85$.
   - Any task on a competing URL with cannibalization risk $\ge 0.80$ is automatically classified as `NO_ACTION` (or converted to `CONSOLIDATE_CANNIBALIZED_URLS` / `INJECT_SECONDARY_H2_ONLY` on the owner page).

### 12.5 P3: Content Usefulness & Factual Claim Provenance Gate

Implemented in `scripts/content_usefulness_gate.py` to ensure user value and E-E-A-T depth:

1. **Anti-Vaporware Regex Ban (Invariant F):** User-facing content must NEVER contain roadmap or status phrases matching `r"(in rollout|coming soon|server-side pipeline|beta pipeline|under construction|placeholder)"`.
2. **Substantive Depth:** Pages must provide at least 120 words of technical, domain-specific body text explaining file architectures, algorithms, or workflow specifications.
3. **Query Intent in Headings:** Headings must explicitly address the query tokens with technical authority (e.g. `<h2>STEP to DXF Conversion: ISO 10303 B-Rep to AutoCAD 2D Projection</h2>`).
4. **Factual Claim Provenance (`claim_evidence_ledger`):**
   - Concrete performance metrics, model architectures, or throughput benchmarks must trace back to an authorized evidence source:
     - `source_code`: Implemented in the codebase (e.g. WASM SIMD, local rendering).
     - `test_suite`: Verified in automated tests.
     - `official_spec`: Published web/industry standard (ISO, W3C, RFC, ASPRS).
     - `measured_benchmark`: Documented benchmark artifact.
   - Unverified speculative marketing hype (`"military-grade"`, `"supercharged quantum"`, `"100x faster than all"`) is rejected.
5. **Anti-Doorway Distinctiveness:** Sibling pages sharing template families must have pairwise Jaccard shingle similarity $< 0.20$ to prevent Google doorway-page demotions.

### 12.6 P4: 10-Point Technical SEO & Indexability Verification Gate

Superficial HTTP 200 checks are insufficient. `scripts/verify_technical_seo.py` (and `improve_seo_rewarm.py --deep-verify`) audits the fully rendered edge DOM:

| Gate | Check Name | Verification Rule | Failure Severity |
| :---: | :--- | :--- | :---: |
| **1** | **HTTP Status** | `status_code == 200`, no redirect hops, no 5xx | `ERROR` |
| **2** | **Rendered Body** | HTML length $\ge 500$ bytes, non-empty `<body>` | `ERROR` |
| **3** | **Title Geometry** | Title exists, $30 \le \text{chars} \le 70$, desktop width $\le 580\text{px}$ | `ERROR` |
| **4** | **Primary H1** | Exactly one `<h1>` tag present representing topic | `ERROR` |
| **5** | **Canonical URL** | Absolute `rel="canonical"` matching request host and path | `ERROR` |
| **6** | **Robots Defense** | No accidental `noindex`, no blocking `X-Robots-Tag` | `ERROR` |
| **7** | **Internal Links** | At least 2 crawlable `<a href="...">` links in content | `ERROR` |
| **8** | **Structured Data** | Valid JSON-LD parsing with `@context` and `@type` | `WARNING` |
| **9** | **Mobile Viewport** | Standard `<meta name="viewport" ...>` tag present | `WARNING` |
| **10** | **Functional Tool** | Interactive tool container, specifications table, or canvas present | `WARNING` |

### 12.7 P5: Adaptive Fleet-Wide Learning & Action Effectiveness

1. **Empirical Action Statistics (`action_effectiveness_stats`):**
   Records empirical win-rates, neutral-rates, loss-rates, and average click lift across the fleet, keyed by `(domain, action_code, route_family)`.
2. **Cross-Property Prior Pooling:**
   Actions that demonstrate high empirical lift on one domain inform the baseline priors of sibling properties.
3. **Multi-Tenant Isolation Invariant (Rule 16):**
   Only normalized mathematical metrics (`action_code`, `route_family`, `win_rate`, `avg_lift`) may be pooled. Raw queries, URL paths, customer content, and tenant databases remain strictly isolated.

### 12.8 P6: Authoritative Two-Part Scorecard Contract

Reports MUST separate engineering delivery from measured business outcomes:

1. **Part 1: Engineering Execution Quality (0–10.0):**
   - Data Integrity & Multi-Tenant Isolation (15%)
   - Opportunity Quality & Intent Mapping (15%)
   - Content Uniqueness & Usefulness (20%)
   - Technical SEO & Indexability (15%)
   - Deployment Hygiene & Cache Re-warm (15%)
   - Quality, TDD & Product Functionality (20%)
2. **Part 2: Measured SEO & Business Effectiveness (0–10.0):**
   - Evaluates actual post-28d GSC data, incremental organic clicks, impressions, and ranking movement.
   - **MANDATORY INVARIANT:** When tasks are inside the 28-day observation window or awaiting Googlebot recrawl, the engine MUST strictly output:
     `**SEO Effectiveness Grade:** **NOT YET MEASURED (Awaiting GSC Recrawl & 28-Day Observation Window)**`
   - **Never manufacture 10/10 SEO effectiveness grades from passing test suites or clean deployments.**

### 12.9 P7: Mandatory Wave Changelog Contract & Automated Wave-Close Gate

No autonomous SEO wave may be marked complete without an authoritative, auditable Markdown report committed to the repository:

1. **Canonical Report Path:**
   `reports/seo-waves/<domain>/wave-<N>-<domain>-changelog.md`  
   *(e.g. `reports/seo-waves/incomecanvas.com/wave-15-incomecanvas-changelog.md`)*

2. **Automated Wave-Close Verification Gate (`scripts/validate_wave_close.py`):**
   ```bash
   python scripts/validate_wave_close.py \
     --report reports/seo-waves/<domain>/wave-<N>-<domain>-changelog.md \
     --domain <domain> \
     --wave <N> \
     --db-path ~/.seo_fleet/fleet_state.db \
     --commit-sha <sha>
   ```
   Wave completion is blocked if:
   - The report file is missing or $< 500$ bytes.
   - Any of the 8 mandatory sections are omitted:
     1. Executive Summary & Authoritative Two-Part Scorecard (Part 1 Engineering Execution + Part 2 Measured SEO)
     2. Reconciled Task Inventory & Ledger Alignment
     3. Strategic Deep-Dive & Intent Analysis (Query ownership, vertical alignment, and factual claim provenance)
     4. Exhaustive File & Configuration Changes (File-by-file diffs and lines modified)
     5. Standardized Test Classification & Quality Verification (Skill Engine vs Wave TDD vs Regression vs Preflight vs Edge Rewarm)
     6. Deployment, Edge Cache & Invariant Compliance (Zone purge, 28-day title locks, pixel geometry, 1440px grid)
     7. Rollback Runbook & Disaster Recovery
     8. Actionable Recommendations for Subsequent Wave
   - **Invariant P6 Breach:** Part 2 claims a numerical score when inside the 28-day recrawl window instead of `NOT YET MEASURED`.
   - **Task Reconciliation Failure:** Shipped tasks in `fleet_state.db` do not appear in the report table.
   - **Rule 32 Violation:** Prohibited unicode emojis are detected anywhere in the report.

3. **Standardized Evidence & Rigor Standard:**
   Different websites produce different technical and content tasks, but **never different standards of evidence or completeness**. Every wave across all fleet domains (`incomecanvas.com`, `openfileconverter.com`, `smsriver.com`, `figiva.com`) must produce reports meeting this identical contract.

---

## 13. Outcome-Driven SEO Engine v2.1: Critical Refinements

Based on empirical findings and adversarial review, version 2.1 introduces seven foundational mathematical and state-machine refinements.

### 13.1 P0 — Correct Experiment Recrawl State & Independent Exposure Tracking
- **The Core Distinction:** Fresh Google Search Console impressions reflect Google's *cached representation* of a URL, NOT proof that Googlebot has recrawled and processed newly deployed code or content changes.
- **Explicit Experiment State Transitions:**
  ```
  DEPLOYED -> CRAWL_PENDING -> RECRAWL_CONFIRMED -> INDEX_STATUS_VERIFIED -> MEASUREMENT_PENDING -> EVALUATED_28D -> EVALUATED_56D -> TERMINAL_EVALUATED
  ```
- **Recrawl Evidence Requirements:**
  - `url_inspection`: GSC URL Inspection API `lastCrawlTime > deployed_at`.
  - `verified_googlebot_log`: Reverse-DNS verified Googlebot access log timestamp $> \text{deployed\_at}$.
- **Exposure Detection:** GSC impressions before verified recrawl populate `exposure_detected_at` but leave `status = 'CRAWL_PENDING'`.

### 13.2 P0 — Calibrated Bayesian Economic Expected Value (EV) Model
Replaces arbitrary point probabilities ($0.75$, $0.25$) and arbitrary multipliers with an empirical Bayesian decision framework:
\\[ EV(a) = \\hat{P}(\\text{success}) \\times \\text{IncrementalBusinessValue} - \\text{ImplementationCost} - \\text{ExpectedRiskCost} \\]
- **Bayesian Smoothed Success Probability:**
  \\[ \\hat{P}(\\text{success}) = \\frac{\\text{successes} + \\alpha}{\\text{total} + \\alpha + \\beta} \\times P(\\text{rank}) \\]
  Where position prior $P(\\text{rank})$ is:
  - Striking distance (pos 4.0–15.0): $0.45$
  - Top 3 (pos 1.0–3.0): $0.35$ (protecting high CTR from volatile shifts)
  - Second-tier tail (pos 15.0–30.0): $0.25$
  - Deep tail (pos $>30.0$): $0.15$
- **Intent-Specific Conversion Probabilities:**
  - Interactive tools / converters / calculators: $P(\\text{conv}) = 0.05$
  - Format comparison / spec sheets: $P(\\text{conv}) = 0.035$
  - Editorial / informational guides: $P(\\text{conv}) = 0.015$
- **Explicit Economic Costs:**
  - Implementation cost: standard \$50/hr normalized against action complexity.
  - Expected risk cost: $\\text{CannibalizationRisk} \\times \\text{BaselineClicks} \\times \\text{ValuePerClick}$.

### 13.3 P0 — Difference-in-Differences (DiD) Statistical Safeguards
To guarantee genuine causal attribution rather than macro-seasonal coincidence:
1. **Minimum Control Cohort Size:** Requires $N_c \\ge 3$ matched sibling URLs in the same route family. If $N_c < 3$, status is classified as `INSUFFICIENT_EVIDENCE` and attribution confidence is capped ($\le 0.40$).
2. **Pre-Treatment Parallel Trends Validation:** Evaluates pre-treatment slope divergence ($[-56d, -28d]$ vs $[-28d, 0d]$). Divergence $> 0.30$ triggers a parallel trends violation limitation.
3. **Contamination Defense:** Controls modified post-treatment are dynamically excluded from the valid control set.
4. **Statistical Uncertainty & Confidence Intervals:** Reports standard errors and 95% confidence intervals (`did_ci_lower`, `did_ci_upper`). Statistically significant lift requires `did_ci_lower > 0.05`.

### 13.4 P1 — Multi-Dimensional Query Ownership & Risk Scoring
Replaces single-metric token containment with multi-dimensional classification:
- **`OWNED`:** Single canonical URL owns intent, functional elements, and $>60\%$ of historical traffic. Cannibalization risk: $0.0$.
- **`POTENTIAL_OVERLAP`:** Shared lexical tokens, distinct format (risk $\\sim 0.20$).
- **`CONFIRMED_COMPETITION`:** Multiple URLs targeting identical user intent without functional distinction (risk $\\sim 0.85$).
- **`DISTINCT_INTENT`:** Related queries with fundamentally different user tasks (e.g. `las point cloud viewer` vs `las to xyz converter`). Low risk ($\le 0.15$).
- **`CONSOLIDATION_CANDIDATE`:** Multiple thin competing pages requiring 301-redirect or canonical consolidation (risk $\\sim 0.90$).

### 13.5 P1 — Page-Type-Specific Content Quality & Usefulness Gate
- **Dynamic Word Count Baselines:**
  - Interactive Tools & Calculators: $40$ words minimum (with verified functional elements).
  - Technical Comparisons: $150$ words minimum.
  - Directories & Hubs: $50$ words minimum.
  - Editorial & Guides: $200$ words minimum.
- **Boilerplate Stripping:** `<header>`, `<nav>`, `<footer>`, `<dialog>`, and search forms are stripped before computing 3-shingle Jaccard distinctiveness against sibling pages.
- **Broadened Authority Claim Provenance:** Automatically recognizes and verifies government regulations (IRS, IRC, CFR, ACA), tax years, standard jurisdictions (US, UK, EU, CA), and official technical specifications (ISO, ASPRS, RFC, W3C, NIST).

### 13.6 P1 — Technical SEO 10-Point Gate & Soft-404 Detection
1. **HTTP Status & Soft-404:** Rejects HTTP 200 responses containing soft-404 signatures (`"404 not found"`, `"page not found"`, `"tool unavailable"`).
2. **Desktop Title Pixel Geometry:** Titles exceeding $580\\text{px}$ produce an advisory `WARNING`, never a fatal deployment-blocking error.
3. **Functional Utility:** Tools must render interactive inputs, canvas, dropzones, or tables.
4. **Crawlable Internal Links:** Requires $\\ge 2$ crawlable relative internal links.
5. **Mobile Viewport & Structured Data:** Standard valid viewport and syntax-checked JSON-LD.

### 13.7 P1 — Uncertainty-Aware Beta-Binomial Fleet Learning
Replaces naive win ratios ($4/5 = 80\%$) with Beta-Binomial Bayesian smoothing:
\\[ \\text{WinRate}_{\\text{smoothed}} = \\frac{\\text{successes} + \\alpha}{\\text{total} + \\alpha + \\beta} \\]
- Weighted by confidence: $\\text{ConfidenceWeight} = \\min(1.0, \\sqrt{\\text{total} / 25})$.
- Prevents small exploratory samples from displacing high-evidence established actions ($60/100$) in backlog ranking.

### 13.8 Standardized Wave Changelog Generation
- Generated via `scripts/generate_wave_changelog.py`.
- Reconciles Git diffs (`git show --name-status`, `git show --stat`), task backlog cursor (`fleet_state.db`), and edge re-warm receipts (`improve_seo_rewarm.py`).
- Embeds all 20 required audit dimensions cleanly across the 8 mandatory top-level headings checked by `scripts/validate_wave_close.py`.

---

## 14. Outcome-Driven SEO Engine v2.2: Statistical and Operational Maturity

The Outcome-Driven SEO Engine v2.2 upgrades the empirical scoring, causal inference, and verification gates from v2.1 to full mathematical and operational maturity.

### 14.1 P0 — Calibrated Bayesian Expected Value & Holdout Evaluation (`score_backlog.py`)
1. **Statistical Decomposition:**
   Opportunities return explicit decomposition:
   - `posterior_success_prob` ($\hat{p}$): Bayesian posterior probability incorporating position band and action effectiveness.
   - `is_cold_start`: Boolean flag indicating whether the action is operating on prior mean vs empirical trials.
   - `credible_interval_95`: Exact $[ci_{\text{lower}}, ci_{\text{upper}}]$ interval.
   - `evidence_weight`: $\min(1.0, \sqrt{\text{sample\_size} / 25})$.
   - `model_type`: `"BAYESIAN_HIERARCHICAL"` vs `"COLD_START_PRIOR"`.
   - `calibration_status`: `"CALIBRATED"` vs `"UNMEASURED"`.
2. **Configurable Economic Parameters (`EconomicConfig`):**
   - `labor_hourly_rate`: Default \$50.0/hr (customizable per team).
   - `value_per_conversion`: Default \$10.0 (customizable per business model).
   - `currency`: Default `"USD"`.
   - `time_horizon_days`: Default 90 days.
   - `success_click_growth_threshold`: Default 0.10 (+10% relative click growth).
3. **Temporal Holdout Probability Calibration (`evaluate_temporal_holdout_calibration`):**
   Across matured, graded experiments ($\ge 28$ days post-deployment), computes:
   - **Brier Score:** $\frac{1}{N}\sum (\hat{p}_i - y_i)^2$. Brier score $\le 0.25$ indicates strong calibration.
   - **Log Loss:** $-\frac{1}{N}\sum [y_i \ln(\hat{p}_i) + (1-y_i) \ln(1-\hat{p}_i)]$.
   - **5-Bin Reliability Diagram:** Binned into $[0, 0.2)$, $[0.2, 0.4)$, $[0.4, 0.6)$, $[0.6, 0.8)$, $[0.8, 1.0]$ tracking mean predicted vs observed win rates and absolute calibration error.

### 14.2 P0 — Small-Sample Student's $t$ DiD & Commercial Negligibility (`fleet_state.py`)
1. **Pre-Treatment Parallel Trends Divergence:**
   $$\text{PreTrendDivergence} = \left| \frac{T_{P2} - T_{P1}}{\max(T_{P1}, 1.0)} - \frac{C_{P2} - C_{P1}}{\max(C_{P1}, 1.0)} \right|$$
   where $P1=[-56d, -28d]$ and $P2=[-28d, 0d]$. If divergence $> 0.30$, flags `PARALLEL_TRENDS_VIOLATION` limitation and caps attribution confidence ($\le 0.35$).
2. **Degrees of Freedom Small-Sample Correction:**
   When control cohort size $N_c < 5$, standard normal $1.96$ is replaced with exact Student's $t$ two-tailed 95% critical values ($N_c=4 \implies 2.776$, $N_c=3 \implies 3.182$, $N_c \le 2 \implies 4.303$) to prevent small-sample overconfidence.
3. **Commercial vs. Statistical Significance:**
   - **`STATISTICALLY_SIGNIFICANT_LIFT`:** $ci_{\text{lower}} > 0.05$ AND incremental clicks $\ge 2.0$.
   - **`COMMERCIALLY_NEGLIGIBLE_LIFT`:** $ci_{\text{lower}} > 0.05$ BUT incremental clicks $< 2.0$. Distinguishes minor mathematical variance from actionable business lift, excluding negligible changes from biasing future action effectiveness.
   - **`INSUFFICIENT_EVIDENCE`:** Assigned when $N_c < 3$, parallel trends violate ($>0.30$), or observations have not completed 28 days.

### 14.3 P0 — Real Functional Product Verification (`verify_product_functionality.py` & Gate 10)
Replaces superficial tag sniffing with real domain-specific functional proofs:
1. **OpenFileConverter:** WebAssembly/Worker client-side conversion pipelines (`FileReader`, `readAsArrayBuffer`, `Uint8Array`, `wasm`, `Worker`), interactive dropzone/file-inputs, and format pair integrity.
2. **IncomeCanvas (Financial & Tax Calculators):**
   - **2026 Excess APTC 100% Repayment Rule:** Under IRC § 36B, statutory repayment limitation caps sunset for Tax Year 2026; taxpayers must repay 100% of excess advance payments regardless of household income percentage.
   - **Statutory Hour Definitions:** 130 hours/month full-time classification threshold (IRC § 4980H(c)(4)) vs. 120 hours/month divisor for Full-Time Equivalent (FTE) aggregate hours (IRC § 4980H(c)(2)(E)).
   - **Section 179 Depreciation:** $1,250,000 maximum deduction cap and $3,130,000 phaseout ceiling for Tax Year 2026, with dollar-for-dollar reduction logic.
   - **WACC Formulation:** Equity weighting, debt weighting, and after-tax interest tax shield $(1 - T_c)$.
3. **SMSRiver:** Active virtual number table and polling event stream listeners.
4. **Directories:** Structured links ($\ge 3$) and search/filter mechanisms.
5. **Gate 10 in `verify_technical_seo.py`:** Dispatches to `verify_product_functionality.py` and treats functional failure as a fatal `ERROR` on tool/calculator/converter archetypes.

### 14.4 P1 — Multi-Dimensional Query Ownership & SERP Jaccard Overlap
1. **Exact SERP Jaccard Overlap:**
   $$J(\text{Top10}_A, \text{Top10}_B) = \frac{|\text{Top10}_A \cap \text{Top10}_B|}{|\text{Top10}_A \cup \text{Top10}_B|}$$
   Overlap $\ge 0.50$ confirms identical search intent in Google's index.
2. **Operational Invariants:** 90-day observation window, segmented by device and country, with minimum thresholds ($\ge 100$ impressions, $\ge 5$ clicks).
3. **Harmless Dual-Ranking vs Harmful Cannibalization:**
   - **`HARMLESS_DUAL_RANKING`:** Both URLs rank in top 5 positions with stable combined CTR $\ge$ benchmark (risk $0.05$). Search footprint is expanded without self-competition.
   - **`CONFIRMED_COMPETITION`:** URLs oscillate / rank-bounce, or combined CTR drops $> 25\%$ below expected benchmark (risk $0.85$).
   - **`CONSOLIDATION_CANDIDATE`:** Performance evidence confirms sustained traffic degradation ($> 40\%$ CTR drop), requiring 301-redirect or canonical consolidation (risk $0.90$).

### 14.5 P1 — 3-Tier Hierarchical Bayesian Fleet Learning
1. **Tier 1 (Global Fleet Prior):** $\text{Beta}(1.5, 3.5)$ with prior mean $0.30$.
2. **Tier 2 (Property-Specific Prior):** Aggregated across all route families for the domain.
3. **Tier 3 (Position-Stratified Prior):** Stratified by baseline ranking band:
   - `top_3` ($0 < \text{pos} \le 3.0$)
   - `striking_4_15` ($3.0 < \text{pos} \le 15.0$)
   - `tail_15_30` ($15.0 < \text{pos} \le 30.0$)
   - `deep_tail_30_plus` ($\text{pos} > 30.0$ or unranked)
4. **Immature & Inconclusive Exclusions:** Experiments $< 28$ days elapsed and unmeasured/inconclusive outcomes (`INSUFFICIENT_EVIDENCE`) are strictly excluded from updating action effectiveness.

### 14.6 P0 — Changelog Gate & Negative Validation (`validate_wave_close.py` v2.2.0)
- Enforces `--version` reporting `validate_wave_close.py v2.2.0`.
- Dirty worktree rejection: `git status --porcelain` must be clean before wave sign-off unless explicitly overridden with `--allow-dirty`.
- Negative validation against missing task IDs, non-existent Git commit SHAs, omitted modified files, missing test run evidence in Section 5, and Rule 32 emojis.

---

## 15. Outcome-Driven SEO Engine v2.2.1: Evidence and Statistical Integrity

The Outcome-Driven SEO Engine v2.2.1 establishes rigorous empirical truth, statutory calculation reality, and mathematical statistical integrity across all fleet operations.

### 15.1 P0.1 — Statutory Reality & Section 179 Limits (IRS Publication 946)
Replaces stale 2025 limits with verified statutory limits under current IRS Publication 946:
1. **Tax Year 2026 Statutory Limits:**
   - **Maximum Deduction Cap:** $2,560,000.
   - **Phaseout Threshold:** $4,090,000.
   - **Full Phaseout Ceiling:** $6,650,000 ($4,090,000 + $2,560,000).
   - **Qualifying SUV Deduction Limit:** $32,000.
   - **Reduction Mechanism:** Dollar-for-dollar reduction:
     $$\text{Reduction} = \max(0, \text{Cost} - \$4{,}090{,}000)$$
     $$\text{AvailableCap} = \max(0, \$2{,}560{,}000 - \text{Reduction})$$
     $$\text{BaseDeduction} = \min(\text{Cost}, \text{AvailableCap})$$
2. **Tax Year 2025 Statutory Limits:**
   - **Maximum Deduction Cap:** $1,250,000.
   - **Phaseout Threshold:** $3,130,000.
   - **Full Phaseout Ceiling:** $4,380,000.
   - **Qualifying SUV Deduction Limit:** $30,500.
3. **Strict Statutory Invariant:**
   Presenting stale 2025 limits ($1,250,000 / $3,130,000) on 2026 calculators constitutes a fatal validation failure (`Section 179 Stale Limit Invariant Failure`).

### 15.2 P0.2 — Calibrated Bayesian Expected Value & Holdout Evaluation (`score_backlog.py`)
1. **Brier Skill Score (BSS) vs Base-Rate Baseline:**
   Brier score $\le 0.25$ alone does NOT qualify a model as calibrated when base rates are low. Enforces Brier Skill Score:
   $$BSS = 1 - \frac{BS_{\text{model}}}{BS_{\text{baseline}}}$$
   where $BS_{\text{baseline}} = \bar{y}(1 - \bar{y})$ (the sample variance of observed outcomes).
2. **Baseline Benchmarks & Calibration Parameters:**
   - **Baseline Log Loss:** $LL_{\text{baseline}} = -[\bar{y}\ln(\bar{y}) + (1-\bar{y})\ln(1-\bar{y})]$.
   - **Calibration Intercept ($a$) and Slope ($b$):** Estimated via logistic regression on logits ($z = \text{logit}(p)$). Well-calibrated models exhibit $a \approx 0$ and $b \approx 1$.
   - **Sample Size Gate ($N \ge 20$):** Calibration verdicts require at least 20 matured experiments. When $N < 20$, verdict is strictly `INSUFFICIENT_SAMPLE_SIZE_FOR_CALIBRATION`. Only when $N \ge 20$, $BSS > 0$, and $BS \le 0.25$ is a model labeled `WELL_CALIBRATED`.
3. **Full EV Decomposition (`ev_decomposition`):**
   Every scored opportunity returns an explicit mathematical derivation:
   `expected_delta_clicks`, `conversion_rate`, `value_per_conversion`, `time_horizon_days`, `gross_business_value`, `labor_hours`, `labor_hourly_rate`, `implementation_labor_cost`, `cannibalization_risk`, `expected_risk_cost`, `posterior_success_probability`, and `net_expected_value`.
4. **Canonical Outcome Reconciliation (`determine_canonical_outcome`):**
   Standardized mapping across causal DiD estimation and empirical growth:
   - `STATISTICALLY_SIGNIFICANT_LIFT`: Lower 95% bound $> 0.05$ and incremental clicks $\ge$ commercial threshold.
   - `COMMERCIALLY_WORTHWHILE_LIFT`: Incremental clicks $\ge$ commercial threshold and relative lift $\ge 10\%$.
   - `COMMERCIALLY_NEGLIGIBLE_LIFT`: Positive lift or lower bound $> 0$, but incremental clicks $<$ commercial threshold.
   - `STATISTICALLY_SIGNIFICANT_DROP`: Upper 95% bound $< -0.05$.
   - `INCONCLUSIVE_EVIDENCE`: Confidence interval spans zero or control cohort $< 3$.
   - `NEUTRAL_NO_EFFECT`: Confidence interval tightly bounds zero.

### 15.3 P0.3 — Exact Poisson-Normal DiD Estimator (`fleet_state.py`)
1. **Exact Degrees of Freedom ($df = N_c - 1$):**
   For sample variance $s_C^2$ across $N_c$ controls, degrees of freedom are $df = \max(1, N_c - 1)$:
   - $N_c = 2 \implies df = 1, t = 12.706$
   - $N_c = 3 \implies df = 2, t = 4.303$
   - $N_c = 4 \implies df = 3, t = 3.182$
   - $N_c = 5 \implies df = 4, t = 2.776$
   - $N_c = 6 \implies df = 5, t = 2.571$
   - $N_c \ge 31 \implies df \ge 30, t = 1.960$
2. **Exact Poisson-Normal Standard Error:**
   Removed arbitrary $0.5$ scaling multiplier. Standard error is derived directly from count variances:
   $$SE = \sqrt{\frac{Y_{T1} + Y_{T0}}{\max(Y_{T0}, 1)^2} + \frac{s_C^2}{\max(1, N_c)}}$$
3. **Multi-Period Event Study Diagnostics (`check_event_study_parallel_trends`):**
   Evaluates consecutive pre-treatment periods ($[-56d, -42d]$, $[-42d, -28d]$, $[-28d, -14d]$, $[-14d, 0d]$) to prove parallel trends hold before treatment. Divergence $> 0.30$ triggers `PARALLEL_TRENDS_VIOLATION`.
4. **Configurable Commercial Threshold:**
   Replaces hardcoded 2.0 clicks with configurable `min_incremental_clicks` per property.

### 15.4 P0.4 — True Product Functional Testing (`verify_product_functionality.py`)
Crucial Distinction:
- `FUNCTIONALLY_VERIFIED`: Real input/output executed and mathematically/structurally validated.
- `IMPLEMENTATION_PRESENT`: Static HTML/script element presence verified.
- `VERIFICATION_FAILED`: Required product logic or statutory limits missing or invalid.

Reference Engines Implemented:
1. **OpenFileConverter (`execute_converter_pipeline`):** Real byte-level conversions with magic byte validation (BMP $\to$ PNG with `\x89PNG`, STEP $\to$ STL with `solid ...`, DOCX $\to$ PDF with `%PDF`, and malformed byte rejection).
2. **IncomeCanvas Financial Engines:**
   - Section 179 (`calculate_section_179_deduction`): 2025 vs 2026 statutory limits, SUV limit, business income limit.
   - ACA APTC (`calculate_aca_excess_aptc_repayment`): 2026 100% full repayment vs 2025 capped repayment.
   - Corporate WACC (`calculate_wacc`): Weighting and after-tax interest tax shield $(1 - T_c)$.
3. **Figiva (`calculate_figiva_gpa`):** Collegiate 4.0 weighted cumulative GPA scale.
4. **SMSRiver (`verify_smsriver_operational_pipeline`):** E.164 phone verification and JSON polling message extraction with OTP verification.

### 15.5 P1 — Multi-Dimensional Query Ownership & Fleet Learning
1. **Query Classification Terminology:**
   - `HIGH_SERP_OVERLAP`: Shared SERP Top 10 results ($\ge 0.50$) without full canonical ownership.
   - `LOW_DATA_UNCERTAIN`: Queries with $\le 100$ impressions and $\le 5$ clicks assigned uncertain risk ($\sim 0.15$) rather than false certainty.
   - `CONSOLIDATION_CANDIDATE`: 301 consolidation strictly requires multiple corroborating signals (shared SERP $\ge 0.50$, split impressions, and declining traffic trend).
2. **Hierarchical Fleet Learning Structure:**
   Preserves 5-tier partial pooling without double-counting:
   - Tier 5: Position Band + Route Family + Action + Property
   - Tier 4: Route Family + Action + Property
   - Tier 3: Action + Property (pooled across route families)
   - Tier 2: Action pooled across Fleet (all domains)
   - Tier 1: Global Prior $\text{Beta}(1.5, 3.5)$

### 15.6 P1 — Wave-Close Gate & Auditor (`validate_wave_close.py` v2.2.1)
1. **Version Reporting:** `--version` reports `validate_wave_close.py v2.2.1`.
2. **Worktree Waiver Requirement:** `--allow-dirty` requires an explicit `--waiver-reason` and lists affected dirty/untracked files.
3. **Test Summary Verification:** Section 5 must report standardized test results with explicit `Passed`, `Failed`, and `Skipped` (or `XFailed`) classifications.
4. **Deployment & Re-Warm Arithmetic Reconciliation:** Mathematically impossible claims (e.g. 36/38 paths with 100% success) are strictly rejected.

## 16. Outcome-Driven SEO Engine v2.2.2: Statutory Attribution & Multi-Commit Audit Reconciliation

The Outcome-Driven SEO Engine v2.2.2 enforces exact federal statutory citations, multi-regime healthcare calculation models, precise macroeconomic disclosures, and multi-commit Git diff reconciliation.

### 16.1 P0.1 — ACA Excess APTC Repayment Regimes (ARPA 2020 Relief & IRC § 36B Sunset)
1. **Three-Regime Excess Advance Premium Tax Credit (APTC) Engine:**
   - **Tax Year 2020 (ARPA § 9662 / IRC § 36B(f)(2)(B)(iii)):** Complete statutory suspension of excess APTC repayment. Any excess subsidy received is fully protected ($0.00 repayment liability regardless of income level or excess amount).
   - **Tax Years 2021–2025 (IRC § 36B(f)(2)(B)(i) & Form 8962 Line 28):** Statutory repayment limitation caps apply based on household income as a percentage of the Federal Poverty Line (FPL) (e.g. Under 200% FPL: $375 single / $750 family; 200%-300% FPL: $950 single / $1,900 family; 300%-400% FPL: $1,575 single / $3,150 family). Above 400% FPL prior to 2026, full repayment was required unless enhanced subsidies applied.
   - **Tax Year 2026 Onward (IRC § 36B Sunsets):** Form 8962 Lines 28-29 reserved; statutory limitation caps expire. Any excess APTC must be repaid in full (100% uncapped repayment liability) up to total advance credits received.
2. **Statutory Engine Verification:**
   `scripts/verify_product_functionality.py` enforces regression verification across all three distinct historical and future statutory regimes.

### 16.2 P0.2 — Statutory Precision for ACA FTE Compliance
All ACA shared responsibility computations and advisory materials must cite exact statutory and regulatory authorities:
1. **Applicable Large Employer (ALE):** IRC § 4980H(c)(2)(A) (average of at least 50 full-time employees including FTEs on business days during the preceding calendar year).
2. **Full-Time Employee (FT):** IRC § 4980H(c)(4)(A) (employed on average at least 30 hours of service per week).
3. **Monthly Equivalency Standard:** 26 C.F.R. § 54.4980H-1(a)(21)(ii) (130 service hours in a calendar month treated as the monthly equivalent of 30 service hours per week).
4. **FTE Monthly Divisor:** IRC § 4980H(c)(2)(E) (aggregate non-full-time service hours up to 120 per employee divided by 120).

### 16.3 P1.1 — Insurance Data Disclosure & Risk Cohorts (NAIC 2024 Benchmark)
1. **Macroeconomic vs Underwriting Distinction:** NAIC state average expenditures are macroeconomic statewide market benchmarks from the NAIC 2024 Auto Insurance Database Average Premium Supplement (released October 1, 2026), NOT individual underwriting quotes.
2. **Custom Derived Cohorts:** Analytical risk tiers (e.g. Prime Preferred, Standard Commuter, Urban Congestion, High Risk Subprime, Young Driver Novice) must be explicitly identified as *custom derived analytical groupings* categorized by NAIC state expenditure percentiles, NOT official NAIC-defined risk cohorts.

### 16.4 P1.2 — Unsecured Personal Loan Borrower Scenarios & Financing Disclaimers
1. **Underwriting Assumptions:** High-balance ($100,000) personal loan scenarios must document underwriting qualification criteria (FICO $\ge 760$, income $\ge \$150,000$, DTI $\le 36\%$, origination fees $1\%\text{--}8\%$).
2. **Mandatory Conspicuous Disclosure:**
   `> **Illustrative borrower profile and financing assumptions. Actual lender eligibility, rates, fees and borrowing limits vary.**`

### 16.5 P1.3 — Multi-Commit Audit Reconciliation (`validate_wave_close.py` v2.2.2 & `generate_wave_changelog.py`)
1. **Version Reporting:** `--version` reports `validate_wave_close.py v2.2.2`.
2. **Multi-Commit Range Support:**
   `validate_wave_close.py` and `generate_wave_changelog.py` support `--commit-range <start_sha>..<end_sha>` (as well as comma-separated commit SHAs). The reconciliation engine parses `git diff --name-only <start_sha>..<end_sha>` across the entire commit sequence, guaranteeing zero omitted file modifications in Section 4.
3. **Execution Gate Enforcement:** Wave-close fails if any file modified across the multi-commit delivery range is missing from Section 4.

---

## 17. Outcome-Driven SEO Engine v2.2.3: DOM Structural Integrity, Annual Statutory Indexing & Pre-Flight Gate Architecture

The Outcome-Driven SEO Engine v2.2.3 enforces semantic HTML rendering integrity, exact annual statutory inflation indexing, inclusive Git commit-range reconciliation, and consolidated pre-flight verification gates across all production properties.

### 17.1 P0.1 — DOM Structural Integrity Gate & Markdown Sanitization (`verify_dom_structural_integrity` & `validate_rendered_articles_dom_integrity`)
1. **Semantic HTML Invariants (Zero Raw Markdown Leakage):**
   - **Markdown Pipe-Tables:** Raw pipe-delimited tables (`| col1 | col2 |`) MUST never be wrapped inside `<p>` tags. They must compile to semantic `<div class="overflow-x-auto"><table class="..."><thead>...<tbody>...</table></div>`.
   - **Blockquote Entities:** Leading markdown blockquote characters (`>`) MUST never be entity-escaped to literal `&gt;` inside `<p>` prose tags. They must compile to semantic, accessible `<blockquote class="...">` styled callout containers.
   - **Boundary Hygiene:** Paragraph text immediately preceding or following pipe tables and blockquotes must maintain double newline (`\n\n`) boundaries during parsing and template compilation.
2. **Pre-Deploy Structural Lint Enforcement:**
   `scripts/deploy_seo_alpha_worker.py` and `scripts/verify_product_functionality.py` execute `validate_rendered_articles_dom_integrity` and `verify_dom_structural_integrity` across all catalog and programmatic articles. Any unparsed table (`<p>|`), literal blockquote (`<p>&gt;`), raw bold (`<p>**...**</p>`), or orphan table separator (`| --- |`) constitutes a fatal pre-flight build failure.

### 17.2 P0.2 — Annual Statutory Inflation Indexing for ACA Excess APTC Repayment (2021–2026+)
Replaces static repayment caps with the exact annual IRS Revenue Procedure indexing schedules under IRC § 36B(f)(2)(B)(i):
1. **IRS Annual Revenue Procedures:**
   - **Tax Year 2020 (ARPA § 9662):** $0.00 repayment required (statutory suspension).
   - **Tax Year 2021 (Rev. Proc. 2020-36):** <200% FPL: $325 (Single) / $650 (Other); 200–300% FPL: $800 (Single) / $1,600 (Other); 300–400% FPL: $1,350 (Single) / $2,700 (Other).
   - **Tax Year 2022 (Rev. Proc. 2021-36):** <200% FPL: $325 (Single) / $650 (Other); 200–300% FPL: $825 (Single) / $1,650 (Other); 300–400% FPL: $1,400 (Single) / $2,800 (Other).
   - **Tax Year 2023 (Rev. Proc. 2022-34):** <200% FPL: $350 (Single) / $700 (Other); 200–300% FPL: $900 (Single) / $1,800 (Other); 300–400% FPL: $1,500 (Single) / $3,000 (Other).
   - **Tax Year 2024 (Rev. Proc. 2023-29):** <200% FPL: $375 (Single) / $750 (Other); 200–300% FPL: $950 (Single) / $1,900 (Other); 300–400% FPL: $1,575 (Single) / $3,150 (Other).
   - **Tax Year 2025 (Rev. Proc. 2024-35):** <200% FPL: $375 (Single) / $750 (Other); 200–300% FPL: $975 (Single) / $1,950 (Other); 300–400% FPL: $1,625 (Single) / $3,250 (Other).
   - **Tax Year 2026 Onward (Permanent IRC § 36B Split):**
     * **$\ge 400\%$ FPL (Subsidy Cliff Expiration):** Temporary IRA expansion sunsets under permanent IRC § 36B(c)(1)(A). Taxpayers exceeding 400% FPL are ineligible for credits and must repay 100% of excess APTC with NO statutory limitation cap.
     * **$< 400\%$ FPL (Permanent Statutory Limitation Schedule):** Statutory limitation schedule remains permanent under IRC § 36B(f)(2)(B)(i) as indexed by Rev. Proc. 2025-32: <200% FPL: $400 (Single) / $800 (Other); 200–300% FPL: $1,000 (Single) / $2,000 (Other); 300–400% FPL: $1,675 (Single) / $3,350 (Other).

### 17.3 P1.1 — Section 179 Statutory Authority Citations by Tax Year
`financial_methodology_registry.py` strictly disaggregates statutory citations by tax year:
- **Tax Year 2024:** IRS Revenue Procedure 2023-34 ($1,220,000 cap; $3,050,000 phaseout).
- **Tax Year 2025:** IRS Revenue Procedure 2024-40 ($1,250,000 cap; $3,130,000 phaseout).
- **Tax Year 2026:** Public Law 119-21 / IRS Revenue Procedure 2025-32 ($2,560,000 cap; $4,090,000 phaseout).

### 17.4 P1.2 — Inclusive Commit-Range Resolution (`<start_sha>^..<end_sha>`)
Git range notation `A..B` by definition computes changes between tree `A` and tree `B`, omitting files modified in commit `A` itself. Both `validate_wave_close.py` (v2.2.3) and `generate_wave_changelog.py` implement inclusive parent-range normalization:
$$\text{commit\_range} = A\text{..}B \implies A\text{^\;..}B$$
For root commits (commits without a parent), the diff automatically resolves against git's empty tree hash `4b825dc642cb6eb9a060e54bf8d69288fbee4904` or root commit fallback. This guarantees that all files modified in the initial commit of a delivery wave are captured in Section 4.

### 17.5 P2.1 — Synchronous Git Operations & Execution Hygiene
- **No Backgrounding Git Operations:** All `git commit`, `git add`, `git diff`, and `git push` operations MUST execute synchronously with explicit wait timeouts and status checks. Backgrounding git mutations introduces dirty worktree races, index lock contention (`.git/index.lock`), and partial commit hazards.
- **Unified Wave Gate (`scripts/run_wave_gate.py`):** Consolidates TDD suites, DOM structural linting, statutory engine verification, and wave-close report auditing into a single pre-flight executable, ensuring zero fragmented verification cycles.

---

## 18. Outcome-Driven SEO Engine v2.3.0: Machine Learning Transparency, Tree SHAP Attributions & Mandatory Decision Summaries

The Outcome-Driven SEO Engine v2.3.0 establishes complete machine learning auditability and explainability across all invocations, backlog scoring runs, and wave closeout changelogs.

### 18.1 P0.1 — Explicit Invocation Output Contract (`score_backlog.py`)
1. **Always-Visible Model Attribution Summary:**
   Every invocation of `score_backlog.py` (both the fast cursor lease and full feature scoring) constructs and prints the `MACHINE LEARNING MODEL DECISION & SHAP ATTRIBUTION SUMMARY` block.
2. **Explicit Attributions Per Leased Task:**
   - **Task ID:** Database identifier mapped directly to `atomic_task_backlog`.
   - **Queue Slot:** Exploit vs Explore designation (85/15 ratio).
   - **Action Code & Target URL:** Prescribed atomic technical change.
   - **ML Rank Score:** Raw LightGBM margin evaluated under LambdaMART `rank_xendcg`.
   - **Expected Value ($):** Calibrated 30-day click and conversion value.
   - **Top SHAP Drivers:** 3 highest-magnitude Tree SHAP feature attributions (`+` for rank-lifting signals, `-` for deficit penalties).
   - **Selection Rationale:** Plain-language explanation specifying why the model chose this task over competing candidates.
3. **Persistent Fleet State Enrichment:**
   When tasks are leased or merged into `data/action_queue.json`, each task payload embeds `top_shap_drivers` and `selection_rationale`.

### 18.2 P0.2 — Mandatory Changelog Section `Part 1.1: Machine Learning Model Decisions & Feature Attributions`
1. **Automated Changelog Generation (`generate_wave_changelog.py`):**
   Natively generates subsection `### Part 1.1: Machine Learning Model Decisions & Feature Attributions (Tree SHAP)` between Engineering Execution Quality and Measured SEO Effectiveness.
2. **Documented Model Architecture:**
   - Booster architecture (`LGBMRanker rank_xendcg`).
   - Residual baseline equation (`init_score = log10(impressions + 1) * (TargetCTR - CurrentCTR) * ConvValue`).
   - Monotone directional constraints across the 14-feature vector.
3. **Reconciled Task Attribution Table:**
   Includes the full tabular audit trail mapping every shipped task ID to its exact model score, expected value, queue slot, top SHAP drivers, and selection rationale.

### 18.3 P0.3 — Automated Wave-Close Gate Enforcement (`validate_wave_close.py` v2.3.0)
1. **Blocking Verification Gate:**
   `validate_wave_close.py` strictly validates the existence of Section `Part 1.1: Machine Learning Model Decisions & Feature Attributions`. Reports missing this section or lacking the task attribution table fail wave sign-off.
2. **Version Reporting:**
   `validate_wave_close.py --version` reports `validate_wave_close.py v2.3.0`.
