# OpenFileConverter run record — 2026-11-09

## P0 incident: production outage (resolved)

- Symptom: every dynamic route on openfileconverter.com served 503 (Cloudflare 1102,
  worker resource limit); GSC last good contact 2026-11-06.
- Two deploy/rollback cycles with a concurrent agent produced a version-pointer tangle;
  resolved by force-deploying the last verified-good commit (198df49a) via
  scripts/deploy_openfileconverter_worker.py + edge purge. Live version d27fdbbc.
- Smoke 6/6. Homepage warm responses 70-96ms; cold isolates ~2s.
- Root cause (code-adjacent): homepage renders with private/no-store (CSRF form), so the
  Cache API can never absorb it; cold-start render sits at the 1000ms cpu_ms ceiling.
  Intermittent 1102s are load/colo dependent. Convert/studio money pages are edge-cached
  and survived every outage.
- The SEO wave (agent/ofc-seo-growth-gsc: STUDIO_META for 24 studios, /screen/37 and
  /download 301s, guides.py) deployed and REPRODUCED the 1102; reverted. The wave is
  verified green (51 tests) but blocked on mainline reconciliation (37 conflicting files;
  views.py ~3k lines diverged between local main and origin lineage).

## GSC window (property data begins ~2026-09-01)

- 40 (query, page) rows, 69 impressions, 1 click, after 2026-11-07 finalized.
- Only real demand cluster: '274x'/'rs 274x' -> /studio/gerber/ (pos 12.7-17.3, 13 imps).
- /screen/37/ impressions are residual pre-noindex data (internal design-spec surface,
  correctly noindexed); consolidation onto /studio/gerber/ is in progress by design.

## Model inference (rank_xendcg, 24 trees, pooled 1,498-row fleet history)

- Stage 1: 40 candidates, 39/40 with live SERP features (9 fresh DFS fetches, ~$0.005).
- Stage 3 top queue (see data/fleet_queues/action_queue_openfileconverter_2026-11-09.json):
  1. 274x -> /studio/gerber/ REWRITE_SNIPPET_AND_TOP_300PX (score 1.108, SHAP:
     search_volume_log +0.642, current_pos +0.597)
  2. pdf to dox -> /convert/pdf-to-docx/ REWRITE_SNIPPET_AND_TOP_300PX (0.971, pos 22)
  3. open source file converter -> / LAUNCH_PSEO_ROUTE (0.536)
  8. cad model to toolpath comparison -> /compare/step-vs-stl/ (0.363, pos 42)
- Caveat: LAUNCH_PSEO_ROUTE prescriptions on ranks 5-16 target routes that already exist;
  treat as "route has earned no demand yet" (content/links), not build orders.

## Blocked on operator

- Mainline reconciliation (local main ahead 26/behind 59; 37-file merge) ships the wave,
  the homepage CPU hardening, and 5 other lanes in one pass.
- Coordination gap: two agents mutated the worker concurrently; the deployment log was
  the only shared surface. Recommend a claim/lease check before incident mutations.
