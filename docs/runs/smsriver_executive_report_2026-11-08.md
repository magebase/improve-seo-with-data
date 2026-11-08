# SEO & Conversion Executive Report: smsriver.com

**Generated:** 2026-11-08 (UTC) · **Windows:** GSC 28-day (2026-10-12 → 2026-11-08), Cloudflare 7-day (Nov 1–7)
**Data provenance:** GSC REST (449 rows, joint query×page), Cloudflare GraphQL zone analytics (REAL), DataForSEO Standard Queue (179/200 SERP-enriched), live crawl + Playwright field measurement. Clarity/PostHog legs NOT connected (no API token) — excluded from all conclusions.

---

## 1. Trajectory (REAL edge data)

| Date | Requests | Page Views |
| :--- | ---: | ---: |
| Nov 2 | 10,414 | 4,481 |
| Nov 5 | 17,338 | 7,473 |
| Nov 7 | **34,924** | **13,734** |

Requests grew **3.4× in 6 days**; Nov 7 was the biggest day since GSC data begins (2026-10-12). GSC demand: 1,138 impressions / 32 clicks per 28-day window, 16–24 imps/day.

## 2. Edge reliability (Plane C, Nov 7, 25,979 sampled)

| Signal | Share | Verdict |
| :--- | ---: | :--- |
| 429 rate-limited | 42.6% | Inbox scraper wall — defense working (targets: `/inbox/<digits>/` GET harvesters) |
| 200 (cache HIT) | 29.5% | Edge caching effective on hot paths |
| 204 (HTMX polls) | 21.2% | Live-feed polling traffic |
| **504 (served STALE)** | **3.8%** | Origin timeouts, diffuse across inbox/receiver DB reads; stale-while-revalidate masked user impact. **Action: monitor after D1 hot-path review — no single hot path to fix (sampled paths: /inbox/*, /receive-sms/* country reads, /compare/).** |
| 403 bot filter | ~1% | Expected |

Token limitation: per-path TTFB/CWV fields require higher authz — Plane C limited to status/cache/traffic. No fabricated metrics.

## 3. Ranking loop state (Workflow 7, waves 20 → 20f)

- **Model:** LightGBM `rank_xendcg`, 24 trees, monotonic constraints, cluster-integrity split, heuristic residual init; pooled fleet history 1,498 rows / 26 clicked → `serp_bootstrap` label mode (flips at 50).
- **Backlog:** 200/200 candidates feature-complete; full-backlog rescore converged — exploit tier identical to executed waves.
- **Executed experiments (all deployed + field-verified 2026-11-08):**
  1. Homepage "Receive SMS Live" H2 + SMSBro comparisons (slots 2–4, 7–10)
  2. Receiver how-to H2 + MCC-MNC homepage card (slots 6, explore)
  3. Receiver free-cluster section + FAQ depth, 24 pages (template archetype)
  4. Verify-detail per-service FAQ + FAQPage, all services (slot 12/40 cluster)
  5. **GB receiver retitle → "Receive SMS UK" cluster head** ('receive sms' 83 imps pos 30.7, ~35 variants)
  6. **Receiver fold reorder** — 298 number cards above fold (y=376 vs 929 viewport)
  7. **Homepage live feed promoted** above fleet grid per DESIGN.md canonical order (was y=2736)
  8. **Digit-search 301 retargeted** `/inbox/` (noindexed) → `/number/` (indexable) — equity consolidation
- **Deterministic cross-validation (Workflow 1):** 14/14 actions reconciled — 13 mapped to executed work, 1 caught the 301 defect above.

## 4. Verification passes (Invariant 10)

GEO 100/100 · technical audit 0 high-severity · IndexNow runtime ping live (BDD 3/3) + fleet sweep implemented, 559 fleet URLs batched (smsriver 9).

## 5. Stage-4 outcome ledger (measure on ~2026-12-06 via `log_outcomes_and_retrain.py --executed data/action_queue_2026-11.json`)

| Experiment | Baseline (2026-11-08) | Success signal |
| :--- | :--- | :--- |
| GB cluster retitle + fold reorder | 'receive sms' pos 30.7, 0 clicks | pos ≤ 15, first clicks on /receive-sms/gb/ |
| Homepage live-feed promotion | 'receive sms live' pos 11.3 | pos ≤ 8 |
| Verify FAQ schema | 'receive sms paypal' pos 42 | pos ≤ 25 |
| Digit 301 consolidation | digit rows landing on '/' | impressions migrating to /number/ URLs |
| Fleet label flip | 26/50 clicked rows | ≥ 50 → fleet_clicks mode, isotonic calibration |

## 6. Open items (owner-tagged)

1. **Clarity API token** — Workflow 3 blocked; generate in Clarity portal → `CLARITY_API_TOKEN`.
2. **autopublishai.com/sitemap.xml** returns non-XML — its IndexNow discovery is dark (fleet finding).
3. `SEO-INDEXNOW` pulse detector entry is stale — flip to implemented.
4. Foreign-lane test drift (seo_alpha comparisons detector, collector-vault/figiva/file-converter checkpoint symbols) — owning agents.
5. `/uploads/2018/05/241050548788.jpg` 504 — legacy asset on origin, not Worker-served.
