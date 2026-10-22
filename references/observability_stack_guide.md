# The Modern $0 Observability & Telemetry Architecture for SEO

> **Purpose:** Standardize a zero-marginal-cost, high-leverage telemetry, error monitoring, and user session recording fleet to ensure every organic search visit, bot crawl, and conversion is observed with zero blind spots.

---

## 1. The Observability Stack Hierarchy

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Search Engine Indexing & Bot Logs (Server Logs / Cloudflare / GSC) │
├────────────────────────────────────────────────────────────────────────┤
│ 2. Edge & Error Telemetry (Sentry / Better Stack / Cloudflare Logpush) │
├────────────────────────────────────────────────────────────────────────┤
│ 3. Web & Organic Traffic Analytics (Google Analytics 4 / Search Console)│
├────────────────────────────────────────────────────────────────────────┤
│ 4. Session Replay & UX Diagnostics (Microsoft Clarity - 100% Free)     │
├────────────────────────────────────────────────────────────────────────┤
│ 5. Product & Conversion Attribution (PostHog - 1M events/mo Free)       │
├────────────────────────────────────────────────────────────────────────┤
│ 6. Real User Monitoring / Core Web Vitals (web-vitals LCP/INP/CLS)     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Specifications

### 2.1 Microsoft Clarity (Session Replay & Heatmaps)
- **Role:** Understand *why* organic search visitors bounce, where they scroll, and where they encounter dead clicks or rage clicks on programmatic landing pages.
- **Cost:** 100% Free with zero quota caps (unlimited sessions, recordings, heatmaps).
- **Setup:**
  1. Create a project at [clarity.microsoft.com](https://clarity.microsoft.com).
  2. Embed the Clarity tracking script in your root layout/base template.
  3. Filter by **Referrer: Google / Bing / Perplexity** and **Metric: Rage Click Count** to find broken UI components.

### 2.2 Google Analytics 4 (GA4) + GSC Property Link
- **Role:** Connect Search Console query impressions directly to GA4 landing page sessions, engagement rate, and goal conversions.
- **Setup:**
  1. In GA4 Admin > **Product Links** > **Search Console Links**, link your GSC property.
  2. In Reports > Library, publish the **Search Console** collection to unlock the *Queries* and *Google Organic Search Traffic* reports.
  3. Monitor landing page engagement rates: pages with $<40\%$ engagement rate suffer from intent mismatches or poor mobile UX.

### 2.3 PostHog (Organic Attribution & Funnels)
- **Role:** High-value semantic business events (`user_signed_up`, `tool_used`, `calculator_calculated`, `lead_submitted`) with strict initial attribution.
- **Cost:** First 1,000,000 events/month free.
- **Invariant:** Capture `initial_referrer`, `initial_utm_source`, `initial_utm_medium`, and `initial_landing_page` into the user profile on first touch so organic search SEO ROI can be tracked through to paid subscription revenue.

### 2.4 Core Web Vitals Real User Monitoring (RUM)
- **Role:** Google's ranking algorithm penalizes sites with poor real-world Core Web Vitals (Largest Contentful Paint $>2.5s$, Interaction to Next Paint $>200ms$, Cumulative Layout Shift $>0.1$). Lab tests (Lighthouse) only test ideal conditions; RUM catches real mobile user degradation.
- **Setup:** Use `web-vitals` JavaScript library (`templates/telemetry_snippet.html`) to report LCP, INP, and CLS directly to GA4 and PostHog.

### 2.5 IndexNow (Instant Search Engine Notification)
- **Role:** Instantly notify Bing, Yandex, Seznam, and partner AI engines the moment a page is created, updated, or deleted, bypassing crawler latency.
- **Setup:**
  1. Generate an IndexNow key:
     ```bash
     python3 scripts/setup_observability.py --generate-indexnow-key --output-dir ./static/
     ```
  2. Serve `/<key>.txt` containing `<key>`.
  3. When publishing new pages, submit via POST:
     ```bash
     curl -X POST "https://api.indexnow.org/indexnow" \
       -H "Content-Type: application/json; charset=utf-8" \
       -d '{
         "host": "example.com",
         "key": "<your-key>",
         "keyLocation": "https://example.com/<your-key>.txt",
         "urlList": ["https://example.com/new-page/"]
       }'
     ```

### 2.6 Server & Edge Crawler Access Logging
- **Role:** See when `Googlebot`, `GPTBot`, `ClaudeBot`, and `PerplexityBot` visit your URLs, which HTTP status codes they receive, and detect crawl budget waste before it damages indexation.
- **MCP Analysis:**
  Stream access logs directly into the SEO MCP server:
  ```bash
  seo reports run server-log-analysis --params '{"logFile": "/var/log/nginx/access.log"}' --json
  ```
