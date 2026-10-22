# Multi-Dimensional Google Search Console (GSC) Playbook

> **Core Axiom:** Stop treating queries, pages, countries, devices, search appearance, and dates as six isolated reports. Maximum SEO and conversion leverage emerges when you combine and correlate all dimensions together against business outcomes.

---

## 1. The Growth Equation & Levers

Search traffic is not a monolithic metric. It operates as an end-to-end customer acquisition pipeline:

$$\text{Impressions} \longrightarrow \text{Clicks} \longrightarrow \text{Qualified Visits} \longrightarrow \text{Conversions \& Revenue}$$

| Funnel Stage | Core Question | What to Investigate in GSC / GA4 | Growth Levers to Pull |
| :--- | :--- | :--- | :--- |
| **Impressions** | Are we visible for the searches our users make? | Relevant queries with low impression count or low coverage. | Indexation, topical depth, sitemap inclusion, semantic coverage, internal link graph. |
| **Average Position** | How high does Google rank our pages? | High-demand queries where the site ranks in positions 5–20. | Search intent alignment, comprehensive content, original calculation/data utility, page authority. |
| **CTR (Click-Through Rate)** | Do searchers choose our result over competitors? | High impressions with CTR below position/device benchmarks. | Search title tags, meta descriptions, intent modifiers, Schema rich snippet eligibility. |
| **Clicks** | Are we attracting qualified search volume? | Top landing pages capturing majority of organic search visits. | Protect winners, expand related topic clusters, defend against cannibalization. |
| **Conversions** | Do searchers complete valuable business actions? | Organic landing pages with traffic but low GA4 conversion rates. | Landing page intent match, mobile UX, frictionless CTAs, value propositions, pricing clarity. |

> [!IMPORTANT]
> GSC measures **search visibility and clicks**, not conversions. GSC data must be joined with **GA4**, **PostHog**, or backend event pipelines using compatible dimensions (landing page URL, date, country, device) to understand what searchers do after arriving.

---

## 2. Exploiting the 6 GSC Dimensions

### A. Queries: Real Search-Demand Evidence
The Queries report reveals exactly what Google associates with your content.

1. **High Impressions, Low CTR:**
   - Filter to comparable positions, devices, and countries.
   - Inspect the live SERP: are competitors offering interactive tools, current-year guides, or schema stars?
   - Update `<title>` and `<meta name="description">` with actionable intent modifiers (`Free`, `Online`, `Calculator`, `Instant`).
2. **Rising Queries (28-day & 90-day momentum):**
   - Identify terms gaining traction.
   - If an existing page answers the intent, expand it to cover secondary questions. If it represents a new user intent, plan a dedicated landing page.
3. **Unexpected / Unplanned Queries:**
   - Discover adjacent topics where users found your tools through unforeseen phrases.
   - Group them by intent before deciding whether to expand or split.
4. **Query Clustering & Commercial Intent:**
   - Classify queries into **Informational**, **Navigational**, **Comparison**, or **Transactional**.
   - Prioritize commercial clusters that drive signups or purchases over pure top-of-funnel curiosities.

### B. Pages: Identifying Assets & Bottlenecks
Join page URLs with query-level metrics to evaluate individual asset performance:

| Page Pattern | Diagnosis | Recommended Action |
| :--- | :--- | :--- |
| **High Imp, Low CTR** | Search snippet fails to persuade searchers. | Rewrite title tag, add meta description hook, test rich snippets. |
| **High Imp, Pos 5–20** | Established visibility, missing top-page punch. | Deepen topical coverage, inject dedicated H2s, add internal links from authority pages. |
| **High Clicks, High Conversion** | Core business winner. | Protect rankings, monitor daily, build topical satellite pages. |
| **High Clicks, Low Conversion** | Conversion leakage / UX friction. | Audit mobile usability, check PostHog funnels & Clarity replays, simplify CTA. |
| **Declining Impressions** | Demand drop, lost rankings, or technical bug. | Compare query mix across historical periods; inspect indexing and crawl logs. |

#### Cannibalization Detection:
Do not assume two URLs ranking for the same keyword is automatically harmful. Look for recurring patterns where two URLs **alternate in position** or **split clicks** for the same search intent.
- Solution: Designate one canonical authority URL; 301-redirect or re-scope secondary pages to distinct sub-intents.

### C. Countries: Geographic Market Optimization
Analyze geographic demand across impressions, CTR, landing pages, and conversion outcomes:
- **High Impressions, Low CTR in Country X:** Check language match, currency symbols, and localized snippet wording.
- **High Clicks, Low Conversions in Country X:** Offer/pricing mismatch, local payment method absence, or language barrier.
- **High Conversions, Modest Traffic in Country X:** Untapped commercial market; prioritize dedicated localized landing pages or local ccTLD/subdomain routing.

### D. Devices: Desktop vs. Mobile Discrepancies
Always segment queries and pages by `DESKTOP`, `MOBILE`, and `TABLET`:
- Mobile CTR benchmark is typically 10–15% lower than desktop due to smaller viewports and dense SERP features.
- If a page has strong desktop conversions but abysmal mobile conversions, investigate viewport layout, CTA button sizing, input touch ergonomics, and Core Web Vitals (INP/CLS) on real mobile devices.

### E. Search Appearance: Rich Result Opportunities
Monitor how Google presents your search results:
- Track `rich_result` impressions and CTR lifts.
- Validate Schema.org structured data (`SoftwareApplication`, `FAQPage`, `BreadcrumbList`, `Organization`).
- Use Google's Rich Results Test API to ensure snippet eligibility without over-stuffing schemas.

### F. Historical Days: Trend Analysis & Traffic Decomposition
Evaluate performance over multiple analytical horizons:
- **7-day:** Short-term volatility and anomaly detection.
- **28-day vs. Previous 28-day:** Recent operational performance controlling for day-of-week mix.
- **90-day & 16-month:** Structural growth, seasonality, and core algorithm update impacts.

#### Exact Traffic Decomposition Formula:
Clicks equal Impressions multiplied by CTR ($C = I \times R$). Between period 0 and period 1, the total change in clicks decomposes exactly as:

$$\Delta C = (I_1 - I_0) R_0 + I_1 (R_1 - R_0)$$

- **Impression Volume Effect:** $(I_1 - I_0) R_0$ — Clicks gained or lost due to visibility/demand changes.
- **CTR / Engagement Effect:** $I_1 (R_1 - R_0)$ — Clicks gained or lost due to snippet appeal and position changes.

---

## 3. Query-Mix Adjustment: Avoiding Aggregate Fallacies

A common pitfall is observing a sitewide CTR decline and concluding titles are underperforming.
- If your site gains impressions for 500 new generic keywords at position 12, overall CTR will plummet even if your top-3 positions maintained perfect CTR.
- **Fix:** Calculate **mix-adjusted CTR** by holding query position and device weights constant to isolate true snippet performance from query expansion.
