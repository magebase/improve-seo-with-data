# Search Console Optimization Runbook

This runbook defines standard operational procedures for turning Search Console data into measurable ranking and traffic gains.

---

## 1. Striking Distance Optimization (Positions 11 to 20)

### Criteria:
- Average position between `10.1` and `20.0`.
- Impressions $\ge 50$ over the last 28 days.
- Page intent matches the query.

### Remediation Workflow:
1. **Target Subheading Injection:** Add an `<h2>` or `<h3>` containing the exact search phrase.
   - Example Query: `virtual phone number for sms verification`
   - Added Subheading: `How to Use a Virtual Phone Number for Instant SMS Verification`
2. **Contextual Internal Linking:** Search your existing site content for topically related articles. Add an internal link pointing to the striking distance URL with exact or partial-match anchor text.
3. **Intent Coverage Expansion:** Check the "People Also Ask" or related queries for the term. Add a 150-word targeted answer block addressing the specific question.

---

## 2. Low-CTR Quick Wins (Positions 1 to 7)

### Criteria:
- Average position between `1.0` and `7.0`.
- Impressions $\ge 100$.
- Actual CTR is $<50\%$ of standard position benchmark:
  - Pos 1 Benchmark: $20\%$
  - Pos 2 Benchmark: $10\%$
  - Pos 3 Benchmark: $6\%$
  - Pos 4 Benchmark: $4\%$
  - Pos 5 Benchmark: $3\%$

### Remediation Workflow:
1. **Title Tag Hook Overhaul:**
   - Add compelling numbers or modifiers: `[Updated 2026]`, `Free`, `Top 10`, `Step-by-Step`.
   - Ensure the primary target keyword is within the first 40 characters.
   - Keep total title length between 50 and 60 characters to avoid SERP truncation.
2. **Meta Description CTA:**
   - Include a clear call to action: `Calculate in 30 seconds`, `Try free with zero signup`, `Compare live pricing`.
   - Keep description length between 135 and 155 characters.
3. **Rich Snippets (FAQPage):** Add 2-3 FAQ questions in Schema.org JSON-LD to claim additional vertical height in search results.

---

## 3. Resolving Query Cannibalization

### Criteria:
- A single search query generates clicks or impressions across 2 or more distinct URLs.
- Neither URL ranks in the top 3 positions due to split page authority.

### Resolution Options:
1. **Consolidation (Recommended):** If one page is clearly superior, 301-redirect the secondary page to the primary authority page and merge valuable content.
2. **Canonical Pointing:** If both pages must exist for separate user flows, set `<link rel="canonical" href="https://example.com/primary-page/">` on the secondary page.
3. **Intent Differentiation:** If the pages serve different audiences (e.g. `Developer API` vs `Non-technical Web App`), re-title and re-focus the secondary page away from the primary query.

---

## 4. Decaying Content Refresh

### Criteria:
- 90-day clicks or impressions dropped $>20\%$ compared to previous 90-day window.

### Remediation Workflow:
1. Identify lost queries using the `decaying-pages` report.
2. Update outdated timestamps, code snippets, or API syntax.
3. Remove or replace broken outbound links.
4. Add a `Last updated: [Month Year]` notice in the article header to signal freshness to search engines.
