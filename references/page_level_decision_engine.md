# Page-Level Decision Engine: Turning SEO Data into Concrete Website Changes

> **The Core Rule:** When an agent is instructed to use the skill to improve a website or domain, its primary mission is governed by the **SEO Outcome Maximization Contract**: translate every meaningful pattern in GSC, GA4, PostHog, Clarity, and technical telemetry into one of **six mutually exclusive page-level actions** across **two parallel execution tracks**:
> 1. **Improve an existing page** *(Track 1)*
> 2. **Create a new page** *(Track 2)*
> 3. **Improve a shared template** *(Track 1)*
> 4. **Build a new template** *(Track 2)*
> 5. **Consolidate overlapping pages** *(Track 1)*
> 6. **Make no change**

---

## 1. The Decision Matrix

| What the Data Tells You | What to Change (The Action) | What NOT to Do |
| :--- | :--- | :--- |
| A page ranks for relevant queries around positions 5–20. | **Improve the existing page's** usefulness, intent coverage, internal links, and result presentation. | Automatically create another page for the same topic. |
| High impressions but low CTR versus comparable results. | **Investigate and test the title**, page messaging, and snippet relevance on the existing page. | Change titles based only on a sitewide CTR benchmark. |
| A cluster of related queries is growing and existing page already addresses intent. | **Add useful sections, examples, comparisons, or an interactive tool** to the existing URL. | Split every keyword variation into a separate URL. |
| A valuable query cluster has a distinct intent and no suitable landing page. | **Create a new, purpose-built page** passing the 7-factor quality gate and URL ownership check. | Create a thin page that merely rephrases an existing one. |
| Hundreds of pages share the same structural or component problem. | **Improve the shared template**, after testing the change on a matched cohort. | Manually patch hundreds of URLs one at a time. |
| Several URLs target essentially the same search intent. | **Differentiate their purpose or consolidate** overlapping content via canonical/301. | Redirect pages just because their impressions are low. |
| Visitors click but rarely convert (high traffic, weak conversions). | **Improve the landing experience, offer, or funnel** (CTA, mobile layout, inputs). | Publish more informational articles to solve a conversion problem. |
| Pages are inaccessible, incorrectly canonicalized, or failing to render. | **Fix the underlying delivery, rendering, or technical defect**. | Keep generating pages that have the same technical blocker. |
| A page has no meaningful demand, unique value, or business purpose. | **Reassess its role; improve, consolidate, retire, or leave it alone**. | Keep expanding the site merely to increase URL count. |

---

## 2. The Existing-Page Improvement Workflow

For each important URL, generate a page brief from its GSC query history and landing-page performance. Check and edit these 6 areas in strict priority order:

```
[ Step 1: Title & Search Messaging ] ──▶ Align title, visible H1, and meta description within display-width limits.
                │
[ Step 2: The First Screen of Content ] ──▶ Immediate clarity above the fold; answer the user's task.
                │
[ Step 3: Missing Topic Coverage ] ──▶ Ingest actual GSC query variations for unanswered edge cases.
                │
[ Step 4: Original Value & Utility ] ──▶ Calculators, verified data, comparison tables.
                │
[ Step 5: Internal Link Architecture ] ──▶ Crawlable links from category hubs with natural anchor text.
                │
[ Step 6: Conversion UX & Funnel ] ──▶ Fix Clarity rage clicks & PostHog dropoffs.
```

### Specific Edits in Detail:
1. **Title & Search-Result Messaging:**
   - Does the title accurately communicate what the page offers?
   - Align visible `<h1>` with `<title>` so Google doesn't rewrite snippet headers.
   - Use accurate intent modifiers (`Free`, `Online`, `Calculator`, `Instant`, Current Year).
   - Evaluate against SERP display width: desktop ~580px, mobile ~480px. Never treat character limits as pass/fail SEO quality gates.
   - *Note on Structured Data:* Do **NOT** add `FAQPage` markup expecting FAQ rich-result space in Google Search; Google removed the FAQ rich-result feature. Use `SoftwareApplication`, `Product`, `WebSite` SearchAction, and `BreadcrumbList`. Visible FAQ accordions remain valuable for answering on-page user intent.
2. **The First Screen of Content (Above the Fold):**
   - Can the visitor immediately understand what the tool/page does, who it is for, and how to get the answer?
   - Place primary interactive inputs or the core answer where it helps the visitor immediately, without forced narrative filler.
3. **Missing Topic Coverage:**
   - Use GSC's actual query variations to identify unanswered questions or missing parameters.
   - Add a section to the current page when queries represent the same overall user task.
4. **Original Value & Interactive Utility:**
   - Add something competing pages lack: interactive calculator, tested edge-case data, comparison table, or verified benchmarks.
   - Rewriting existing web content without original utility violates Google Helpful Content criteria.
5. **Internal Links:**
   - Find relevant category hubs and parent pages that should point to the destination.
   - Use crawlable standard HTML links (`<a href="...">`) with concise, natural anchor text.
6. **Conversion Experience:**
   - Use GA4 to locate low-conversion organic landing pages.
   - Use PostHog to pinpoint the funnel step where users abandon.
   - Use Microsoft Clarity to inspect rage clicks (unresponsive buttons) and dead clicks (misleading non-interactive elements).

---

## 3. The New-Page Decision Process & 7-Factor Quality Gate

> [!IMPORTANT]
> **Do not use a query as the unit of page creation.** Use a **distinct search intent and user task** as the unit.

A new page is justified **ONLY** when there is meaningful demand, no existing page that satisfies the intent, and the proposed page passes all 7 quality factors:

| Quality Factor | Mandatory Evaluation Question |
| :--- | :--- |
| **1. Demand** | Is there evidence of relevant search demand in GSC or keyword research? |
| **2. Intent Gap** | Does the current site lack a page that properly fulfills this specific user task? |
| **3. Business Value** | Is this audience likely to take a meaningful next action (conversion, signup, lead)? |
| **4. Unique Value** | What original information, proprietary data, or interactive calculation does this page add? |
| **5. Differentiation** | Is this a genuinely different destination from existing URLs (no content cannibalization)? |
| **6. Cost & Maintenance**| Can the page be created, validated, and maintained economically when data changes? |
| **7. Risk & Quality** | Will this avoid creating thin, duplicated, or doorway content? |

---

## 4. The 5 Standard Template Archetypes

Templates multiply quality or replicate defects across thousands of URLs. Create a new template only when there is a genuinely different functional experience to deliver:

1. **Editorial / Guide Template (Informational Intent):**
   - Clear primary answer, structured subheadings, original examples, source citations, author attribution, and contextual internal links.
   - *Trigger:* Informational queries expanding around a conceptual topic.
2. **Comparison Template ("A vs B" & "Best Alternative" Intent):**
   - Consistent evaluation criteria, verified feature differences, limitations, suitable use cases, and decision comparison matrix.
   - *Trigger:* Comparison and alternative queries where current pages only provide one-sided informational prose.
3. **Tool / Calculator Template (Functional Calculation Intent):**
   - Working deterministic calculation engine, reactive inputs, instant output cards, edge-case validation, and accessible mobile controls.
   - *Trigger:* Clear functional intent (`calculator`, `converter`, `estimator`, `simulator`) that prose alone fails to satisfy.
4. **Directory / Category Template (Discovery & Browsing Intent):**
   - Logical categorization, meaningful differences between listed items, relevant filter dimensions, and crawlable links to detail pages. Zero empty filter combinations.
   - *Trigger:* Broad navigational and exploration queries.
5. **Localized / Market-Specific Template (Geographic & Regional Intent):**
   - Verified market-specific pricing, local currencies, regional compliance, service area boundaries, or native language translation.
   - *Trigger:* Genuine regional variation; never generate near-identical city pages with only place names swapped.

---

## 5. The 8-State Page-Level Diagnostic Decision Tree

Before choosing code or content edits, classify the diagnosed search state for the target URL or query cluster:

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

## 6. The 7 Standard Typed Action Contracts

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

---

## 7. The URL Ownership Model (`query_cluster -> intended_url -> actual_ranking_urls`)

Never allow keyword-to-page generation without verifying existing ranking ownership:

1. **Which existing URLs already receive impressions for the query cluster?**
2. **Which URL has the best matching search intent?**
3. **Are several URLs competing for similar queries?**
4. **Is a new page actually necessary, or would an existing-page improvement be better?**
5. **Which internal links should connect the relevant pages?**

> [!CRITICAL]
> **The Anti-Cannibalization Rule:**
> If an existing non-hub URL already ranks at position $\le 15.0$ or receives the majority of impressions for a query cluster, **NEVER create a new competing page**. The correct action is to improve that URL (Recipe A), add a complementary sub-topic, or strengthen internal links. Creating a second page splits domain authority and destroys search rank.

---

## 8. The 4 Core Operational Recipes

### Recipe A — Improve Rankings for Existing Pages (Positions 4–20)
*Target: Relevant non-branded queries where the page already has impressions, especially positions 4–20.*
1. Extract top query clusters from the longest useful GSC window.
2. Inspect live search results: what format does Google favor (tools, calculators, directories, guides)?
3. Identify missing information, computational logic, or verified benchmarks.
4. Add crawlable internal links from high-authority category hubs.
5. Deploy the minimal code/content edit that directly closes the diagnosed gap.
6. Record baseline metrics and content version identifier.

### Recipe B — Improve CTR Without Sacrificing Relevance
*Target: Pages where query demand produces impressions but CTR is below position/device benchmark.*
1. Segment query impressions by device (`DESKTOP` vs `MOBILE`), country, and position.
2. Inspect the searcher's exact expectation and what genuine advantage the page provides.
3. Test title display width (~580px desktop, ~480px mobile) to prevent awkward SERP truncation.
4. Ensure visible `<title>`, `<h1>`, and `<meta name="description">` make consistent promises.
5. Evaluate over 28-day Difference-in-Differences against matched URL cohort.

### Recipe C — Recover Pages That Are Not Gaining Impressions
*Target: Published pages that have zero or negligible search visibility.*
1. Classify the page in the indexing funnel: Not Discovered vs. Crawled Not Indexed vs. Duplicate Canonical vs. No Demand.
2. A canonical defect requires a technical fix; low value requires original utility; isolated pages require internal links.
3. Do not blindly submit every URL for indexing; verify technical eligibility first.

### Recipe D — Scale Content That Has Demonstrated Value
*Target: Page families where live evidence proves the template earns search clicks and conversions.*
1. Track page-family health: % of published URLs indexed, % receiving impressions, % generating clicks.
2. If a page family succeeds, expand it using the same validated mechanisms and verified source data.
3. If a page family underperforms, diagnose the systemic template flaw before generating more pages.

---

## 9. Content Evidence System & Factual Safeguards

Every programmatic or generated page must be backed by a structured evidence payload:
- **Verified Primary Sources:** Official ITU standards, API specifications, carrier documentation, or regulatory filings.
- **Telecom & Domain Accuracy:** Distinguish telecom carriers (e.g., Safaricom, AT&T) from mobile payment services (e.g., M-PESA).
- **Competitor Claim Verification:** Require source-backed verification for competitor pricing, API limits, and features.
- **Operational Reality:** On SMS/telecom pages, display real carrier health, live routing statuses, and tested latency rather than static marketing copy.

---

## 10. The Production Indexing Funnel

Do not count the mere generation of URLs as an SEO outcome. Track every page through the complete search production funnel:

$$\text{Published} \longrightarrow \text{Discovered \& Crawled} \longrightarrow \text{Eligible \& Indexed} \longrightarrow \text{Receiving Impressions} \longrightarrow \text{Generating Clicks \& Conversions}$$

- **Published:** Valid HTML, canonical tag present, indexable HTTP 200 response.
- **Discovered & Crawled:** Present in XML sitemap and linked contextually from category hubs.
- **Eligible & Indexed:** Verified via GSC Inspection API or sitemap indexing reports; zero canonical conflicts.
- **Receiving Impressions:** Search demand captured across relevant query clusters.
- **Generating Clicks & Conversions:** Qualified search traffic taking meaningful business actions.

> [!NOTE]
> **Engineering Regression Tests vs. Real SEO Growth:**
> Passing 300 unit tests or 80 BDD scenarios is essential engineering evidence that code is safe and regressions did not occur. It is **NOT** evidence of search ranking growth. Real SEO growth is measured exclusively by post-deployment search clicks, impressions, CTR, position, and business conversions.

---

## 11. Title SERP Display-Width Heuristics

Google determines title truncation based on available pixel width in SERP rendering containers, not raw character counts:
- **Desktop SERP Container:** Approximately **580 pixels**.
- **Mobile SERP Container:** Approximately **480 pixels**.

Keep character counts (50–65 characters) as a rough heuristic, but verify actual display width using proportional character approximations (narrow characters like `i, l, |` take ~4.5px, while wide characters like `m, w, M, W` take ~11.5px). Ensure the primary keyword and intent modifier appear within the first 480 pixels.

---

## 12. Sitemap `lastmod` Timestamp Integrity

Google guidelines explicitly mandate that `<lastmod>` timestamps in XML sitemaps must reflect **substantive content or functional updates**, not routine cron job sweeps or automated deployment builds:
- Advance `<lastmod>` ONLY when page content, calculation logic, pricing data, or metadata has genuinely changed.
- Do NOT advance `<lastmod>` on routine automated sitemap generation passes.
- Regularly verify that all URLs in sitemaps return HTTP 200, match their own canonical tags, and are indexable.
