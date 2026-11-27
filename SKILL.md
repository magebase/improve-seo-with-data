---
name: improve-seo-with-data
description: >-
  The authoritative, multi-source SEO Growth & Conversion Operating System. Use this skill whenever you need to audit, diagnose, optimize, or scale a website's organic search visibility, conversion funnels, or AI search presence using real data. Automatically fetches, correlates, and joins Google Search Console (GSC joint page+query performance, devices, indexation), Microsoft Clarity (heatmaps, rage clicks, dead clicks, scroll depth drop-offs), PostHog (organic conversion funnels and user journeys), Cloudflare (TTFB, Core Web Vitals LCP/INP/CLS, edge 5xx/404 logs), Better Stack (uptime incidents), and live SERP competitor DOMs. Enriches every opportunity with external DataForSEO SERP intelligence (weak-spot detection, SERP feature crowding, cost-routed queue vs live fetching) and predicts pre-launch keyword ROI with LGBMRanker before spending crawl budget. Formulates prioritized, effort-adjusted Action Queues and executes rigorous SEO matched-cohort and CRO experiments.
---

# improve-seo-with-data: The SEO & Conversion Growth Operating System

An autonomous, data-first SEO engineering, conversion optimization, and Generative Engine Optimization (GEO) system for **Antigravity CLI (`agy`)**, **Claude Code**, and engineering fleets.

Eliminates speculative "best practices", subjective design opinions, and isolated dashboards. Turns multi-dimensional performance data into a prioritized, revenue-weighted growth engine that identifies where search visibility exists, diagnoses why it is not producing clicks or conversions, and continuously executes changes that compound business outcomes.

> **Start every run with the execution loop, not the diagnosis.** `scripts/growth_loop.py plan` must return at least one action. If the launch gate rejects every new route, the planner still selects the highest-lower-bound existing-page improvement, indexation fix, or measurement task. The `guarantee` field distinguishes a real click-lift action from maintenance and instrumentation — never describe the latter two as ranking wins.

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

### 4.1 Indexation Forecasting & Evidence-Gated Page Creation

Position 90+ is a demand-absence signal, not demand. The skill therefore no longer treats `current_pos >= 90` as permission to create a URL. Every `CREATE_PROGRAMMATIC_ROUTE` task must clear `scripts/indexation_forecast.py::evaluate_launch_candidate`:

1. **Real demand evidence** — GSC impressions (`>= 10`) or a real search-volume signal. Synthetic pairwise rows with `impressions=0` and no volume are never launch candidates.
2. **Live data depth** — at least three unique live data fields (or the template family's declared requirement). A country page needs live numbers; a comparison page needs spec rows; a tool needs a working input/output.
3. **Sibling uniqueness** — nearest-sibling similarity `<= 0.50`. A page that is 70% identical to its siblings is a duplicate, not a new intent.
4. **Indexed link equity** — at least three inlinks from already-indexed pages.
5. **Unclaimed intent** — no existing page already owns the query.
6. **Calibrated probability floor** — `P(indexed within 28d) >= 0.80` with an 80% lower bound `>= 0.70`, and `P(indexed within 56d) >= 0.85` with a lower bound `>= 0.70`.

The model is trained on `page_launch_outcomes` (URL Inspection coverage state + GSC, recorded at launch and updated at 7/28/56 days). The transparent prior is used until at least 20 labelled outcomes exist, so the gate works on a brand-new domain with zero historical indexation data. DataForSEO supplies the cold-start demand/competition evidence: Keywords-Data search volume plus cached SERP features (forum ratio, exact-match rate, pixel crowding). Volumes are stored on the same 30-day `dfs_serp_cache` row as the SERP result and reused across invocations; only missing queries are priced. No page-count cap is applied: every candidate that clears the gate may launch; candidates that fail are discarded, not replaced with synthetic filler.

**Fail-closed evidence contract.** Every new URL must be evaluated before creation:

1. **SERP intent match** — the planned template must match the dominant top-10 archetype; a consumer verification query is never attached to a comparison/troubleshooting URL.
2. **SERP data present** — `serp_fetched` must be true with non-empty `serp_item_types`; otherwise the candidate is `unscored_missing_serp`, never scored on a zero vector.
3. **Real demand only** — Keywords-Data volume for a new route; missing volume is absent, never fabricated from impressions or another query.
4. **Dry-run payload depth** — `unique_data_fields` comes from the page generator's payload, not the live DOM. Supply it with `--page-contracts contracts.json`; the contract also carries `planned_indexed_inlinks` (hub pages that will link on deploy) and `non_boilerplate_ratio`.
5. **Template litmus** — if hiding the variable (country/app/service) leaves no meaningfully different content, or stripping the data collapses the page, the template is rejected (`non_boilerplate_ratio < 0.50`).
6. **Planned indexed inlinks** — a new URL cannot already have live inlinks; use `planned_indexed_inlinks` from the routing/hub config. Existing pages use live `inlinks_from_indexed` and are never launch candidates; they are `existing_page_requires_enrichment`.

**Entity-level routing.** Related-search variants are collapsed onto one canonical entity URL (`gmail`/`google` -> `/verify/google/`, `discord` -> `/verify/discord/`). A query never becomes a raw slugified URL. Queries requiring a capability the product does not have (outbound `send sms`, voice calls, paid private numbers) are rejected before scoring.

**Off-page authority is a separate gate.** Run `python scripts/authority_report.py --target <domain> --competitors <csv>` before assuming on-page work can rank. DataForSEO backlinks exposes domain rank, referring domains, and spam score; a domain with `rank 0` and a handful of referring domains cannot outrank established competitors through template changes alone.

**Domain health before a canary.** A new-template canary is confounded while the existing domain is unhealthy. `domain_health_gate` blocks canary selection until the measured baseline reaches `--min-domain-index-rate` (default 65%). It uses cached URL Inspection coverage, not impressions.

**Canary proof before scale.** A template is never scaled from a static score:

1. Ship a 10–20 URL canary cohort from `build_canary_cohort` and isolate it in a dedicated sitemap (`canary_sitemap`).
2. Inspect the cohort through GSC URL Inspection at days 7, 14 and 21.
3. Call `evaluate_canary_outcomes`; scale only when at least 80% are indexed and the cohort has non-zero impressions.
4. Record every launch in `page_launch_outcomes`; `dead_route_candidates` flags routes still unindexed and unseen after 45 days for merge, enrichment, or `noindex`.

**GSC limits:** URL Inspection is 2,000/day and 600/minute per property; use `sc-domain:<domain>` for domain properties and exact URL-prefix properties otherwise. Search Analytics caps at 25,000 rows sorted by clicks and lags about 48 hours; do not treat a zero-row day 3 as a ranking failure. Prefer the inspection verdict for indexation, and evaluate impressions over 14–21 days.

```bash
# Record/fit/backtest the indexation model
python scripts/indexation_forecast.py --state-db ~/.seo_fleet/fleet_state.db --fit
python scripts/indexation_forecast.py --backtest-json labelled-records.json
python scripts/indexation_forecast.py --candidate-json candidate.json

# Evaluate new routes with dry-run payload contracts (never the live DOM)
python scripts/collect_features.py --site smsriver.com \
  --state-db ~/.seo_fleet/fleet_state.db \
  --page-contracts contracts.json --output data/ltr_features.json
python scripts/score_backlog.py --features data/ltr_features.json \
  --canary-size 20 --compile-wave 20
```

### 4.2 Unified pSEO State Machine (Repair → Contract → Pilot → Scale)

`scripts/seo_factory.py` turns the launch gate into a lifecycle. The fleet DB is the single source of truth: `clusters`, `page_contracts`, `cohorts`, `url_lifecycle`, and `repair_actions` sit alongside the existing GSC/SERP/inspection tables. Keep the DB on persistent disk (`~/.seo_fleet/`), never in `/dev/shm`; a reboot would erase multi-week cohort history.

**Existing-site repair.** `repair-plan` classifies every current URL before any new page is considered:

- `PROTECT` — any click in 90 days, indexed with impressions, or a hard-locked route; never touched by a prune batch. Backlinks alone do not protect a page: they make an ancestor merge the preferred option so the equity survives.
- `MERGE_301` — only a genuine **ancestor** replacement (`/country-codes/germany/` → `/country-codes/`). A generic `/compare/` or `/guides/` hub is not a replacement unless the source value was actually absorbed or it has **legitimate referring domains**; PBN-only backlinks do not count, and those sources are `GONE_410`. A hub is never redirected into a child, and unrelated pages are never bulk-redirected to `/`.
- `NOINDEX` — user-facing routes with no search intent (`/status/`, `/workbench/`); strip from sitemaps, do not robots-block.
- `ENRICH` — demand or live inventory exists but value does not; add first-party telemetry instead of minting a new URL.
- `GONE_410` — zero clicks, zero backlinks, no ancestor, no utility.

**Data-moat contracts.** `page_contracts` binds every Tier B page to a dry-run payload: `data_source_hash`, at least 3 unique data fields, entity-stripped overlap ≤ 0.45, at least 3 planned indexed inlinks, and a cluster. `compute_stripped_overlap` is the CI check: strip country/app/brand tokens and measure shingle overlap on the remaining prose.

**Outside-in winnability.** `evaluate_cluster` requires aggregate demand ≥ 500 searches/month across **at least 15 valid entities**, plus at least 2 weak top-10 slots (UGC or ≤ 250 referring domains), before a cluster can become a pilot. It is data-in, no fabricated volume. `discover` aggregates the whole keyword-pattern list, not one keyword at a time, and always emits a funnel: `raw_suggestions → raw_ideas → valid_entities → aggregate_demand → serps_checked → weak_top10_slots → rejection_reason`. `discover` calls both Labs `keyword_suggestions` (exact-match seed phrasing) and `keyword_ideas` (varied entity phrasing), keeps the per-keyword volume floor at 10, and applies **no** `keyword_difficulty` input filter: difficulty is a Labs estimate, while the live SERP + Backlinks stage measures the actual top-10 authority. An empty result with `no_valid_entities` is a parser/volume problem; an empty result with `insufficient_demand` or `top10_too_authoritative` is the gate working.

**Cohort state machine.** A pilot is 5–15 URLs in a dedicated sitemap, measured at days 7/14/21/45:

- `PILOT_LIVE` → `SCALING` only at ≥ 80% indexed **and** non-zero impressions.
- Day-21 indexation below 50% → `FROZEN` and the contract is reviewed.
- Day-45 unindexed with no impressions → `PRUNE` back into the repair queue.

```bash
# Existing URL triage (writes url_lifecycle)
python scripts/seo_factory.py repair-plan   --input url_rows.json --sitemap-file sitemap_urls.json   --domain smsriver.com --persist

# Cap the indexable footprint to ~15-20 strong URLs
python scripts/seo_factory.py finalize --input repair_plan.json \
  --keep-limit 18 --output final_footprint.json

# Validate/register dry-run contracts
python scripts/seo_factory.py contracts --input contracts.json

# Outside-in discovery (real Labs volume + SERP + Backlinks authority)
python scripts/seo_factory.py discover --seeds "iban format,swift code,port number" \
  --niche finance --limit 100 --max-keywords 5 --output clusters.json

# Offline cluster gate
# Outside-in discovery: one winnable cluster + reviewable (INVALID) drafts
python scripts/seo_factory.py discover --seeds "bin lookup,iban validator" \
    --niche finance --domain binvalidator.com \
    --contracts-output data/draft_contracts.json --output data/cluster.json

# Track 2: collect live first-party benchmark telemetry into contracts
python scripts/collect_live_benchmarks.py \
    --sitemap https://browseservers.com/benchmarks-sitemap.xml \
    --cluster-id cl_xxx --domain browseservers.com \
    --state-db ~/.seo_fleet/fleet_state.db --output data/pilot_contracts.json

python scripts/seo_factory.py cluster-check --input cluster.json

# Pilot lifecycle
python scripts/seo_factory.py cohort-create --template verify-entity   --domain smsriver.com --urls urls.json
python scripts/seo_factory.py cohort-measure --cohort coh_...   --day 21 --indexed 8 --total 10 --impressions 120
```

**Discipline:** an existing domain below 65% active-sitemap indexation does not get a new-template pilot. Run `repair-plan` and `ENRICH` first. A fresh domain may start with 1–2 Tier A authority assets plus one 5–15 URL Tier B pilot.

### 4.2.1 Pilot Containment (Mandatory)

A pilot is a controlled test, not a small version of the full site.

- Submit **only** the pilot sitemap: 10-15 new template URLs plus their parent hubs (at most 30 total). Never submit the site-wide sitemap on a cold host while a template is being proven.
- Keep non-pilot routes `200` for users but send `X-Robots-Tag: noindex, follow`; do not let them enter the sitemap or the crawl-priority graph.
- Give every pilot template one distinct search intent from its parent hub. If the hub targets ``"<entity> server list"``, the pilot must target ``"<entity> live player count"`` / ``"server stats"`` / ``"population by country"``; never reuse the hub's primary query in the title, H1 or lead.
- Use a stable pilot sitemap with a hysteresis floor, not a live-count filter: a transient dip stays `200`; sustained low sample flips `noindex` and leaves the sitemap; only retired entities return `404`/`410`.
- Do not buy links, post to communities or scale past the pilot until the cohort clears the 80% indexation gate. A lab on a disposable subdomain must not accumulate off-page equity that has to be migrated later.

### 4.3 The Positive-Expectation Invocation Loop (v3.0)

The earlier versions of this skill were **gate-heavy**: they could correctly refuse a bad page and still return an empty queue. That is a safety property, not a growth property. The 2026-11-26 SMSRiver run exposed the gap: 1,064 candidates produced 0 new routes, 867 existing pages were identified as enrichment work, and the operator was left holding a diagnosis rather than an executable next step.

**Self-critique of the pre-v3 loop**

1. **A score is not an action.** The ranker ranked *candidates*; it did not own a portfolio of launch, enrichment, internal-link, technical and measurement actions with marginal cost.
2. **The indexation gate had a zero-solution.** When every new route failed, the run had no fallback that improved the pages already indexed. A filter that returns zero does not increase indexation or ranking.
3. **Indexation probability was modelled; ranking probability was not.** `evaluate_launch_candidate` answers "will Google index this?" but not "will this page reach the top 10?" The two probabilities have different features and different failure modes.
4. **The fast cursor could lease zero.** `score_backlog.py --state-db` returns leased tasks only; a drained backlog produced a successful-looking empty invocation.
5. **Repair, discovery and the queue were separate state machines.** `repair-plan`, `discover`, `score_backlog` and `experiment_ledger` did not share one action ledger, so the same work could be re-recommended or never closed.
6. **No mandatory review surface.** The experiment ledger had DiD machinery, but no single command forced an owner to record baseline → action → due review → outcome for every intervention.
7. **No honest guarantee label.** A measurement task and a ranking intervention were both rendered as "actions", letting an agent imply a ranking win where no ranking work happened.

**The v3 invocation contract**

Every invocation must call the planner and must end with a non-empty action plan:

```bash
python scripts/growth_loop.py plan \
  --features data/ltr_features.json \
  --action-queue data/action_queue.json \
  --state-db ~/.seo_fleet/fleet_state.db \
  --domain smsriver.com --limit 5 --record \
  --output data/growth_plan.json

# after shipping the selected action(s)
python scripts/growth_loop.py complete <action_key> --commit-sha <sha>

# at the 21-day review
python scripts/growth_loop.py review --observations observations.json --domain smsriver.com
python scripts/growth_loop.py status --domain smsriver.com
```

The planner draws from four portfolios and ranks them on a common click-equivalent scale. Two hard gates prevent the "never empty" rule from turning into busywork:

- **Indexation prerequisite track.** A URL that is explicitly `Crawled - currently not indexed`, `Discovered - currently not indexed`, canonicalised away, or excluded gets `ENRICH_UNIQUE_DATA` / `FIX_INDEXABILITY` / hub-inlink work first. Title and meta edits are forbidden until the URL is indexed. A `Crawled` verdict means the content is the problem; a `Discovered` verdict means the link graph is the problem.
- **Materiality floor.** An action earns `positive_expected_click_lift` only when `expected_clicks_lower_90d >= 10`. A 0.02-0.4 click/90d title tweak is unmeasurable noise, not growth; below the floor the plan emits `BUILD_TIER_A_ASSET` (or `RUN_DISCOVERY`) and labels the run `below_materiality_floor`.

| Portfolio | Action codes | What "improvement" means |
| :--- | :--- | :--- |
| **GROW** | `LAUNCH_PSEO_ROUTE`, `CREATE_PROGRAMMATIC_ROUTE` | demand + payload contract + indexation gate cleared |
| **IMPROVE** | `INJECT_SECONDARY_H2_ONLY`, `REWRITE_TITLE_META`, `ENRICH_UNIQUE_DATA`, `REFRESH_STALE_CONTENT` | measured GSC/SERP gap on an existing URL |
| **CONNECT** | `INJECT_CONTEXTUAL_INLINK` | indexed link equity to a page that has impressions but too few inlinks |
| **MAINTAIN** | `FIX_INDEXABILITY`, `REQUEST_INDEXING`, `CONSOLIDATE_CANNIBALIZED_URLS`, `PRUNE_OR_NOINDEX` | a crawl/index defect that blocks every other gain |
| **MEASURE** | `MEASURE_OUTCOME`, `INSTRUMENT_TELEMETRY` | closes the loop or establishes the baseline; **never** claimed as a ranking lift |

**Ranking probability prior.** `estimate_ranking_probability` returns `p_top10`, `p_top3`, their lower bounds, and the model name. It is a transparent logistic prior over position, SERP openness (forum share, competitor title match, pixel crowding), internal-link equity, content depth, demand and the weakest-top-10 referring-domain gap, multiplied by the indexation probability. It is deliberately **not** presented as a calibrated Google probability; it becomes empirical as `action_effectiveness_stats` accumulates real experiments. The title-edit lift is explicitly conditional on indexation:

$$
\Delta\text{clicks}_{title} = p_{index}(1.0) \times p_{top10} \times \Delta CTR \times \text{impressions}
$$

and `p_top10` is multiplied by an authority ratio curve:

$$
authority\_factor = \min\left(1, \max\left(0.02, \sqrt{\frac{host\_legitimate\_RD}{weakest\_top10\_RD}}\right)\right)
$$

With 42 referring domains against a 674-RD competitor the factor is ~0.25; against a 2,390-RD competitor it is ~0.13. When either referring-domain field is missing the factor is conservatively 0.35 and marked `authority_source: missing`, never silently 1.0. The action score is:

$$
\text{score}(a) = \frac{\mathbb{E}[\Delta\text{clicks}_{90d} \mid a] \times p_{lower}(a)}{\text{effort\_hours}(a)}
$$

**Honest guarantee labels.** The plan's `guarantee` field is one of:

- `indexation_prerequisite` — a known unindexed/canonical/excluded URL exists; indexation work is selected before any CTR or ranking action, and no click lift is claimed.
- `positive_expected_click_lift` — at least one selected action clears the 10-click/90d lower-bound floor. This is the only label that supports a claim of likely improvement.
- `maintenance_only` — only indexation/hygiene actions remain and no URL is explicitly blocked.
- `below_materiality_floor` — every on-page action is below the measurable click floor; the plan emits `BUILD_TIER_A_ASSET` or `RUN_DISCOVERY` instead of shipping busywork.
- `measurement_only` — all known actions are already open; the run measures instead of duplicating work.
- `information_only` — no measured pages or backlog exist; the run instruments telemetry and says so.

The planner never emits a `LAUNCH_*` action as a fallback. A zero-evidence domain receives telemetry work, not a fabricated page. An invocation is allowed to say **"no positive click-lift action exists; here is the measurement that unblocks the next one"** — that is honest and still advances the loop. What it may not do is return an empty queue or call a measurement a ranking win.

**Stateful rules**

- `score_backlog --keep-urls/--sitemap` scopes the emitted queue **and** the state-DB cursor to the declared indexable footprint. A retired/noindex page with residual GSC rows never gets a title, inlink, or launch task.
- `growth_actions.action_key = hash(domain, page, query, action_code, target)`. An `OPEN` or recently `SHIPPED` key is never re-emitted inside the cooldown.
- `plan --record` writes the run and opens its actions; `complete` marks the shipped action and sets a 21-day review date; `review` compares clicks/position against the recorded baseline and marks `SUCCESS` or `FAILED`.
- A successful action raises the measured prior for that action/route family; a failed action is not repeated by the next run.
- A review is only eligible to update effectiveness when its recorded baseline has at least 200 impressions; below that the action is marked `INSUFFICIENT_BASELINE` and no model learns from the noise.
- A review whose observation window overlaps a known Google core/spam rollout is marked `QUARANTINED_CORE_UPDATE` and never fed into `action_effectiveness_stats`.
- `measurement_only` and `information_only` runs are visible in `growth_runs` so an operator can see the difference between a week of experiments and a week of diagnostics.

**The one guarantee this skill can honestly make:** every invocation leaves the site with either (a) a positive lower-bound click-lift action, (b) a bounded indexation fix, or (c) the measurement needed to make the next decision. It cannot guarantee Google will index or rank a page, and no honest SEO system can.

### 4.4 First-Party Telemetry Enrichment Contract

Programmatic pages must never rely on entity-name substitution around static prose. Before a route can pass `page_contracts` for launch or `ENRICH`, at least three independent metrics must come from the site's own database, logs, or scheduled probes, spanning at least two of these primitives:

1. **Observed performance / compatibility** — verified success rates, uptime, pass/fail matrices over 7d/30d.
2. **Inventory freshness / churn** — active count, median record age, additions/removals, last-verified timestamp.
3. **Activity / velocity** — rolling throughput (24h/7d/30d), median interval, peak windows.
4. **Structural composition** — provider, carrier, format, price-band, or prefix distribution.
5. **Friction / outliers** — failure reasons, latency percentiles, saturation, delta vs site median.

Hard gates:

- **SSR visibility.** The telemetry summary and tables are in the initial HTTP 200 HTML, not behind client-only fetches.
- **Cross-sibling variance.** Every required field must vary across sibling URLs; constant values (`active_lines: 1` on every page) do not count toward `unique_data_fields`.
- **Entity-stripped overlap.** After removing entity names and nav/footer boilerplate, sibling shingle overlap must be `<= 0.45`.
- **Sample / freshness guard.** A route below `min_sample_size` or stale beyond `max_staleness_days` drops to `noindex, follow` and leaves the sitemap; it is never an empty shell of zeros.
- **UGC isolation.** Raw inbound messages, comments, and scraped text are sanitized or secondary; untrusted spam must not define the indexed page.
- **Deterministic first, LLM last.** All numbers, ranks, and outlier flags are computed in SQL/Python before templating. Generated prose may only interpret the computed JSON; if removing the numbers leaves generic filler, reject it.

This is the pattern that makes country/entity pages genuinely distinct: a country hub publishes observed app compatibility, pool freshness, message velocity, carrier/prefix mix, and saturation from its own logs. A competitor or LLM can copy the layout but cannot fabricate the measured rows.

### 4.5 Mandatory Invocation Output: Machine Learning Model Transparency & SHAP Attribution

Every executing agent and autonomous SEO engine invocation MUST explicitly output the **Machine Learning Model Decision & SHAP Attribution Summary Block**. The operator and user must never have to guess whether a machine learning model was used, which features drove priority, or why specific tasks were selected.

#### Mandatory Terminal Output Format

When running `score_backlog.py` (or executing an autonomous wave), the tool outputs and the agent MUST present the structured decision block:

```text
================================================================================
MACHINE LEARNING MODEL DECISION & SHAP ATTRIBUTION SUMMARY
================================================================================
Engine Objective: LGBMRanker (rank_xendcg) | Mode: trained_model
Bundle Path: models/seo_lgbm_ranker.txt (8 engineered ranking features)
Residual Baseline: init_score = log10(impressions + 1) * (TargetCTR - CurrentCTR) * ConvValue
Monotone Constraints: [+1 centroid_sim, +1 forum_ratio, -1 title_exact_match, -1 pixel_crowding, +1 hub_links, 0 current_pos, +1 volume_log, +1 conversion_intent]
--------------------------------------------------------------------------------
Task ID   Slot      Action                           Score   EV ($)  Top SHAP Drivers                Rationale
--------------------------------------------------------------------------------
1475      exploit   INJECT_EXACT_TITLE_AND_H2         1.56    18.50  +0.38 imp, -0.25 pos, +0.14 ...  Prioritized striking-distance query 'figma to html converter'; title/H2 token match deficit yields high expected CTR lift.
1476      exploit   ADD_D1_SPEC_COMPARISON_TABLE      1.42    14.20  +0.42 missing_table, +0.31 ...   Competitor DOM analysis indicates structured data table deficit for 'figma to webflow'; prioritized for search conversion.
1477      exploit   WIRE_HUB_AND_FOOTER_INLINKS       1.35    12.00  -0.38 hub_links, +0.25 auth      Negative hub internal linking attribution detected; contextual link injection elevates PageRank equity.
1491      exploit   OVERHAUL_CTR_HOOK_AND_WEBAPP_...  1.28    11.40  +0.45 imp, -0.39 zero_ctr        High impressions with zero clicks indicates snippet presentation failure for 'ai figma design'; hook rewrite unlocks CTR.
1492      explore   INJECT_EXACT_TITLE_AND_H2         0.92     6.80  +0.22 imp, +0.15 intent          Exploratory striking-distance expansion on high-intent token set to test counterfactual ranking elasticity.
1493      explore   CREATE_PROGRAMMATIC_ROUTE         0.88     5.50  +0.50 uncaptured_demand          Uncaptured search demand on query 'figma to tailwind conversion'; prioritized dedicated programmatic route creation.
================================================================================
```

#### The 6-Stage Autonomous Engineering Lifecycle

All SEO improvements across the fleet follow an immutable 6-stage lifecycle:

1. **Stage 1: Multi-Source Feature Collection (`collect_features.py`)**  
   Pulls empirical GSC query performance (`dimensions: ["page", "query", "device"]`), crawls competitor DOMs for semantic gaps, inspects coverage states, and calculates the 8-feature ranking matrix (`ltr_ranker.FEATURES`).
   *(Sibling delegation: use `seo` MCP for ad-hoc site crawls/AI-readiness reports, and `dc-gyc` for AdSense NNLS RPM & TECP abandonment guardrails.)*
2. **Stage 2: Learning-to-Rank Opportunity Scoring & Stratified Leasing (`score_backlog.py`)**  
   Scores candidates with the `LGBMRanker` (`rank_xendcg`) booster, extracts Tree SHAP contributions (`pred_contrib=True`), maps actions to bottlenecks, evaluates expected commercial value, and draws an 85/15 exploit/explore wave cursor partition.
3. **Stage 3: Design-Driven ATDD & Atomic Implementation**  
   Prior to touching production views or templates, acceptance tests (`pytest-bdd`) are authored reflecting the exact prompt, query, and assertions. Implementations enforce the 1440px canonical viewport, clean SVG IconKit icons, and a strict ban on emojis (Rule 32).
4. **Stage 4: Edge Deployment, Zone Cache Purge & Re-warm (`wrangler deploy` + `improve_seo_rewarm.py`)**  
   Deploys to Cloudflare Workers, purges only the modified tenant zone (`--zone <domain>`), and immediately re-warms 100% of routes with signed `X-SEO-Verify: 1` headers to prevent cold crawler latency.
5. **Stage 5: Standardized Wave Changelog Generation & Strict Wave-Close Validation (`generate_wave_changelog.py` + `validate_wave_close.py --strict`)**  
   Generates the authoritative wave changelog including `Part 1: Engineering Execution Quality`, `Part 1.1: Machine Learning Model Decisions & Feature Attributions (Tree SHAP)`, and `Part 2: Measured SEO & Business Effectiveness` (marked `NOT YET MEASURED` per Invariant P6). Blocks wave completion if any section, file, or test execution count fails reconciliation.
6. **Stage 6: 28-Day Causal Outcome Verification & Ranker Retraining (`log_experiment_outcomes.py` + `train_ranker.py` + `indexation_forecast.py`)**
   Following verified Googlebot recrawls and the 28-day observation window, Difference-in-Differences (DiD) lifts are evaluated against matched cohorts, registered in the `experiment_ledger`, and fed back to retrain the `LGBMRanker` bundle. New-route launches are recorded in `page_launch_outcomes` at creation and updated from URL Inspection at 7/28/56 days; the indexation model is refit from those labels so the next launch decision is based on observed coverage, not position.

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

1. **Demand-First Candidate Depth (no synthetic route quota):** A 150-row pool is a reporting target, never a licence to invent pages. `collect_features.py::ensure_candidate_depth` may still surface GSC rows, sitemap orphans, and DataForSEO suggestions, but the pairwise/three-way matrix rows are **suggestions only**. They must never become `CREATE_PROGRAMMATIC_ROUTE` tasks unless they independently carry real demand, live-data depth, sibling uniqueness, indexed inlinks, and a calibrated indexation probability (Section 4.1). Returning fewer than 150 candidates is correct when the demand graph is exhausted; the run reports the shortage instead of fabricating routes.
   - **Tier 1 — GSC rows** (real demand signals, minus recently shipped pairs).
   - **Tier 2 — sitemap orphans** (existing deployed routes; rescue links, never new URLs).
   - **Tier 3 — catalog pairwise matrix** (`pairwise_matrix_from_sitemap`: entity vocabulary from existing family routes $\times$ unbuilt pairs; suggestions only, demand verified before launch).
   - **Exhaustion guard (Tier 3.5):** when the pairwise space is exhausted OR the fleet's pending task backlog drops below 200 rows, `ensure_candidate_depth` engages `three_way_matrix_from_sitemap` as **suggestion expansion only**; it never authorises a new URL.
   - **Tier 4 — DataForSEO suggestions** (the only costly tier; gated, last resort; suggestions still pass the Section 4.1 launch gate).
2. **Fleet State Machine (`--state-db`):** All runs operating on an enrolled property MUST pass the SQLite state DB (WAL mode + busy timeout, safe under concurrent invocations): a **24h GSC snapshot** fast path, a **30-day shared SERP cache** layer, and a **daily DataForSEO budget gate** consulted BEFORE any network call. Atomic tasks live in a strict cursor: `PENDING -> LEASED -> SHIPPED` (with commit SHA) — leased in ONE atomic `UPDATE ... RETURNING` statement so two concurrent invocations can never lease the same task; a `(page, action_code)` pair that is already open is never re-enqueued. Crashed agents' leases auto-expire back to `PENDING` after 1 hour (`release_stale_leases`), and the Stage-4 rollback detector records `SHIPPED -> REVERTED` (terminal, audit trail preserved — reverted waves never re-enter the cursor to thrash the same page). `PENDING -> REJECTED` (terminal) is written by cursor hygiene for queries that can never be addressed by a single-heading edit.
   - **Stratified leasing (`lease_tasks`):** leases are drawn via a window-function ranking PARTITIONED BY `route_family` (first path segment of the task URL), with `family_caps` (e.g. `{"number": 3}`) + `default_family_cap` so one template family can never eat the whole wave quota, AND a second window rank PARTITIONED BY `action_code` enforcing **task-type quotas** (`type_caps`/`default_type_cap`; `DEFAULT_TYPE_CAPS` = 8x `ADD_D1_SPEC_COMPARISON_TABLE`, 8x inlinks (`BOOST_CLUSTER_CROSS_LINKS` + `STRENGTHEN_HUB_INTERNAL_LINKS`), 6x `OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA`, 5x title/H2 intents (`INJECT_EXACT_TITLE_AND_H2` + `INJECT_EXACT_H2_AND_TITLE`), 3x `CREATE_PROGRAMMATIC_ROUTE` — every wave ships a mix of work products, not 30 identical heading checks), a **single task per unique URL constraint** (`ROW_NUMBER() OVER (PARTITION BY page ORDER BY priority_score DESC) AS page_rank` with `page_rank = 1` preventing duplicate-URL task pairs from burning multiple lease slots in the same wave), and a **file_target collision lock**: a PENDING task whose `file_target` is actively LEASED elsewhere is skipped (two agents can never edit the same file at once). `NULL`/empty file_targets are exempt.
   - **Pre-lease cursor hygiene (`scripts/cursor_hygiene.py`, wired into BOTH lease paths of `score_backlog`):** before any lease, `preflight_hygiene` (1) terminally `REJECT`s junk queries (`site:`/`inurl:`/`intitle:`/`filetype:` operators, raw URLs, uppercase Boolean `OR`/`AND`, `-negation` terms, >15% non-ASCII, probable non-English function words — lowercase `and`/`or` as ordinary words survive), (2) terminally `REJECT`s inlink tasks for the root homepage `/` (every page already links to `/` via the brand header/footer), (3) **graduates** `INJECT_*` tasks whose query tokens are already fully covered by the route/country intent map (`--intent-map`, JSON `{page: rendered_text}`; the executing agent regenerates it from `route_search_intent.py`/`country_search_intent.py` + live DOM after each wave) straight to `SHIPPED` — no duplicate intent H2s, (4) skips pages/file_targets under another agent worktree's registered lock prefix, and (5) enforces a **max-2 intent tasks per URL** cap. `REJECTED` rows are never re-enqueued (`enqueue_tasks` honors the terminal state).
   - **Worktree lock registry (`~/.seo_fleet/worktree_locks.json`):** agents register their owned route/template prefixes at wave start (`register_worktree_locks`, PID + 2h heartbeat TTL — dead PIDs and stale heartbeats self-expire); `active_locked_prefixes` feeds pre-flight so concurrent waves never lease each other's routes. At wave closeout the agent MUST call `release_deferred_leases_on_closeout(conn, deferred_ids)` to return agent-deferred LEASED tasks to `PENDING` immediately (they otherwise strand for the full 1h stale-lease TTL and block their file_targets). `cursor_hygiene.py` is also a thin CLI: `--state-db --release-deferred 12,13` and `--register-locks "/prefix/ ..."`.
   - **Cursor starvation guard:** `score_backlog --replenish-below N` refills the backlog to full candidate depth whenever pending rows fall below `max(replenish_below, lease_size)`; the fast lease path (pending above threshold, <0.5s, zero network) keeps the lease loop cheap when no refill is due.
3. **URL Inspection CoverageState Enrichment (`--state-db` + default on):** zero-impression candidates are enriched via `inspect_coverage_states` (GSC URL Inspection API, 2,000 free calls/day/property; results cached 7 days in the state DB, every call counted against a daily gate). The coverageState tells the compiler WHY a route has no impressions: `Crawled - currently not indexed` -> thin-content gate (`ADD_D1_SPEC_COMPARISON_TABLE`), `Discovered - currently not indexed` -> discovery gate (`RESCUE_ORPHAN_ROUTE_INLINKS`). Bound per run with `--inspect-limit` (default 40).
4. **Atomic TDD Wave Compilation (`--compile-wave N`, target 35-60):** `compile_wave_backlog` decomposes each scored row into INDEPENDENT atomic tasks — one (page, action) each, cooldown-masked against the shipped ledger, deduplicated, each carrying a concrete `file_target` and a machine-checkable `tdd_assertion` a coding agent can run verbatim. Canonical action codes: `BOOST_CLUSTER_CROSS_LINKS`, `OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA`, `INJECT_EXACT_TITLE_AND_H2`, `STRENGTHEN_HUB_INTERNAL_LINKS`, `CREATE_PROGRAMMATIC_ROUTE`, `RESCUE_ORPHAN_ROUTE_INLINKS`, `ADD_D1_SPEC_COMPARISON_TABLE`, `INJECT_PAA_SEMANTIC_SECTIONS`, `ADD_WEBAPP_JSONLD_SCHEMA`, `REWRITE_HIGH_CONTRAST_TITLE`.
   - **Indexation launch gate (mandatory):** `CREATE_PROGRAMMATIC_ROUTE` is emitted only when `evaluate_launch_candidate` returns eligible. The task carries `p_index_28d`, `p_index_56d`, and the exact `launch_evidence` used. A route blocked by the gate is discarded; the compiler never substitutes a lower-evidence page to fill the wave.
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

# Stage 3.5: ALWAYS produce a non-empty positive-expectation plan, even when
# the gate correctly rejects every new route. This is the execution loop.
python3 scripts/growth_loop.py plan \
    --features data/ltr_features.json --action-queue data/action_queue.json \
    --state-db ~/.seo_fleet/fleet_state.db --domain smsriver.com \
    --limit 5 --record --output data/growth_plan.json

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
| [`scripts/growth_loop.py`](./scripts/growth_loop.py) | **Positive-Expectation Invocation Planner:** merges the ranked queue, measured GSC/SERP gaps, repair actions and due experiments into one non-empty action plan; scores actions by lower-bound expected click lift / effort, carries a transparent ranking-probability prior, dedupes OPEN/SHIPPED keys, and records the baseline → 21-day review loop. |
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

---

## 11. Superseded Version Notes (Archived)

The historical v2.x wave notes, statutory tax/insurance tables, and repeated operating upgrades that previously filled the rest of this file are preserved verbatim in [`docs/history/superseded-version-notes.md`](./docs/history/superseded-version-notes.md). They are **reference history, not the active contract**. The active contract is:
- Sections 1-10 above for diagnosis, telemetry, ranking, indexation, repair, and tool inventory.
- Section 4.3 for the positive-expectation growth loop.
- Section 4.4 for first-party telemetry enrichment.
- Section 4.5 for the ML/SHAP invocation output.

Do not add a new `v2.x` section for a future change. Amend the canonical section instead.
