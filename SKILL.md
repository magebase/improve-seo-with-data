---
name: improve-seo-with-data
description: >-
  The authoritative, multi-source SEO Growth & Conversion Operating System. Use this skill whenever you need to audit, diagnose, optimize, or scale a website's organic search visibility, conversion funnels, or AI search presence using real data. Automatically fetches, correlates, and joins Google Search Console (GSC joint page+query performance, devices, indexation), Microsoft Clarity (heatmaps, rage clicks, dead clicks, scroll depth drop-offs), PostHog (organic conversion funnels and user journeys), Cloudflare (TTFB, Core Web Vitals LCP/INP/CLS, edge 5xx/404 logs), Better Stack (uptime incidents), and live SERP competitor DOMs. Enriches every opportunity with external DataForSEO SERP intelligence (weak-spot detection, SERP feature crowding, cost-routed queue vs live fetching) and predicts pre-launch keyword ROI with LGBMRanker before spending crawl budget. Formulates prioritized, effort-adjusted Action Queues and executes rigorous SEO matched-cohort and CRO experiments.
---

# improve-seo-with-data: The SEO & Conversion Growth Operating System

An autonomous, data-first SEO engineering, conversion optimization, and Generative Engine Optimization (GEO) system for **Antigravity CLI (`agy`)**, **Claude Code**, and engineering fleets.

Eliminates speculative "best practices", subjective design opinions, and isolated dashboards. Turns multi-dimensional performance data into a prioritized, revenue-weighted growth engine that identifies where search visibility exists, diagnoses why it is not producing clicks or conversions, and continuously executes changes that compound business outcomes.

---

## 1. Where Most "Data-Driven" SEO Skills Fail (The 5 Structural Flaws to Eliminate)

When evaluating or running an automated SEO agent, these five common architectural flaws prevent real ranking and traffic gains:

1. **Aggregating GSC Data by Page or Query Alone:** Pulling top queries and top pages separately loses the actual mapping. The skill MUST query GSC Search Analytics API with `dimensions: ["page", "query", "device"]` together. This is the only way to detect:
   - **Keyword Cannibalization:** Multiple URLs splitting impressions ($\ge 15\%$ share each) for one query.
   - **Intent Mismatch:** A page ranking for a high-impression query that does not appear in its title, visible H1, or content.
2. **Using Naive CTR Thresholds:** Flagging any query with "CTR $< 2\%$" produces noise because expected CTR depends heavily on position and SERP features. Position 1 averages ~25–30% CTR, whereas Position 8 averages ~2–3%. The skill enforces a mathematical **Position-Adjusted CTR Curve** and flags CTR underperformers where:
   $$\text{Actual CTR} < \text{Expected CTR}(\text{Position}) \times 0.70$$
3. **Ignoring Period-over-Period Deltas (Content Decay):** Static 28-day snapshots hide momentum. The skill pulls two comparative windows (last 28 days vs. previous 28 days, or YoY) to calculate traffic change decomposition and isolate **Decaying Money Pages** ($>20\%$ MoM click drop or position drift) before traffic bottoms out:
   $$\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$$
4. **Optimizing Blind Without Live SERP Context:** GSC reveals internal performance, not who is winning the SERP. The skill pairs GSC data with Live SERP & Competitor DOM inspection (top 5 ranking competitor titles, meta descriptions, content formats, FAQ/Review schema, word count, and SERP features like AI Overviews and People Also Ask) to identify exact semantic and entity gaps.
5. **No Verification Loop:** Recommending changes and vanishing fails the growth mandate. The skill logs baseline metrics, timestamps deployment dates, registers living acceptance specs, and schedules 14-to-28-day post-change GSC comparison checks.

---

## 2. The 4 High-Leverage Data Pipelines

Every optimization pass categorizes data into four mathematical pipelines to maximize incremental clicks, impressions, average position, and CTR:

| Target Metric | Pipeline Name | Exact API Filter & Mathematical Logic | Automated Engineering Action Taken |
| :--- | :--- | :--- | :--- |
| **CTR & Clicks** | **Pipeline 1: Position-Adjusted CTR Underperformers** | Position 1.0–5.5, Impressions $\ge 500$/mo, $\text{CTR} < \text{Expected CTR}(\text{Pos}) \times 0.70$ | Fetch live SERP top 5 titles/snippets; rewrite `<title>` and `<meta name="description">` using high-contrast hooks, numbers, or updated year/data; frontload exact query tokens; verify rich snippet schema (FAQPage, Product, Review). |
| **Position & Clicks** | **Pipeline 2: Striking-Distance Semantic Gaps** | Position 6.0–15.5, Impressions $\ge 200$/mo, query string absent from page `<title>`, `<h1>`, or `<h2>` | Crawl target URL; inject dedicated `<h2>` section directly answering the striking-distance query; weave missing entities from top-ranking competitors; link contextually from high-authority category hub. |
| **Impressions** | **Pipeline 3: Zero-Click / Emerging Cluster Expansion** | Position 16.0–35.0, High Impression Velocity ($+50\%$ MoM), $\le 5$ clicks | Decide via SERP overlap: if $>60\%$ shared URLs with existing page, expand existing page with new sub-topic; if $<40\%$ shared URLs, build dedicated spoke page linked contextually from category hub. |
| **Position & CTR** | **Pipeline 4: Cannibalization & Decay Triage** | Multiple URLs receiving $\ge 15\%$ share of impressions for same query, OR single URL with $>20\%$ click drop MoM | Consolidate competing pages via 301 redirect, designate primary canonical owner, or differentiate anchor text and on-page H1 targeting. Re-align intent and refresh stale data. |

---

## 3. The Essential Multi-Source Telemetry Stack (Beyond GSC Alone)

Google Search Console shows post-impression behavior on the SERP, but is a black box regarding post-click user experience and technical delivery. Correlating data across four first-party platforms closes the complete feedback loop:

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

1. **Google Search Console API (`searchanalytics.query` & `urlInspection.index.inspect`):**
   - Query joint dimensions `["page", "query", "device"]` with up to 25,000 rows.
   - Use `urlInspection` to verify whether low-impression pages are actually indexed, canonicalized properly, or suffering from rendering/crawl blockages.
2. **Microsoft Clarity API:**
   - **Rage Clicks ($>10$):** Pinpoints broken interactivity, confusing buttons, or unclickable elements.
   - **Dead Clicks:** Reveals broken expectations where users expect navigation.
   - **Average Scroll Depth ($<25\%$):** Diagnoses post-click bounce and intent mismatch. If users bounce immediately above the fold, rewriting the title tag alone will not help—the content layout or immediate value proposition is broken.
3. **PostHog API:**
   - Tracks whether organic search visitors from specific query clusters actually complete key business events (`signup`, `checkout`, `tool_calculation`, `activation`).
   - Identifies high-value organic revenue clusters versus vanity impression traffic.
4. **Cloudflare Edge Analytics & GraphQL API:**
   - **TTFB ($>400$ms):** Flags slow origin responses or un-cached dynamic edge pages.
   - **Core Web Vitals:** Monitors Largest Contentful Paint (LCP $>2.5$s), Interaction to Next Paint (INP $>200$ms), and Cumulative Layout Shift (CLS $>0.1$). Slow LCP on mobile is the primary tie-breaker suppressing rankings against equally authoritative competitors.
5. **Live SERP & Competitor DOM Scraper:**
   - Extracts live `<title>`, `<h1>–<h3>`, word count, JSON-LD schema, and internal linking structure of the top 5 ranking competitors to identify topical gaps.
6. **DataForSEO SERP Intelligence (external evidence GSC cannot see):**
   - GSC only shows queries where the site already has impressions and is completely blind to competitor gaps, exact SERP features, and uncaptured volume. DataForSEO fills that blind spot at ~$0.0006/SERP (Standard Queue).
   - **Weak-Spot Scoring:** for every striking-distance query, fetch the Top 10 and compute `serp_vulnerability_score` — forum/UGC share (Reddit/Quora/`discussions_and_forums`), title exact-match rate of the Top 5, and SERP feature crowding (AI Overview / local pack / shopping blocks). High-volume queries where forums rank in the Top 5 with no exact-match titles are immediate, zero-backlink traffic wins.
   - **Cost routing is mandatory:** batch discovery via Standard Queue (`task_post` → `tasks_ready` → `task_get`, ~$0.0006/SERP), never Live ($0.002/SERP). Search operators (`site:`, `inurl:`, `intitle:`) trigger a 5x billing multiplier — fetch the plain Top 10 and filter locally. AI Overviews and PAA come in the base payload (no paid `load_async_ai_overview` flag).
   - **Rank tracking refunds:** pass `stop_crawl_on_match` with the target domain so DataForSEO stops crawling at your URL and refunds unused depth; audit deep positions via `search_param: "&start=N"` (e.g. `30` = page 4) instead of paying full depth from position 1.

---

## 4. Learning-to-Rank (LGBMRanker `rank_xendcg`) Opportunity Scoring & Priority Queue

Opportunity ranking is governed by the trained **`LGBMRanker` (`rank_xendcg`) + SHAP driver engine** (`scripts/ltr_ranker.py`, `scripts/score_backlog.py`), rather than uncalibrated linear multiplication. The legacy heuristic ($\text{Impressions} \times (\text{Expected CTR} - \text{Actual CTR})$) has been replaced because raw impression multiplication artificially inflates low-volume striking-distance terms (e.g. 2 impressions) while burying high-volume long-tail opportunities.

### Expected Baseline CTR Curve (Prior / Warm-Start Baseline)

The baseline CTR curve serves as the inverse-propensity position-bias prior:

$$\text{Expected CTR}(\text{Position}) = \begin{cases} 
0.30 & \text{if } \text{Pos} \le 1.0 \\
0.18 & \text{if } \text{Pos} \le 2.0 \\
0.12 & \text{if } \text{Pos} \le 3.0 \\
0.07 & \text{if } \text{Pos} \le 5.0 \\
0.03 & \text{if } \text{Pos} \le 10.0 \\
0.01 & \text{if } \text{Pos} > 10.0 
\end{cases}$$

### Priority Score & Stratified Backlog Execution

1. **LTR Model Scoring:** Each candidate row is scored across the 8-feature matrix (`domain_centroid_sim`, `serp_forum_ratio`, `title_exact_match_rate`, `serp_pixel_crowding`, `parent_hub_internal_links`, `current_pos`, `search_volume_log`, `conversion_intent_score`) using `LGBMRanker` with LambdaMART (`rank_xendcg`).
2. **Action Queue Binding:** Tasks are bound directly to `action_queue_{domain}.json` and `~/.seo_fleet/fleet_state.db` sorted by `priority_score DESC`.
3. **Winner Protection Invariant:** If a URL's actual CTR exceeds baseline by $\ge 20\%$ at Position $\le 3.0$, it is locked `LOCKED_PROTECTED` with zero metadata changes permitted.

---

## 5. Agentic Execution Rules & Guardrails Against SEO Hallucinations

To guarantee safe, high-integrity autonomous code modifications:

1. **Deterministic Data Preprocessing in Code:**
   Python scripts (`scripts/seo_optimizer_engine.py`, `scripts/seo_growth_intelligence.py`) calculate deltas, CTR residuals, cannibalization shares, and impact scores in code before handing a clean JSON/Markdown summary to the LLM context. **NEVER dump raw 5,000-row GSC CSVs into the LLM context window.**
2. **Strict Guardrail 1 — Never Change Established Ranking URLs or Slugs:**
   Never rename, alter, or move a URL slug that already ranks in GSC. Doing so destroys accrued backlink equity and incurs unnecessary 301 redirection latency.
3. **Strict Guardrail 2 — Never Rewrite Top-Decile CTR Winners:**
   If a URL's actual CTR exceeds expected baseline CTR by $\ge 20\%$ ($\text{Actual CTR} \ge \text{Expected CTR} \times 1.20$) at Position $\le 3.0$, the page is marked `LOCKED_PROTECTED`. Zero title or snippet changes are permitted on winning pages.
4. **Strict Guardrail 3 — Anti-Keyword Stuffing Invariant:**
   Title tags and headings must remain human-readable, grammatically clean, and professional. Repeating the same keyword token more than twice across title and H1 is strictly forbidden.
5. **Strict Guardrail 4 — Closed-Loop Testing Invariant:**
   Every code change must be accompanied by unit tests (`pytest`), behavioral acceptance specs (`pytest-bdd`), and post-deployment edge verification (`curl -sI HTTP 200`).

### The Mandatory Wave Generation Contract

Every wave-producing invocation MUST satisfy ALL of the following. Skipping any step is a contract violation, not a preference:

1. **Minimum Candidate Depth (150 rows):** Never rank a backlog smaller than 150 scoreable candidates. `collect_features.py::ensure_candidate_depth` fills the pool through a strict 4-tier waterfall and records `tiers_used` in its report:
   - **Tier 1 — GSC rows** (real demand signals, minus recently shipped pairs).
   - **Tier 2 — sitemap orphans** (zero-impression deployed routes; zero cost).
   - **Tier 3 — catalog pairwise matrix** (`pairwise_matrix_from_sitemap`: entity vocabulary from existing family routes $\times$ unbuilt pairs; zero cost, demand verified later).
   - **Exhaustion guard (Tier 3.5):** when the pairwise space is exhausted OR the fleet's pending task backlog drops below 200 rows, `ensure_candidate_depth` engages `three_way_matrix_from_sitemap` (entity $\times$ semantic-modifier long-tail expansion) BEFORE any paid tier runs.
   - **Tier 4 — DataForSEO suggestions** (the only costly tier; gated, last resort).
2. **Fleet State Machine (`--state-db`):** All runs operating on an enrolled property MUST pass the SQLite state DB (WAL mode + busy timeout, safe under concurrent invocations): a **24h GSC snapshot** fast path, a **30-day shared SERP cache** layer, and a **daily DataForSEO budget gate** consulted BEFORE any network call. Atomic tasks live in a strict cursor: `PENDING -> LEASED -> SHIPPED` (with commit SHA) — leased in ONE atomic `UPDATE ... RETURNING` statement so two concurrent invocations can never lease the same task; a `(page, action_code)` pair that is already open is never re-enqueued. Crashed agents' leases auto-expire back to `PENDING` after 1 hour (`release_stale_leases`), and the Stage-4 rollback detector records `SHIPPED -> REVERTED` (terminal, audit trail preserved — reverted waves never re-enter the cursor to thrash the same page). `PENDING -> REJECTED` (terminal) is written by cursor hygiene for queries that can never be addressed by a single-heading edit.
   - **Stratified leasing (`lease_tasks`):** leases are drawn via a window-function ranking PARTITIONED BY `route_family` (first path segment of the task URL), with `family_caps` (e.g. `{"number": 3}`) + `default_family_cap` so one template family can never eat the whole wave quota, AND a second window rank PARTITIONED BY `action_code` enforcing **task-type quotas** (`type_caps`/`default_type_cap`; `DEFAULT_TYPE_CAPS` = 8x `ADD_D1_SPEC_COMPARISON_TABLE`, 8x inlinks (`BOOST_CLUSTER_CROSS_LINKS` + `STRENGTHEN_HUB_INTERNAL_LINKS`), 6x `OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA`, 5x title/H2 intents (`INJECT_EXACT_TITLE_AND_H2` + `INJECT_EXACT_H2_AND_TITLE`), 3x `CREATE_PROGRAMMATIC_ROUTE` — every wave ships a mix of work products, not 30 identical heading checks), a **single task per unique URL constraint** (`ROW_NUMBER() OVER (PARTITION BY page ORDER BY priority_score DESC) AS page_rank` with `page_rank = 1` preventing duplicate-URL task pairs from burning multiple lease slots in the same wave), and a **file_target collision lock**: a PENDING task whose `file_target` is actively LEASED elsewhere is skipped (two agents can never edit the same file at once). `NULL`/empty file_targets are exempt.
   - **Pre-lease cursor hygiene (`scripts/cursor_hygiene.py`, wired into BOTH lease paths of `score_backlog`):** before any lease, `preflight_hygiene` (1) terminally `REJECT`s junk queries (`site:`/`inurl:`/`intitle:`/`filetype:` operators, raw URLs, uppercase Boolean `OR`/`AND`, `-negation` terms, >15% non-ASCII, probable non-English function words — lowercase `and`/`or` as ordinary words survive), (2) terminally `REJECT`s inlink tasks for the root homepage `/` (every page already links to `/` via the brand header/footer), (3) **graduates** `INJECT_*` tasks whose query tokens are already fully covered by the route/country intent map (`--intent-map`, JSON `{page: rendered_text}`; the executing agent regenerates it from `route_search_intent.py`/`country_search_intent.py` + live DOM after each wave) straight to `SHIPPED` — no duplicate intent H2s, (4) skips pages/file_targets under another agent worktree's registered lock prefix, and (5) enforces a **max-2 intent tasks per URL** cap. `REJECTED` rows are never re-enqueued (`enqueue_tasks` honors the terminal state).
   - **Worktree lock registry (`~/.seo_fleet/worktree_locks.json`):** agents register their owned route/template prefixes at wave start (`register_worktree_locks`, PID + 2h heartbeat TTL — dead PIDs and stale heartbeats self-expire); `active_locked_prefixes` feeds pre-flight so concurrent waves never lease each other's routes. At wave closeout the agent MUST call `release_deferred_leases_on_closeout(conn, deferred_ids)` to return agent-deferred LEASED tasks to `PENDING` immediately (they otherwise strand for the full 1h stale-lease TTL and block their file_targets). `cursor_hygiene.py` is also a thin CLI: `--state-db --release-deferred 12,13` and `--register-locks "/prefix/ ..."`.
   - **Cursor starvation guard:** `score_backlog --replenish-below N` refills the backlog to full candidate depth whenever pending rows fall below `max(replenish_below, lease_size)`; the fast lease path (pending above threshold, <0.5s, zero network) keeps the lease loop cheap when no refill is due.
3. **URL Inspection CoverageState Enrichment (`--state-db` + default on):** zero-impression candidates are enriched via `inspect_coverage_states` (GSC URL Inspection API, 2,000 free calls/day/property; results cached 7 days in the state DB, every call counted against a daily gate). The coverageState tells the compiler WHY a route has no impressions: `Crawled - currently not indexed` -> thin-content gate (`ADD_D1_SPEC_COMPARISON_TABLE`), `Discovered - currently not indexed` -> discovery gate (`RESCUE_ORPHAN_ROUTE_INLINKS`). Bound per run with `--inspect-limit` (default 40).
4. **Atomic TDD Wave Compilation (`--compile-wave N`, target 35-60):** `compile_wave_backlog` decomposes each scored row into INDEPENDENT atomic tasks — one (page, action) each, cooldown-masked against the shipped ledger, deduplicated, each carrying a concrete `file_target` and a machine-checkable `tdd_assertion` a coding agent can run verbatim. Canonical action codes: `BOOST_CLUSTER_CROSS_LINKS`, `OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA`, `INJECT_EXACT_TITLE_AND_H2`, `STRENGTHEN_HUB_INTERNAL_LINKS`, `CREATE_PROGRAMMATIC_ROUTE`, `RESCUE_ORPHAN_ROUTE_INLINKS`, `ADD_D1_SPEC_COMPARISON_TABLE`, `INJECT_PAA_SEMANTIC_SECTIONS`, `ADD_WEBAPP_JSONLD_SCHEMA`, `REWRITE_HIGH_CONTRAST_TITLE`.
   - **Root homepage inlink exclusion:** Never emit `WIRE_HUB_AND_FOOTER_INLINKS` (or synonyms) for the root homepage `/` (every page already links to `/` via the brand header/footer).
   - **Footer link bloat constraint:** Cap global `footer.html` links at **max 12 top-level hubs/popular tools**. Route all child-page `WIRE_HUB_AND_FOOTER_INLINKS` tasks into **contextual parent hubs** (`/compare/`, category cards, or related-converter widgets on sibling formats like `/convert/stl-to-step/` $\leftrightarrow$ `/compare/step-vs-stl/`), never directly into the site-wide footer.
5. **Catalog-Wide Propagation:** A fix prescribed on one programmatic route MUST propagate across every sibling sharing its template family (`catalog_propagation` hint with sibling counts, auto-derived from the candidate pool): change the template once, not N times.
6. **CTR-Oriented Schema Preference:** For tool/interactive routes prefer `WebApplication` (and `Dataset` where a proprietary aggregation exists) over `FAQPage` markup; FAQPage does not earn CTR-eligible rich results for tools.
7. **Offline Surrogate Before Paid Calls:** `scripts/dfs_surrogate.py` predicts the four DataForSEO columns (volume log, forum ratio, title-match rate, pixel crowding) from the fleet's cached SERP history — LightGBM-only, no sklearn. Use it to pre-screen matrix/suggestion candidates offline; refit nightly with `--fit-from-state-db` once the cache grows past its 20-row floor (it refuses below the floor rather than guessing).
   - **Volume head backfill (`--backfill-volumes`):** SERP `task_get` responses carry NO search volume, so the surrogate's `search_volume_log` target starves on SERP-only caches. `dfs_surrogate.py --fit-from-state-db <db> --backfill-volumes` fills `dfs_serp_cache.search_volume` from one batch Keywords Data `google_ads/search_volume/live` call (~$0.05-$0.09 per 1,000 keywords; queries missing after sanitation are honestly absent, never fabricated) and `refit_from_state_db` feeds the stored volumes into the volume model. Volume-backed row count is reported on every refit.
8. **DOM Gap Flags as Task Selectors:** `dom_gap_flags` (missing exact H2, missing data table, missing PAA coverage, weak inlinks, missing WebApplication schema, title CTR deficit) turn structural deficits into atomic tasks — they ride outside the feature vector and never silently deprioritize a ranked row.

---

## 6. Operating Invariants

1. **Observability Precedes Optimization:** If a website cannot observe its organic search visitors, crawler hits, rage clicks, and conversion funnels, it is flying blind. Audit and configure the telemetry stack before modifying code or metadata.
2. **The Growth Equation Over Vanity Metrics:**
   $$\text{Impressions} \longrightarrow \text{Clicks} \longrightarrow \text{Qualified Visits} \longrightarrow \text{Conversions \& Revenue}$$
3. **Cross-Dimensional Synthesis (No Data Silos):** Combine query cluster $\times$ landing page $\times$ device $\times$ conversion rate $\times$ edge latency.
4. **Traffic Change Decomposition:** Decompose click changes: $\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$.
5. **Separate SEO Experiments from CRO Experiments:** Matched URL cohorts evaluated via Difference-in-Differences (DiD) for SEO; visitor-level randomized A/B tests in PostHog for CRO.
6. **Query-Mix Adjustment:** Never infer sitewide snippet deterioration from an unadjusted drop in aggregate CTR. Hold query position, country, and device constant.
7. **Crawl Budget & Parameter Defense:** Guard crawler bandwidth by ensuring faceted query parameters (`?sort=`, `?filter=`, `?page=`) are governed by `Disallow: /*?*` in `robots.txt` and marked with `rel="nofollow"`.
8. **Generative Engine Optimization (GEO):** Maintain machine-readable documentation via `llms.txt`, validated Schema.org JSON-LD entity graphs, and explicit AI crawler permissions (`GPTBot`, `ClaudeBot`, `PerplexityBot`).
9. **Auditable Action State Machine:** Every recommendation transitions through:
   $$\text{Detected} \longrightarrow \text{Validated} \longrightarrow \text{Approved} \longrightarrow \text{Implemented} \longrightarrow \text{Evaluated} \longrightarrow \text{Learned}$$
10. **Closed-Loop Verification:** Always re-run the matching audit report, crawler pass, or telemetry evaluator after implementing code changes to verify 0 regressions.
11. **Direct Empirical Data Traceability (Zero Speculative Actions):** Every recommendation MUST track directly back to an empirical observation in data (specific GSC query, impressions, position, CTR vs benchmark, GA4 conversion rate, PostHog drop-off %, Clarity rage clicks, Cloudflare CWV metrics). Speculative "best practices" or orphan actions lacking empirical proof are strictly banned.
12. **Dual-Track Execution Mandate (Improve Existing AND Create New Every Run):** Every single invocation of this skill MUST execute BOTH tracks in parallel:
    - **Track 1: Improve Existing Pages:** Title optimization within display-width limits (~580px desktop, ~480px mobile), snippet appeal, content depth/utility, Schema.org rich data, internal links, and conversion CTA streamlining for existing URLs.
    - **Track 2: Create New Pages:** Detect unmet query clusters that pass the URL ownership check and 7-factor quality gate. Automatically build and register them into production models, views, templates, sitemaps, and Gherkin acceptance specs across the 5 Standard Template Archetypes.
13. **The SEO Outcome Maximization Contract:** Maximize incremental organic clicks and meaningful business conversions, not pages published or words written.
14. **The URL Ownership Model & Anti-Cannibalization Gate:** If an existing non-hub URL ranks $\le 15.0$ or receives the majority of impressions for a query cluster, **NEVER create a new competing page**. Improve the existing URL (Recipe A).
15. **Title SERP Display-Width Heuristics (~580px Desktop / ~480px Mobile):** Keep 50–65 characters as practical rule of thumb; verify that the primary user intent and brand fit within container rendering width.
16. **Sitemap `lastmod` Timestamp Integrity:** Advance `<lastmod>` only on substantive content, pricing, or functional updates, never on routine cron runs.
17. **Production Indexing Funnel Tracking:** Track pages through `Published -> Discovered & Crawled -> Eligible & Indexed -> Impressions -> Clicks -> Conversions`.

---

## 7. The 8-State Page-Level Diagnostic Decision Tree

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

## 8. The 5 Standard Template Archetypes

1. *Editorial / Guide Template:* Informational queries (answers, context, citations, technical deep-dives).
2. *Comparison Template:* "A vs B" & "Best Alternative" queries (decision criteria, benchmark comparison matrix).
3. *Tool / Calculator Template:* Functional calculation queries (interactive inputs, instant deterministic outputs).
4. *Directory / Category Template:* Browsing and discovery queries (structured filters, crawlable detail links).
5. *Localized / Market-Specific Template:* Regional telecom and market differences (dialing plans, regulations, currencies).

---

## 9. Autonomous Operational Workflows

### Workflow 0: Multi-Platform Data Fusion Engine (The Master Automation)
Execute the multi-platform correlation engine to fuse GSC, Clarity, PostHog, and Cloudflare:

```bash
# Automated run with export to JSON action queue and Markdown executive report
python3 scripts/seo_optimizer_engine.py \
    --site sc-domain:example.com \
    --output-json /tmp/seo_action_queue.json \
    --output-md /tmp/seo_executive_report.md
```

### Workflow 1: Multi-Dimensional GSC & GA4 Opportunity Discovery
Run the comprehensive growth intelligence orchestrator:

```bash
python3 scripts/seo_growth_intelligence.py --site sc-domain:example.com
```

### Workflow 2: Period-over-Period Traffic Change Decomposition
When diagnosing traffic gains or declines across 7-day, 28-day, or 90-day intervals:

```bash
python3 scripts/gsc_analyzer.py --compare-periods period0_baseline.json period1_recent.json
```

Separates impression volume changes from snippet engagement changes:
$$\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$$

### Workflow 3: Conversion Leakage & UX Friction Diagnosis
1. **GA4 / PostHog Audit:** Locate landing pages where organic session volume is high but conversion rate is depressed.
2. **Clarity Friction Investigation:** Filter session recordings by affected landing page; inspect rage clicks, dead clicks, and 50% scroll line placement.
3. **Formulate CRO Intervention:** Simplify mobile inputs, sticky-position primary CTA, and test via PostHog visitor-level A/B test.

### Workflow 4: Technical Reliability & Incident Correlation
1. **Cloudflare Edge Logs:** Monitor 5xx response spikes and 404 error clusters; verify Googlebot via reverse DNS.
2. **Core Web Vitals:** Ensure LCP $\le 2.5\text{s}$, INP $\le 200\text{ms}$, and CLS $\le 0.1$.

### Workflow 5: Generative Engine Optimization (GEO) & Machine-Readable Discovery
Ensure search visibility across LLM answer engines (**ChatGPT Search**, **Perplexity**, **Claude**, **Google AI Overviews**):

```bash
python3 scripts/geo_evaluator.py --url https://example.com
```

### Workflow 6: DataForSEO Weak-Spot Enrichment & Pre-Launch Ranking (External SERP Alpha)
Internal telemetry alone is bound by survivorship bias: it can only optimize keywords where Google already grants impressions. Enrich every striking-distance candidate with external SERP evidence BEFORE spending engineering time (see [`references/serp_intelligence_and_programmatic_scaling.md`](./references/serp_intelligence_and_programmatic_scaling.md) for the full playbook):

```bash
# Dry-run: inspect the payload plan and cost estimate (no network)
python3 scripts/dataforseo_client.py --keywords-file striking_distance.txt --dry-run

# Batch weak-spot scan via the Standard Queue ($0.0006/SERP), then score every SERP
python3 scripts/dataforseo_client.py --keywords-file striking_distance.txt \
    --output-json /tmp/serp_weakspots.json

# Rank tracking that stops at your domain (refunds unused depth)
python3 scripts/dataforseo_client.py --keywords-file my-queries.txt --rank-track-domain example.com
```

Route every candidate through the enrichment funnel before acting:
$$\text{GSC Striking Distance} \longrightarrow \text{SERP Vulnerability Score} \longrightarrow \text{LGBMRanker Expected Clicks} \longrightarrow \text{Action Queue}$$

1. **Weak-Spot Gate:** high-impression queries scoring `weak_spot=true` (forum-heavy, low title-match) jump to the front of the Action Queue; queries where entrenched DR 90+ giants exact-match the title are demoted regardless of internal metrics.
2. **Pre-Launch Prediction (LGBMRanker lambdarank):** rank the pSEO backlog by predicted 30-day click velocity (features: topical centroid similarity, SERP vulnerability, title exact-match rate, internal-link centrality) and publish only the top 5-15% of route pairs first. Deploy top deciles only after early cohorts earn impressions in GSC.
3. **Programmatic Doorway Defense:** every pSEO template must pass the pre-deploy similarity gate — `uniqueness_ratio >= 0.50` populated data fields, dynamic DOM branching on data deltas, and MinHash/shingle similarity < 70% between sibling routes. Bulk templates that fail the gate are held from the sitemap (crawl-and-drop is a site-wide trust hazard, and noindex does not undo a domain-level classifier hit).
4. **Navboost & Indexing Velocity:** interactive answers/calculators in the top 300px to win the long click; sharded priority sitemaps; IndexNow pings on publish (Bing/ChatGPT/Perplexity); rotating "recently updated" boost slots on the highest-authority pages until first GSC impressions arrive.

### Workflow 7: The Self-Improving Ranking Loop (Collect → Train → Score → Log Outcomes)

The production implementation of Workflow 6's funnel: a closed, ALWAYS-ON Learning-to-Rank loop. Labels come from real click buckets once the fleet history carries clicks, and from DataForSEO SERP-structure bootstrap grades before that — so the ranker trains from day one (10+ rows) instead of idling behind a 300-outcome gate. The deterministic heuristic survives only as the `init_score` residual baseline, meaning the model can never underperform it. Run it as a monthly cycle per property.

```bash
# Stage 1: REAL GSC candidates + DataForSEO SERP enrichment -> 8-feature matrix
python3 scripts/collect_features.py --site smsriver.com --top 200

# Stage 1.5 (fleet pooling, cross-domain day-one strength): harmonize every
# authenticated GSC property's exports into ONE domain-agnostic history
python3 scripts/fleet_ingest.py --inputs 'data/fleet/*.json' \
    --output data/ltr_training_history.jsonl

# Stage 2: train the ranker (ALWAYS-ON: >= 10 trainable rows suffice)
python3 scripts/train_ranker.py                       # rank_xendcg + bootstrap grades
python3 scripts/train_ranker.py --objective lambdarank    # for mature click-rich pools

# Stage 3: score the backlog -> prescribed actions + calibrated Expected Clicks
python3 scripts/score_backlog.py                      # auto-trains if no bundle exists

# Stage 4 (30 days later): join executed queue against fresh GSC, append
# labeled outcomes, and retrain in one step
python3 scripts/log_outcomes_and_retrain.py \
    --executed data/action_queue_2026-01.json --site smsriver.com
```

Contract details enforced by `scripts/ltr_ranker.py` (see [`references/serp_intelligence_and_programmatic_scaling.md`](./references/serp_intelligence_and_programmatic_scaling.md) section 4):

- **Labels (always-on, two modes):** with >= 50 pooled rows carrying real clicks, exponential 0-4 click buckets (`label_gain=[0, 1, 3, 7, 15]`; any conversion overrides to grade 4). Below that, `bootstrap_labels.py` grades every candidate from pure SERP structure: quantile-binned DataForSEO opportunity score (`search_volume_log x serp_openness x crowding_penalty x position_weight x domain_centroid_sim`), with **deep-head traps** (position > 50, zero forum slots, >= 0.6 title match rate) hard-graded 0. The mode is recorded in the bundle metadata (`label_mode: serp_bootstrap | fleet_clicks`) and flips automatically as click outcomes accumulate.
- **Position-bias correction:** click labels are propensity-adjusted (`AdjustedClicks = realized * min(5, ECTR(3)/ECTR(p_start))`, `ECTR(p) = 0.28/p^1.15`) so the ranker learns click LIFT, not "recommend whatever already ranks #1".
- **Leakage defense:** the 80/20 train/validation split is performed over WHOLE semantic clusters, never inside one.
- **Monotonic constraints:** `[+1 centroid, +1 forum, -1 title match, -1 crowding, +1 hub links, 0 position, +1 volume, +1 intent]` — small datasets cannot learn inverted truths.
- **Residual learning:** `init_score` warm-starts from the deterministic heuristic `log10(imp+1) * (TargetCTR - CTR) * ConvValue`, so the model can never underperform the baseline while young. The linear proxy has no other role; it is no longer a scorer.
- **Adaptive regularization:** `min_data_in_leaf = max(5, n_rows // 30)` scales leaf size to the pooled history, which is what makes 10-150-row bootstrapped histories trainable at all.
- **Cross-cluster calibration:** raw ranker margins are NOT comparable across clusters; an isotonic regressor (PAVA, out-of-bounds clipping) maps them onto calibrated Expected 30-Day Clicks before global Top-20 queueing — fitted only when >= 20 clicked validation rows exist. Bootstrap-mode bundles ship uncalibrated margins rather than invent click semantics.
- **Trainable floor:** below `MIN_TRAINABLE_ROWS = 10` pooled rows the trainer and scorer refuse (exit 2) rather than emit guess-ranked queues; pool the fleet with `fleet_ingest.py` first.
- **85/15 queue:** 17 exploited slots (top calibrated scores) + 3 exploratory slots drawn from the 50th-80th percentile stratified across clusters, so the history keeps receiving counterfactual variance and the model never goes feedback-loop blind.
- **Prescription:** SHAP contributions (`booster.predict(X, pred_contrib=True)`) map each candidate onto one of 4 executable actions: `LAUNCH_PSEO_ROUTE`, `INJECT_EXACT_H2_AND_TITLE`, `BOOST_INTERNAL_LINKS`, `REWRITE_SNIPPET_AND_TOP_300PX`.

### Workflow 7 volume & verification upgrades (always surface fresh work)

Four queue-volume mechanisms (implemented in `collect_features.py` / `score_backlog.py` / `ltr_ranker.py`) so every invocation emits a FULL wave instead of repeating the same Top-20:

1. **Unseen-candidate injection (fixes 0-row & thin sites):** `collect_features.py --suggest-seeds "seed1,seed2" [--suggest-limit 200 --suggest-min-volume 50 --suggest-max-difficulty 35]` calls DataForSEO Labs `keyword_suggestions/live` (`include_serp_info=true`) and synthesizes net-new candidates at `current_pos=100` (→ `LAUNCH_PSEO_ROUTE`). For brand-new domains, `--seed-from-competitors "comp1.com,comp2.com"` calls Labs `domain_intersection/live` and injects the keywords actually driving competitors' traffic. Both are LIVE Labs endpoints (deliberate cost, explicit flags, fails soft to GSC-only).
2. **Multi-prescription SHAP explosion:** every scored row carries an `actions[]` list, primary first: beyond the 4 primary families, `prescribe_all_actions` emits atomic work items per negative SHAP driver — `REWRITE_CTR_TITLE_AND_TOP_300PX` (pos ≤ 10, ≥ 30 impressions, 0 clicks = CTR-hook failure) and `SPIN_OUT_DEDICATED_SUBROUTE` (forum-heavy SERP within pos 20). One row can yield 2-3 distinct TDD work items.
3. **30-day cooldown ledger:** `data/shipped_actions.jsonl` (append-only; `record_shipped`). `score_backlog.py` filters every `(page, action_type)` shipped within `--cooldown-days 30` BEFORE the 85/15 split, so back-to-back runs walk through the backlog instead of re-recommending the same rows (`--record` appends the emitted queue at ship time; Stage 4 appends graded tasks too).
4. **Per-domain quota slicing:** `score_backlog.py --per-domain-top N` caps the final globally-ranked queue at N tasks per registered domain, so a 454-row property can no longer crowd 40-row and 0-row properties out of the queue.

Four verification & guard mechanisms (Stage 4, `log_outcomes_and_retrain.py`):

1. **Recrawl-lag guard (`--require-recrawl --deployed-at <ISO>`):** Googlebot needs days to recrawl a modified URL; grading earlier teaches the ranker from phantom zeros. A shipped page counts as recrawled once it registers ANY impressions in a post-deploy GSC window (proxy for URL Inspection `lastCrawlTime`, which the `seo` binary does not expose): post-deploy `seo gsc-query` window via `--site`, or a supplied `--post-deploy` export. Un-recrawled tasks go to `data/pending_verification.json` ungraded (and only pages crawled ≥ `MIN_GRADE_DAYS_AFTER_DEPLOY = 7` days after deploy are graded at all).
2. **Negative-delta auto-rollback (`--pre-deploy <gsc-query export>`):** for graded rows whose pre-deploy position sat in the protected 4-15 band, a drop of > 4 positions or > 30% impressions emits a `REVERT_WAVE_COMMIT` task (written to `data/rollback_queue.json`, printed at the top of the next wave's attention). Realized outcomes keep their real clicks (no data falsification); the revert restores the pre-deploy SERP state.
3. **Clicked-row graduation fast-track:** `collect_features.py --backfill-days 365` pulls the full 16-month-retention window once via `seo gsc-query`; historical `(query, page)` winners joined with current SERP structures push the pooled history past the 50-clicked-row threshold the same day, flipping the labeler from `serp_bootstrap` to empirical click grades without waiting for fresh organic data.
4. **Leading indicators (how to know it is working before traffic curves move):** (a) queue sanity — striking-distance rows with weak SERP competition on top, deep head terms at the bottom; (b) shipped-cohort deltas — track ONLY the wave-modified URLs: a winning `INJECT_EXACT_H2_AND_TITLE` shows position +3-8 and an impression spike 5-10 days after recrawl, well before clicks; (c) the graduation counter — clicked rows (25/50 today) climb with every property's daily traffic and flip the label mode automatically (`label_mode` in the bundle metadata records the mode).

### Workflow 7 zero-cost candidate sources and indexation triage

1. **Orphan route detector (default on; `--no-orphans` to skip):** `collect_features.py` fetches the live `/sitemap.xml` (one index level supported) and left-joins it against the GSC page export. Every live URL with ZERO GSC impressions is an orphaned/unindexed route the codebase ALREADY deployed — injected as a candidate with `current_pos=100`, a slug-synthesized demand-proxy query, and the `ORPHAN_ACTIONS` prescription set (`BOOST_INTERNAL_LINKS` + `EXPAND_THIN_ROUTE`; never `LAUNCH_PSEO_ROUTE` — the route exists). Cheapest internal-link targets available, before any DataForSEO spend.
2. **Query cannibalization detector:** `detect_cannibalization` (run inside `score_backlog.py` BEFORE the per-query collapse) flags every query carried by ≥ 2 distinct pages ALL ranking worse than position 10 (a Top-10 owner is Guardrail-2 protected and never flagged). The keeper row gains `CONSOLIDATE_CANNIBALIZED_URLS` (301 the weakest duplicate into the strongest, or split title/h1 modifiers onto sub-intents, or rel=canonical); the full competing-URL set ships in the queue file's `consolidation` array.
3. **coverageState triage (`--inspection FILE`):** a URL Inspection export (`url -> {coverageState, lastCrawlTime, googleCanonical, userCanonical}`) upgrades Stage 4 two ways: `lastCrawlTime > deployed_at + 7d` counts as recrawl evidence, and pending pages get their WHY mapped to an automated fix — `Discovered - currently not indexed` → `BOOST_INTERNAL_LINKS` (inject into the homepage trending/recent block); `Crawled - currently not indexed` → `INJECT_UNIQUE_DATA_TABLE` (add distinct D1 rows/benchmarks, not title tweaks); `Duplicate, Google chose different canonical than user` → `PRUNE_DUPLICATE_ROUTE` (DOM-branch the template or prune the route; the canonical pair is included in the task). Triage rides inside `data/pending_verification.json`.
4. **`item_types` persistence (zero extra cost):** every DataForSEO SERP response carries `result[0]["item_types"]` — the SERP feature list. The collector now persists it as ROW METADATA (`serp_item_types`, `has_ai_overview`, `has_forums`, `has_people_also_ask`) outside the canonical 8-feature vector (whose order is load-bearing for trained bundles). Prescriptions and indexation triage consume the flags without retraining.

---

## 9.5 Edge Telemetry, DOM Auditing & High-Frequency Cursor Invariants

Hard-won from the figiva.com run (Nov 2026): a 504-storm root cause, a
strict-grep false positive, and a stale-keyspace regression. These
invariants are binding on every invocation. (Correction, Nov 10: the
"504 storm" later proved to be Cache API miss instrumentation, not
proxy timeouts — see Invariants B and E; the render-cost lesson stands.)

### Invariant A: Decompressed Canonical DOM Parsing (No Strict-Grep Link Audits)
- NEVER use raw regex (`grep -E 'href="[^"]*/slug/"'`) or raw byte streams to check whether a route is linked or contains target `<title>`/`<h2>` tokens. On a 275 KB hub (`figiva.com/calculators/`) a strict `href="..."` regex reported ZERO links for URLs that were in fact linked 2-6 times (attribute ordering / relative-href variance) and nearly shipped a fabricated "orphan rescue" wave.
- Edge fetches MUST explicitly handle `Accept-Encoding: gzip, deflate, br` decompression and parse `<a href>` attributes through `urllib.parse.urljoin(page_url, href)` with a real HTML parser (`selectolax`/`BeautifulSoup`/`lxml`), normalizing to canonical path slugs before matching.

### Invariant B (Updated): True Edge 5xx Gate vs. Cache-API Miss Telemetry
- When querying Cloudflare GraphQL (`httpRequestsAdaptiveGroups`) for crawl-health gating, ALWAYS filter `requestSource != "edgeWorkerCacheAPI"`. Internal `caches.default.match()` misses emit `edgeResponseStatus = 504` under `edgeWorkerCacheAPI` and are NOT user- or crawler-facing errors.
- Only gate content waves when **true origin/worker responses** (`requestSource == "eyeball"`) exceed `5xx > 5/hr` OR when cold crawler TTFB exceeds `3,000ms` without an active L2 KV cache.
- Once L2 KV caching reduces crawler TTFB below `250ms` and true `5xx == 0`, **do NOT hold content waves on a multi-day hostload cooldown** if no historical eyeball `5xx` storm occurred — ship structural content enrichments (`ADD_D1_SPEC_COMPARISON_TABLE`, worked examples) and warm the KV store immediately so Googlebot's first crawl evaluates the enriched DOM.

### Invariant C: Cloudflare Worker Shared-Kernel D1 Watchdog (`django-cf`)
- `verify_subrequest_timeout_contract()` only LOGS the 5,000ms ceiling; `django-cf` awaits the underlying JS D1 Promise indefinitely. Pair the contract with an ACTIVE timeout (`Promise.race` / `asyncio.wait_for(..., timeout=4.5)`) around D1 binding queries.
- When a D1 read times out on a bot/anonymous GET, serve a stale cached snapshot or return `HTTP 503` with `Retry-After: 30-60` rather than hanging 100s into a crawl-poisoning `504`. Googlebot treats a fast `503 Retry-After` gracefully; a 100-second `504` triggers multi-day hostload throttling.

### Invariant E (Updated): L1 Colo Cache + L2 Global KV Pattern & Anti-Stale Salting
- Pyodide Workers (`django-cf`) bypass Cloudflare Smart Tiered Cache when writing directly to `caches.default`. Always pair L1 `caches.default` (colo-local) with L2 Cloudflare KV (`<app>:bothtml:<version>:<canonical_path>`, `expirationTtl: 21600`) for global crawler pre-warming.
- **Canonical Key Normalization (KV Write-Quota Guard):** The KV key `<canonical_path>` MUST strip all query strings (`?utm_*`, `?ref=*`) and only cache known `200 OK` route patterns so random bot query-string fuzzing cannot exhaust KV write quotas.
- **Deploy-Safe Cache Busting:** Prefix the KV key with a short template/content version token (or honor a `Cache-Control: no-cache` / `X-SEO-Audit-Bypass` header) so post-deploy TDD live verification never reads pre-deploy HTML from the 6-hour KV cache.
- **Telemetry-Clean Pre-Warm & Verification Sweeps (HMAC-gated):** Pre-warm and verification sweeps MUST send `X-SEO-Prewarm: 1` or `X-SEO-Verify: 1` PLUS a valid `X-SEO-Sweep-Sig` (same-day `HMAC-SHA256(FIGIVA_SEO_SWEEP_SECRET, "<path>:<YYYYMMDD>")`; mint via `scripts/figiva_sweep_headers.py`). The worker suppresses crawler-telemetry logging and engages the bot render/store path ONLY for signed sweeps — unsigned flags are treated as the request's raw user agent (fail-closed: an unauthenticated flag would otherwise let anyone force expensive renders + KV writes, or bypass the KV cache, while invisible to telemetry). Never spoof a `Googlebot` UA in synthetic sweeps. If the deploy ran without `FIGIVA_SEO_SWEEP_SECRET`, sweeps are DENIED at the edge (they render as their raw UA and telemetry records them) — redeploy with the secret before sweeping.
- **KV Writes Only On 200 Canonical Routes:** `bot_kv_store` runs strictly behind the 200 + text/html + crawler gate — 404/redirect bot probes (`/wp-admin`, random slugs) must never mint KV writes. An L1 miss -> L2 KV hit re-warms ONLY the local colo Cache API (free) and NEVER re-writes KV.
- **Post-Enrichment Cache Overwrite (D1 mutation waves):** Any D1 content mutation (`ADD_D1_SPEC_COMPARISON_TABLE`, worked examples) on a pre-warmed URL MUST atomically overwrite that URL's KV + Cache API entries upon task completion — re-warm via SIGNED `X-SEO-Verify: 1` GETs per mutated URL (mint headers with `scripts/figiva_sweep_headers.py --verify <path>`; the worker bypasses BOTH cache reads, freshly renders the enriched DOM, and overwrites L1 + KV in the same request, telemetry suppressed) — or bump `CACHE_KEY_VERSION` and re-sweep — so Googlebot never crawls stale pre-enrichment HTML.
- **Execution Order Invariant (L2 + enrichment waves):** when un-gating content waves alongside an L2 cache fix, verify the L2 pipeline on 1-3 canary URLs FIRST, ship the high-priority DOM enrichment wave SECOND, and run the full sitemap pre-warm sweep AFTER the enriched DOM is live (a pre-enrichment sweep locks thin HTML into KV).
- Never let humans consult a bot-only prefix, and swallow all KV failures (the global layer must never break rendering).

### Invariant D: Daily Cursor, Pre-Lease Hygiene & 28-Day Title Lock (with Emergency Bypass)
- All invocations read/write the local SQLite `atomic_task_backlog` cursor (`PENDING -> LEASED -> SHIPPED`) backed by the pooled-fleet LGBMRanker and the offline DataForSEO surrogate, with the daily DFS budget gate consulted before any network call.
- Pre-lease checks MUST scrub Boolean/operator noise (`site:`, `OR`, `AND`, `-\w+`), auto-graduate tasks already satisfied on the live page, skip paths whose `file_target` is leased elsewhere, and release stale `LEASED` rows back to `PENDING` on closeout.
- **28-Day URL Title Lock (`enforce_url_title_lock`):** Once a URL's `<title>` tag has been calibrated and shipped in any wave within the last 28 days, that URL's `<title>` is locked. Secondary queries arriving in subsequent waves must NEVER overwrite or degrade the primary calibrated title; they are strictly downgraded to `INJECT_SECONDARY_H2_ONLY` (enriching body `<h2>`/`<h3>` or FAQ `<details>` blocks).
- **Conditional Emergency Bypass:** The 28-day title lock may only be bypassed if an explicit manual regression, critical factual inaccuracy, or layout breakage is detected (`--force-title-recovery` with documented operator rationale). Routine keyword churn across consecutive waves is strictly prohibited.
- **Strict Canonical Hostname Gate (`is_valid_property_host`):** Rejects legacy or foreign subdomains (e.g. `landscaping.figiva.com` from `sc-domain:` exports) during candidate collection and pre-lease filtering.

### Invariant F: Anti-Vaporware Copy & Structured Table Consolidation
1. **Forbidden Heading Phrases:** NEVER render roadmap, status, or internal pipeline language in user-facing `<title>`, `<h1>`, `<h2>`, or meta descriptions. Phrases matching `r"(in rollout|coming soon|server-side pipeline|beta pipeline|under construction|placeholder)"` are strictly banned and must fail TDD assertions. Every `<h2>` must deliver immediate domain-specific technical utility (e.g., `<h2>STEP to DXF Conversion: ISO 10303 B-Rep to AutoCAD 2D Projection</h2>`).
2. **2-H2 Ceiling & Table Consolidation:** Never stack more than 2 search-intent prose `<h2>` blocks in `ROUTE_SEARCH_INTENT_SECTIONS` on a single URL. When a URL receives a 3rd+ query (such as additional area codes `07770`, `078`, `079` on `/country-codes/united-kingdom/` or format flags on `/convert/`), consolidate them into a single structured HTML `<table>` (`<thead>`/`<tbody>`) with technical specs.
3. **Global Footer Link Cap:** Never append more than 12 links to a site-wide `footer.html`. Satisfy `WIRE_HUB_AND_FOOTER_INLINKS` for child routes by linking from contextual parent hubs (`/compare/`, `/calculators/`, `/niche/<slug>/`, or `/studio/<slug>/`) and sibling cross-link widgets.
4. **Triplet Collapse & Truly Unbuilt Routes (`is_truly_unbuilt_route`):** `CREATE_PROGRAMMATIC_ROUTE` must bundle exact title, H2, and hub inlink assertions upon creation. Secondary intent tasks (`INJECT_EXACT_TITLE_AND_H2`, `WIRE_HUB_AND_FOOTER_INLINKS`) are strictly forbidden for unbuilt routes; candidate generation must emit only the single route creation task. Furthermore, a route is only unbuilt if absent from known sitemaps/shipped history AND has 0 total GSC impressions; existing live routes with low ranking must never be misclassified as unbuilt.
5. **Tier-2 Sitemap Orphan Generation:** Must skip top-level directory/hub routes (`/compare/`, `/calculators/`, `/tools/`, `/articles/`, `/niche/`, etc.) and never synthesize 1-word broad queries from hub slugs.

### Invariant G: Multi-Tenant Worker Cache Scoping
- Deployments for multi-tenant applications (such as `seo-alpha-site-saas`, hosting `incomecanvas.com`, `skrino.com`, and `autopublishai.com`) must only purge the edge cache zone of the domain modified by the current wave (`--zone <domain>`).
- Indiscriminate multi-zone cache flushes without coordinated re-warm sweeps evict edge KV across sibling brands and cause cold-start latency spikes.

### Invariant H: Intent-Driven SERP Title Geometry & Pixel Modeling
- SERP display title pixel estimation must evaluate the full rendered title string, including brand separators, against the desktop ~580px budget.
- Prioritize high-contrast intent tokens and searcher clarity over arbitrary character-count padding: a concise, punchy 52-character title that frontloads intent is superior to a 64-character title padded with filler words.
- When using wide glyphs such as an em-dash (`—`, ~12.5px in Arial/Roboto vs. 4.5px for `|`), pixel modeling must account for its wide footprint so titles stay strictly within Google's desktop cutoff without truncation.

---

## 10. Tool & Script Inventory

| Tool / Script | Authoritative Function |
| :--- | :--- |
| [`scripts/improve_seo_rewarm.py`](../../../scripts/improve_seo_rewarm.py) | **Post-enrichment edge re-warm loop (Invariant E):** per mutated URL, fires signed `X-SEO-Verify: 1` GETs with retry and failure isolation; worker bypasses L1/L2 cache reads, fresh-renders the enriched DOM, and atomically overwrites L1 + KV in the same request with crawler telemetry suppressed. |
| [`scripts/figiva_sweep_headers.py`](../../../scripts/figiva_sweep_headers.py) | **Sweep header minting (Invariant E):** prints curl-ready signed headers (`X-SEO-Prewarm`/`X-SEO-Verify` + `X-SEO-Sweep-Sig`) for one canonical path. |
| [`scripts/seo_optimizer_engine.py`](./scripts/seo_optimizer_engine.py) | **The Multi-Platform Correlation Engine:** Unifies GSC, Microsoft Clarity, PostHog, and Cloudflare into the 4 High-Leverage Pipelines, enforces guardrails against hallucinations, and ranks tasks by Potential Impact Score. |
| [`scripts/seo_growth_intelligence.py`](./scripts/seo_growth_intelligence.py) | **The Master Decision Engine:** Ingests multi-source telemetry, executes 6 opportunity detectors, classifies 8 diagnostic states, enforces URL ownership, computes $EV(a)$ expected values, and emits prioritized Action Queues. |
| [`scripts/gsc_analyzer.py`](./scripts/gsc_analyzer.py) | Multi-dimensional Search Console analyzer for joint page+query dimensions, striking distance, expected CTR residuals, and traffic decomposition. |
| [`scripts/dataforseo_client.py`](./scripts/dataforseo_client.py) | **Cost-Routed DataForSEO SERP Intelligence:** Standard Queue batch discovery at $0.0006/SERP (Live gated at $0.002), weak-spot vulnerability scoring, SERP feature extraction, `stop_crawl_on_match` rank tracking with refunds, offset deep-page crawling, and `--dry-run` cost plans. Credentials via `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD` (or `DFS_*`/`DATAFORSEO_API_KEY`) in `.env.credentials` — never hardcoded. |
| [`scripts/ltr_ranker.py`](./scripts/ltr_ranker.py) | **Learning-to-Rank Core Library:** exponential click grading, position-bias correction, cluster-integrity splitting, monotone constraints, native LightGBM persistence (no joblib/sklearn), pure-Python isotonic calibration, SHAP action prescription, and the 85/15 exploration/exploitation queue split. |
| [`scripts/collect_features.py`](./scripts/collect_features.py) | **Stage 1 Collector:** pulls real GSC performance via the `seo` binary, enriches top candidates through the DataForSEO Standard Queue, computes the 8-feature ranking matrix, and writes `data/ltr_features.json`. |
| [`scripts/train_ranker.py`](./scripts/train_ranker.py) | **Stage 2 Trainer:** trains the always-on rank_xendcg/LambdaRanker from the pooled outcome history (bootstrap SERP grades or real click buckets, adaptive `min_data_in_leaf`, heuristic init_score residual learning), calibrates margins onto Expected 30-Day Clicks when clicked outcomes exist, and persists the deployable bundle to `models/`. Refuses below 10 trainable rows. |
| [`scripts/score_backlog.py`](./scripts/score_backlog.py) | **Stage 3 Scorer:** ranks the collected backlog with the trained bundle, auto-trains one from bootstrap grades when no bundle exists (>= 10 rows), prescribes SHAP-driven actions, and emits the 85/15 `data/action_queue.json`. |
| [`scripts/fleet_ingest.py`](./scripts/fleet_ingest.py) | **Stage 1.5 Fleet Harmonizer:** pools GSC `(query, page)` rows from ALL authenticated properties into one domain-agnostic 8-feature schema (log-scaled volume, URL-path cluster IDs, neutral SERP-feature fills), dedupes with max-clicks-wins, and writes the pooled training history that powers cross-domain day-one training. |
| [`scripts/log_outcomes_and_retrain.py`](./scripts/log_outcomes_and_retrain.py) | **Stage 4 Loop Closer:** joins a previously executed queue against fresh GSC outcomes 30 days later, appends idempotently to the labeled history, and triggers retraining. |
| [`scripts/setup_observability.py`](./scripts/setup_observability.py) | Scans, validates, heals, and exports telemetry manifests (`DataSourceManifest`) and drop-in tracking snippets. |
| [`scripts/geo_evaluator.py`](./scripts/geo_evaluator.py) | Scores AI agent readiness, evaluates `llms.txt`, and validates Schema.org JSON-LD structured data. |
| [`scripts/run_audit.py`](./scripts/run_audit.py) | High-speed technical crawler pass for status codes, canonical consistency, and crawl budget parameter defense. |
| [`scripts/evaluate_experiments.py`](./scripts/evaluate_experiments.py) | **Outcome Evaluation & Two-Part Scorecard:** Tracks 7, 14, 28, 56-day outcomes in `experiment_ledger`, evaluates treatment vs matched-control cohorts (Difference-in-Differences), verifies Googlebot recrawl proof, updates `action_effectiveness_stats`, and renders the two-part scorecard. |
| [`scripts/content_usefulness_gate.py`](./scripts/content_usefulness_gate.py) | **Content Quality & Claim Provenance Gate:** Enforces anti-doorway distinctiveness, substantive content depth (>= 120 words), query fulfillment in headings, anti-vaporware copy bans, and verifies technical performance claims against code/benchmark evidence. |
| [`scripts/verify_technical_seo.py`](./scripts/verify_technical_seo.py) | **10-Point Technical SEO & Indexability Verification:** Audits HTTP 200, non-empty HTML, title geometry, single primary H1, canonical URL consistency, robots noindex defense, >= 2 crawlable internal links, JSON-LD schema validity, mobile viewport, and functional tool presence. |
| [`scripts/generate_wave_changelog.py`](./scripts/generate_wave_changelog.py) | **Wave Changelog & Audit Generator:** Natively produces standardized, auditable Markdown wave reports across 8 mandatory dimensions at `reports/seo-waves/<domain>/wave-<N>-<domain>-changelog.md`. |
| [`scripts/validate_wave_close.py`](./scripts/validate_wave_close.py) | **Automated Wave-Close Verification Gate:** Enforces that an SEO wave cannot be closed until its Markdown report exists, reconciles with the Git diff and backlog cursor in `fleet_state.db`, honors Invariant P6, and passes all contract checks. |
| [`schemas/seo-action.schema.json`](./schemas/seo-action.schema.json) | Standardized JSON Schema for prioritized, auditable SEO and CRO action cards. |
| [`schemas/data-source-manifest.schema.json`](./schemas/data-source-manifest.schema.json) | Declares connection status, freshness watermarks, and capabilities across all 7 telemetry platforms. |
| [`references/page_level_decision_engine.md`](./references/page_level_decision_engine.md) | Exhaustive guide on the 8-state diagnostic decision tree, 7 typed action contracts, URL ownership model, and 4 recipes. |
| [`references/gsc_multidimensional_playbook.md`](./references/gsc_multidimensional_playbook.md) | Exhaustive guide on extracting maximum value from GSC dimensions, decomposition math, and query clustering. |
| [`references/seo_growth_os_architecture.md`](./references/seo_growth_os_architecture.md) | The 3-plane system architecture, Cloudflare hybrid storage model, and tool responsibility boundaries. |
| [`references/conversion_diagnosis_and_experimentation.md`](./references/conversion_diagnosis_and_experimentation.md) | Joining search demand to conversions, PostHog funnels, Clarity heuristics, and matched-cohort experimentation. |
| [`templates/seo_action_queue.md`](./templates/seo_action_queue.md) | Executive markdown template for the prioritized action queue. |
| [`templates/experiment_plan.md`](./templates/experiment_plan.md) | Pre-formatted test plan for SEO matched-cohort and CRO visitor-level experiments. |

---

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



