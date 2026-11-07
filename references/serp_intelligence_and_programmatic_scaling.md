# SERP Intelligence & Programmatic Scaling Playbook

> Companion to `SKILL.md` Workflows 6. This is the deep playbook for external
> SERP intelligence (DataForSEO), predictive pre-launch ranking (LGBMRanker),
> programmatic doorway defense, crawl-budget shaping, Navboost engineering,
> GEO citation capture, and link acquisition unit economics. It complements —
> never replaces — the first-party telemetry stack (GSC, Clarity, PostHog,
> Cloudflare): internal telemetry diagnoses what ALREADY gets impressions;
> this playbook breaks the survivorship bias for what does not yet.

---

## 1. GSC Striking-Distance Mining (the raw input funnel)

Pages ranking at the bottom of page 1 or top of page 2 generate steady
impressions on secondary queries without earning clicks. This is the fastest
compounding loop in search.

**GSC workflow:** Performance → Search results → enable Average position and
CTR → filter `Position > 7 AND Position < 21` → sort Impressions descending.

**Action pattern:** inspect the URLs receiving those impressions and find
high-impression queries that do not literally appear in the page text. Add a
dedicated `<h2>`/`<h3>` section answering that exact query, then request
re-indexing via URL Inspection. Moving a query from position 11 to position 4
raises impressions and clicks multiplicatively within days of recrawl.

**Snippet overhaul for positions 1–5 with CTR < 3%:**
- Replace generic titles with high-contrast, specificity-driven hooks under 60
  characters (never truncate on mobile). Bracketed value indicators
  (`[Free Tool]`, `[Benchmarks]`, `[Updated 2026]`), concrete numbers, and
  speed/cost differentiators lift CTR without any ranking change.
- Search the query manually in an incognito window. If Google rewrites the
  title or pulls awkward body text, rewrite the opening paragraph and meta
  description (150–160 chars) to answer the core intent with a clear CTA.
- Featured-snippet capture: for queries where a competitor holds position 0,
  add a 40–50-word "is-statement" definition or a clean comparison table
  directly beneath a matching question header near the top of the page.

**Internal link equity injection:** GSC → Links → Internal links → find pages
with fewer than 5 incoming internal links. Place contextual links from the
highest-traffic, highest-authority URLs using exact/partial-match descriptive
anchors. This passes immediate equity and triggers faster recrawls.

---

## 2. DataForSEO Unit Economics & Cost Routing (mandatory)

DataForSEO is pay-as-you-go (~$0.0006/SERP) — no $120–400/mo UI subscription,
no aggressive API throttling. But its pricing has multipliers; the skill MUST
route around them:

| Lever | Wrong (expensive) | Right (cheap) |
| --- | --- | --- |
| Batch keyword SERPs | Live endpoint, $2.00/1k SERPs | Standard Queue (`task_post` → `tasks_ready` → `task_get`), $0.60/1k, ~5-min turnaround |
| Search operators | `site:`/`inurl:`/`intitle:` in the query — 5x billing multiplier | Plain Top 10 (`depth: 10`), regex/string filtering locally |
| AI Overview / PAA | `load_async_ai_overview` flag (+$0.002/req) | Parse `ai_overview` / `people_also_ask` from the base Advanced payload |
| Rank tracking | `depth: 100` full crawl every run | `stop_crawl_on_match: ["example.com", "*.example.com"]` — stops at your URL, refunds unused depth |
| Deep-position audits | Paying for page 1 when the URL sits at position 34 | `search_param: "&start=30"`, `depth: 10` — page 4 only |
| Model features | Paid backlink-metric APIs | SHAP-prune (`pred_contrib=True`) — free GSC features + cheap SERP title-match ratios usually explain >95% of variance |

**Client:** `scripts/dataforseo_client.py` (stdlib-only, offline-testable,
credentials from env — never hardcoded). `--dry-run` prints the exact task
payloads and the estimated cost before any network call.

---

## 3. SERP Vulnerability Scoring (weak-spot detection)

For every candidate query, compute (implemented in `dataforseo_client.serp_vulnerability_score`):

- `forum_ugc_count` — `discussions_and_forums` blocks + Reddit/Quora/StackExchange/Medium URLs in the results.
- `title_exact_match_rate` — fraction of Top-5 organic titles containing all query tokens. Rate < 0.4 with volume > 100/mo = underserved long-tail gap.
- `crowding_penalty` — AI Overview / local pack / shopping blocks pushing organic position 1 below the fold (~900px). Crowded SERPs yield far lower CTR even at position 1.

**Weak spot** = score ≥ 70: high volume, forums ranking in the Top 5, nobody
exact-matching the title. Attack those first — they need zero backlinks.

**Demote** queries where entrenched DR 90+ domains exact-match the title in
all Top-5 slots, regardless of how good the internal metrics look.

---

## 4. Predictive Pre-Launch Ranking (LGBMRanker lambdarank)

Standard keyword-difficulty scores ignore topical authority and intent fit.
Train a ranker on your own GSC + DataForSEO history to predict Expected
Clicks per 30 Days BEFORE writing or generating a page.

- **Target (y):** lambdarank needs integer relevance grades — bucket historical
  30-day clicks per URL logarithmically: `0: 0 clicks, 1: 1–10, 2: 11–50,
  3: 51–250, 4: >250`, with `label_gain=[0, 1, 3, 7, 15]`.
- **Grouping:** group candidate keywords by parent semantic cluster (or parent
  programmatic template) so lambdarank learns which modifier variations
  outperform within the same vertical.
- **High-alpha features:**
  - `topical_centroid_similarity` — cosine similarity between the candidate
    keyword embedding and the click-weighted centroid of the domain's top ~50
    GSC queries (site-level authority classifiers boost queries near the centroid).
  - `serp_vulnerability_score` — Section 3.
  - `title_exact_match_rate` — < 0.4 + volume signals an unoptimized SERP.
  - `internal_link_centrality` — PageRank of the parent hub that will link to the route.
  - `serp_pixel_crowding` — flags for `ai_overview`, `shopping`, `local_pack`.

```python
import lightgbm as lgb

ranker = lgb.LGBMRanker(
    objective="lambdarank",
    metric="ndcg",
    ndcg_eval_at=[3, 5, 10],
    label_gain=[0, 1, 3, 7, 15],
    lambdarank_truncation_level=10,
    lambdarank_norm=True,   # stops large clusters dominating gradients
    num_leaves=31,
    learning_rate=0.05,
    n_estimators=300,
    min_child_samples=20,
)
# X sorted by cluster; group = row counts per cluster
ranker.fit(X_train, y_train, group=train_cluster_counts,
           eval_set=[(X_val, y_val)], eval_group=[val_cluster_counts],
           callbacks=[lgb.early_stopping(30)])
```

**Deployment rule:** rank the backlog (e.g. 50k programmatic candidates) and
publish ONLY the top 5–15% of pairs first. Release the next tier after the
early cohorts earn impressions and clicks in GSC. This protects crawl budget
from thin-content dampening. After training, extract SHAP contributions
(`ranker.predict(X_val, pred_contrib=True)`) and drop paid features that
contribute < 5% of variance.

---

## 5. Programmatic Doorway Defense (the crawl-and-drop classifier)

When thousands of near-identical pSEO routes launch (`/convert/{a}-to-{b}`,
`/compare/{a}-vs-{b}`), Google's Helpful Content / Doorway classifiers compute
shingle-level structural similarity across the cohort. Symptom: impressions
spike for ~2 weeks, then collapse to zero ("crawl-and-drop"). Site-wide trust
losses from scaled content are evaluated at the domain/directory level —
flipping pages to `noindex` afterwards usually does NOT restore the money
pages. Prevention is the only cure:

1. **Uniqueness ratio pre-flight gate (hard block):**
   $$\text{uniqueness\_ratio} = \frac{\text{unique data fields populated}}{\text{total template data fields}} \ge 0.50$$
   Require 8–10 distinct numerical/categorical data points per URL from 3+
   distinct sources. Rows with too many NULLs must 404 or merge into a parent
   category — never render.
2. **Dynamic DOM branching:** conditionalize template components on data
   deltas. If `item_a` vs `item_b` differ > 50% in price/specs/architecture,
   render different sub-components, callouts, or benchmark charts. Sibling
   routes must share < 70% identical text shingles (MinHash/Jaccard check in
   CI) or be held from the sitemap.
3. **Pairwise matrix pruning:** never launch the full N×N Cartesian product.
   Use DataForSEO volume + LGBMRanker scores to publish the top decile first.
4. **Information gain injection:** render 3–5 hard numerical metrics per
   entity (latency benchmarks, historical median prices, specs) in HTML
   `<table>`/`<dl>` structures — extraction pipelines weight unique tabular
   numbers far above generated prose.
5. **Subdomain sandbox:** launch unproven 10k+ page templates on an isolated
   subdomain or separate domain; migrate only cohorts with > 70% indexation
   and healthy engagement into the main domain after 30 days.

---

## 6. Crawl Budget & Indexing Velocity

Impressions cannot grow while new routes sit in "Discovered – currently not indexed":

1. **Sharded priority sitemaps:** `sitemap-hubs.xml`, `sitemap-tier1.xml`,
   `sitemap-longtail.xml` (1,000–2,500 URLs each) so the GSC Sitemaps report
   isolates which cohort has indexing friction.
2. **Rotating boost slots:** store the current 15–20 striking-distance URLs
   (positions 7–15, high conversion value) in edge KV/D1; inject a semantic
   `<nav aria-label="Popular Comparisons">` block into the top ~20%
   most-crawled pages. When a URL reaches position 1–3 in the weekly GSC sync,
   evict it and rotate in the next contender.
3. **`lastmod` discipline:** advance `<lastmod>` only when the primary content
   payload actually changed — spoofed freshness teaches Googlebot to deprioritize sitemap polling.
4. **Dual-protocol index pings:** fire IndexNow on publish (Bing/Yandex/Naver —
   and ChatGPT Search, Perplexity, Copilot lean on Bing's index) while
   Googlebot is still queueing; use the Google URL Inspection quota for the
   highest-value URLs only.
5. **Cloudflare bot-to-impression reconciliation:** join Cloudflare Googlebot
   crawl timestamps per URL against GSC first-impression dates. Any cohort
   crawled 5+ times with zero impressions after 14 days gets a content/intent
   rewrite or is pruned from the primary sitemap.

---

## 7. Navboost Engineering (the 13-month click-log multiplier)

Navboost tracks long clicks (dwell) vs short clicks (pogo-sticking) per query
for ~13 months and re-ranks with it.

1. **Win the first 300px:** for tool/data queries, put the interactive element
   or the exact numerical answer in the top 300px with zero hero fluff. Users
   who use a calculator/converter/table within 4 seconds never return to the
   SERP (last-click), which unsticks pages stalled at position 6–9.
2. **Navigational brand velocity:** Navboost rewards queries where users
   search `[keyword] + [brand]` and scroll past positions 1–4 to click you.
   Route newsletter/social/community pushes as brand-search prompts (search
   the exact brand + tool name) rather than always deep-linking. 30–50
   genuine navigational click-throughs on a mid-volume keyword can
   permanently unstick a page.

---

## 8. GEO: Zero-Click AI Overview Capture

When an AI Overview owns the top of the SERP, organic position 1 behaves like
the old position 6. Be cited inside it:

1. **Quote-ready stats pattern:** LLM synthesis extracts sentences pairing
   entity + date + hard number ("Across 14,200 listings in Q4 2026, median
   margin fell 11.4%"). Place a 2-sentence "Key Findings" box with hard
   numbers directly below the `<h1>`.
2. **Merchant/software feed injection:** structured feeds (Google Merchant
   Center free listings) and `Product`/`SoftwareApplication` JSON-LD with
   explicit `offers` + `aggregateRating` surface URLs inside AI Overview
   commercial carousels with materially higher CTR than text citations.

---

## 9. Link Acquisition Unit Economics (and why classic PBNs die)

**Classic PBNs have negative EV:** auctioned expired domains + AI articles +
links to money sites are trivially devalued by Google's SpamBrain graph
analysis (WHOIS/registrar flips, nameserver clusters, outbound velocity,
topical resets). The usual outcome is silent weight nullification, not a
manual penalty — $2,000+ in dead domain and hosting spend.

**What replaces them:**

1. **Buy indexed traffic on the exact URL, never DR/DA.** Pay for link
   insertions (niche edits) into existing articles that already rank Top 20
   and receive verifiable organic search traffic. If Google trusts that URL
   enough to send it visitors, the link passes immediate authority. Never buy
   placements on brand-new orphan pages, regardless of the site's DR.
2. **Outbound-to-inbound filter:** reject any domain linking out to more
   unique domains than link into it, or with a public indexed "Write for Us"
   page (link-farm signatures).
3. **Anchor safety:** no exact-match commercial anchors ("best file
   converter"). Use ~70% branded/URL anchors, ~20% generic natural-flow, ~10%
   partial-match topical.
4. **Micro-SaaS & free-tool satellites instead of fake blogs:** tiny utility
   sites, calculators, or open-source doc hubs on clean domains that rank for
   their own long-tail queries. One link from a site with 500 real monthly
   organic clicks beats 50 dead PBN domains.
5. **Expired-domain restoration (the surviving play):** buy an expired domain
   in the exact sub-niche, restore its top historical pages from the Wayback
   Machine until they regain real GSC impressions, THEN place a single
   contextual link — or 301 the high-authority historical URLs to equivalent
   tools on the main site.
6. **Launch & directory velocity ($0 foundational layer):** Product Hunt,
   Hacker News, GitHub Awesome lists, AlternativeTo, curated vertical
   directories — enough clean DR 30–40 equity for internal linking and
   programmatic content to do the heavy lifting.

---

## 10. Fusion Contract with the Telemetry Stack

Every action from this playbook joins back to first-party evidence before
execution (Invariant 11):

| This playbook emits | Joined against | Before |
| --- | --- | --- |
| Weak-spot keyword + SERP score | GSC joint page+query rows | Any title/content change |
| LGBMRanker expected clicks | PostHog/GA4 conversion value per cluster | Any new pSEO route build |
| Doorway-gate failures | Cloudflare crawl logs + GSC index coverage | Any sitemap submission |
| Boost-slot rotations | Clarity scroll/rage data on the host pages | Any internal-link placement |
| Link prospect list | Cloudflare referral logs + PostHog sessions | Any paid placement |
