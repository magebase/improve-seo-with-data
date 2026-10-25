# Page-Level Decision Engine: Turning SEO Data into Concrete Website Changes

> **The Core Rule:** When an agent is instructed to use the skill to improve a website or domain, its primary mission is to translate every meaningful pattern in GSC, GA4, PostHog, Clarity, and technical telemetry into one of **six mutually exclusive page-level actions**:
> 1. **Improve an existing page**
> 2. **Create a new page**
> 3. **Improve a shared template**
> 4. **Build a new template**
> 5. **Consolidate overlapping pages**
> 6. **Make no change**

---

## 1. The Decision Matrix

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

---

## 2. The Existing-Page Improvement Workflow

For each important URL, generate a page brief from its GSC query history and landing-page performance. Check and edit these 6 areas in strict priority order:

```
[ Step 1: Title & Search Messaging ] ──▶ Align title, visible H1, and meta description.
                │
[ Step 2: The First Screen of Content ] ──▶ Immediate clarity above the fold.
                │
[ Step 3: Missing Topic Coverage ] ──▶ Ingest actual GSC query variations.
                │
[ Step 4: Original Value & Utility ] ──▶ Calculators, verified data, comparison tables.
                │
[ Step 5: Internal Link Architecture ] ──▶ Crawlable links from category hubs.
                │
[ Step 6: Conversion UX & Funnel ] ──▶ Fix Clarity rage clicks & PostHog dropoffs.
```

### Specific Edits in Detail:
1. **Title & Search-Result Messaging:**
   - Does the title accurately communicate what the page offers?
   - Align visible `<h1>` with `<title>` so Google doesn't rewrite snippet headers.
   - Use accurate intent modifiers (`Free`, `Online`, `Calculator`, `Instant`, Current Year).
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

## 5. Shared Template Improvements vs. Page-Specific Edits

Diagnose the root cause scale before writing code:

- **1 URL underperforming:** Investigate that specific page, title, and query intent.
- **A group of URLs for one topic underperforming:** Investigate the topic cluster and information architecture.
- **Many URLs across an entire page type underperforming:** Investigate the **shared template** (component performance, layout shifts, mobile UX).
- **Many different page types deteriorating at once:** Investigate sitewide technical regressions, edge errors, server response times, or core search algorithm updates.

---

## 6. The 5 Mandatory Questions Every Recommendation Must Answer

Every SEO and conversion recommendation and summary action emitted by the system must answer five questions:

1. **Target Scope:** Which specific URL, page cohort, or shared template should change?
2. **Page-Level Action:** Which of the 6 actions is being executed (`improve_existing_page`, `create_new_page`, `improve_shared_template`, `build_new_template`, `consolidate_overlapping_pages`, `no_change`)?
3. **Direct Data Observation & Supporting Evidence:** What exact empirical data observation (telemetry source, metric value, date/period, baseline vs benchmark) triggered this action?
4. **Measurable Target Metric:** What exact measurable outcome should improve (clicks, CTR, conversion rate, position, 5xx rate)?
5. **Scale / Rollback Protocol:** How will you determine whether to scale, revise, or reverse the intervention (e.g., 28-day Difference-in-Differences against holdout cohort)?

> [!IMPORTANT]
> **Summary Action Traceability Mandate:**
> All summary tables, action queue backlogs, and audit reports MUST include a dedicated `Direct Data Observation` column. Every action row must cite its empirical observation directly:
>
> `| Priority | Action ID | Decision | Target URL | Direct Data Observation | Proposed Action | Target Metric |`

---

## 7. Priority Execution Order

Always execute interventions in this strict sequence:

1. **P1 — Technical Blockers First:** Fix 5xx errors, broken canonical tags, robots blockages, and failing Core Web Vitals that prevent crawlability and indexing.
2. **P2 — Valuable Existing Pages Second:** Recapture CTR gaps and push striking-distance positions 5–20 to Page 1 on pages with established search visibility.
3. **P3 — Shared Templates Third:** Fix structural, component, and mobile layout defects that lift entire cohorts of URLs simultaneously.
4. **P4 — New Pages & Tools Fourth:** Expand into genuinely missing user intents passing the 7-factor quality gate.
