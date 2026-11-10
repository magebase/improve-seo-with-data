# Fleet Deploy Safety — Pre-Deploy Guardrails (2026-11-10)

Born from the 2026-11-10 deploy war: a stale-worktree checkpoint commit
(`0153f395`) reverted ~50 commits of shipped work across products, and
concurrent agent windows deploying from `origin/main` (which lacked the
local-only fixes) re-stomped production repeatedly. Two skill invocations
were burned rebuilding deleted OFC code. These guardrails are mandatory for
every skill-driven deploy.

## The three gates (`scripts/preflight_deploy_guard.py` in saas-factory)

Every product deploy wrapper calls `preflight_deploy_guard(...)` before
`wrangler deploy`. A gate failure aborts the deploy.

### Gate 1 — Remote ancestry (anti re-stomp)

Deploying HEAD that is not a strict descendant of `origin/main` rolls
production back to a diverged lineage. The guard fetches `origin/main` and
requires `git merge-base --is-ancestor origin/main HEAD`.

**Operator procedure when the gate fires:** stop other deploying windows,
reconcile local main with origin/main (merge or rebase, resolving conflicts
with intent preservation), run the product gates, push, then deploy.

### Gate 2 — Tree hygiene and path-scoped staging (anti clobber)

- No uncommitted changes under the product path at deploy time: deploy what
  you committed, never what happens to be lying in the tree.
- Staged changes must not span multiple top-level product directories. One
  conceptual change per product; never `git add -A` or `git commit -a` in
  this monorepo — that is the exact mechanism that let one stale checkpoint
  clobber `apps/file_converter/`, thrift-sweeper, and smsriver at once.

### Gate 3 — Baseline regression floor (anti ship-broken)

`scripts/deploy_test_baselines.json` records, per product, the maximum
tolerable pytest failure count over the product's test files. The guard runs
the suite and blocks the deploy when failures exceed baseline.

- Seed baselines with today's measured numbers (e.g. OFC: 35 known
  pre-existing failures on the unit suite at reconciliation time).
- Re-baselining upward requires evidence in the deploy transcript (which
  tests got worse and why the new state is correct). Re-baselining downward
  is always welcome.

## Emergency override

`DEPLOY_GUARD_DISABLE=1` skips the gates. It prints a loud warning; use only
to document a live-incident override, and reconcile immediately after.

## Skill workflow addition

After claim-before-mutation, the deploy step of any wave is now:
claim → worktree → RED → GREEN → commit (path-scoped) →
**preflight gates** → `wrangler deploy` → live verification → run-doc entry.
