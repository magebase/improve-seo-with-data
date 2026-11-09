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

## Redeploy experiment (15:5x, post-rollback) — decisive negative result

Operator re-invoked the skill on openfileconverter.com; treated as authorization to
retry the wave shipping. Re-read of the original evidence showed the "branch reproduces
1102" conclusion rested on ONE observed 503, while known-good also showed a transient
500 once before settling warm. Bounded experiment: redeployed the wave branch head
(agent/ofc-seo-growth-gsc @ 877a1bec) via workflow_dispatch, then measured homepage
cold/warm 10x over ~3 minutes.

Result: NOT a CPU-marginality reproduction. After two cold 503s, the worker settled
into fast consistent 500s (TTFB 80-150ms) on EVERY route including edge-cached money
pages: "500 Worker Initialization Exception ... django apps.populate() died
mid-initialization (apps.loading=True with no populate in flight)". The wave branch's
deployment snapshot is hard-broken; the fail-fast init gate (ported from figiva by the
branch owner, with its own test contract) converts the died-populate state into
permanent hard 500s.

Rollback executed immediately (scripts/deploy_openfileconverter_worker.py from a
detached 198df49a worktree, version 8def3a9f, edge purged). Smoke 6/6, homepage warm
200s at 70-110ms, /studio/gerber/ 200. Production healthy.

Corroborating root-cause evidence found on the branch: its wrangler.toml comment
records the other agent's independent diagnosis of the same 1102 - the KV cache
binding in the request path burns CPU through the Pyodide run_sync bridge (full KV
round trip per cache op; outcome exceededCpu on the homepage). Their mitigation
removes the CF_KV_BINDING_NAME var (cache runs per-isolate). Complementary to my
homepage-no-store diagnosis: BOTH the cold render and KV-per-op CPU burn push the
homepage past the CPU ceiling. Neither lineage's current fix is production-green:
198df49a still intermittently 1102s cold; the branch head hard-500s at populate.

Static checks ruled out new third-party imports (all stdlib in changed app files; no
pyproject/uv.lock diff). The populate-death trigger is inside the branch's new worker
init path (hydrate_worker_env / late-runtime-secrets / cache-init interaction) and
needs the real first-failure traceback - obtainable via `wrangler tail` during a
deliberate branch deploy, which I did NOT do to avoid another outage window.

Status: production stable on 198df49a. Wave remains blocked. Do NOT deploy
agent/ofc-seo-growth-gsc to prod until its populate-death is fixed - the branch owner
is actively iterating on exactly this init contract.

## Evening GSC re-pull (routine, no action triggered)

- OFC: byte-stable at 40 (query,page) rows / 69 imps / 1 click through Nov 7.
  Nov 7 = 37 imps at deep avg pos ~68, 0 clicks (Nov 8 outage day not yet finalized).
  Action queue unchanged; wave prescriptions still blocked.
- smsriver (cross-property pulse): window moved 449->454 rows, 24->25 clicked,
  1138->1151 imps, 32->35 clicks as Nov 7 finalized (25 imps, 3 clicks, avg pos ~5).
  Healthy click profile: brand + digit-number queries landing on / and
  /receive-sms/us/ at pos 1-6.8. Label-flip gate (>=50 clicked rows) not near at 25;
  no retrain. Daily table still ends Nov 7.

## Uptime monitor created (external detection gap closed)

Better Stack had ZERO active fleet monitors (one paused legacy adstim.net entry), which
is why every OFC outage today was discovered manually. Created status monitor 5206772
"OpenFileConverter (openfileconverter.com)" - GET / every 60s from us+eu, 30s timeout,
email alerts, 60s confirm/recover. Status-type chosen deliberately: today's populate
death served hard 500s at 80-150ms TTFB; only a status-code check catches that.
Fleet gap remains open for the other properties.

## Second outage + rollback (evening) — tug-of-war escalated, registry created

Minutes after monitor creation, production regressed to the same hard-500 signature
(cold 4.4s 500 then fast 500s). CF versions API confirmed TWO new wrangler deploys
after my rollback: #336 (08:14Z) and #337 (08:19Z), both as magebase.dev@gmail.com
(shared token - agent-attribution impossible). #337 served the branch's fail-fast
populate error (wsgi.py:151 line numbers match the branch init gate).

Rolled back AGAIN via `wrangler rollback --version-id 8def3a9f...` (faster than a
rebuild deploy). One stale-isolate 500 during rotation, then warm 200s at 56-68ms;
/studio/gerber/ 200. The Better Stack monitor (created minutes earlier) now watches
this exact failure mode every 60s.

Created the shared task registry the repo instructions prescribe (TASKS.md, commit
6708083d on local main) with: the deploy blocker (populate-death traceback, static
findings, do-not-deploy directive), both rollback timestamps, and a claim-before-
mutation protocol for this worker. A third rollback will happen automatically while
the blocker stands - the wave owner must capture the real populate traceback with
`wrangler tail` before any further production deploy of the branch.
