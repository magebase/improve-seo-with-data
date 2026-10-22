# Generative Engine Optimization (GEO) & AI Search Playbook

As search transforms from 10 blue links to synthesized answers in **Perplexity**, **ChatGPT Search**, **Claude**, and **Google AI Overviews**, optimizing for generative engines requires distinct architectural patterns.

---

## The 4 Pillars of GEO

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Machine-Readable Documentation: /llms.txt                │
├─────────────────────────────────────────────────────────────┤
│ 2. Structured Authority: Schema.org JSON-LD                 │
├─────────────────────────────────────────────────────────────┤
│ 3. Unblocked AI Crawlers: robots.txt User-Agent Policies   │
├─────────────────────────────────────────────────────────────┤
│ 4. Direct Q&A Information Architecture: H2 / Answer Blocks │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Deploying `/llms.txt` and `/llms-full.txt`

AI models utilize `llms.txt` as a concise, structured index to understand a site's purpose, public APIs, programmatic hubs, and documentation without crawling gigabytes of raw HTML.

- Place `llms.txt` in the web root (`https://example.com/llms.txt`).
- Follow the official specification:
  - Markdown H1 with site name and primary value proposition.
  - Blockquote containing a 1-2 sentence executive overview.
  - Markdown lists linking to key landing pages, guides, tools, and API references.
  - Explicit links to [`/llms-full.txt`](../templates/llms.txt) for complete raw documentation.

---

## 2. Robots.txt Policies for AI Search Bots

Never accidentally block generative search bots unless you explicitly intend to opt out of AI discovery.

```txt
# Permit primary AI answer crawlers
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

# Prevent crawl-budget waste on internal facets
Disallow: /*?*
Disallow: /admin/
Disallow: /api/private/
```

---

## 3. Schema.org JSON-LD Structured Data

LLMs ingest structured data to confirm entity names, product features, prices, and software capabilities.

### Homepage Essentials:
- `Organization`: Brand name, URL, logo, contact points, sameAs social links.
- `WebSite`: Name, URL, PotentialAction (SearchAction with query-input).

### SaaS & Tool Landing Pages:
- `SoftwareApplication`: Name, operatingSystem, applicationCategory, offers (price, currency, availability).
- `FAQPage`: Explicit question-and-answer pairs matching long-tail search intent.
- `BreadcrumbList`: Clear category taxonomy.

---

## 4. Synthesizable Content Design (Answer Engine Snippets)

Generative engines extract 2-4 sentence answers directly beneath subheadings.

- **Direct Inversion Structure:** Start every H2 section with the direct answer or definition in the first 2 sentences before expanding into background details.
- **Comparison Matrices:** Use clean HTML tables (`<table>`) with clear column headers (`Feature`, `Standard`, `Pro`). LLMs ingest HTML tables with higher citation fidelity than unstructured paragraphs.
- **Interactive Calculators:** When building programmatic utilities (e.g. ROI calculators, converters), provide pre-computed benchmark examples in the static HTML for immediate LLM extraction.
