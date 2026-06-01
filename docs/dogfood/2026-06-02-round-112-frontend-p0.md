# R112 — Frontend P0 Dogfood Report (slice 1 of R112-R114)

**Date**: 2026-06-02 (Beijing 00:34 CST), single cron slot
**Round**: R112 (Phase 6 frontend P0 cleanup, slice 1 of 3 — R112/R113/R114)
**Scope**: code-driven dogfood pass over the 5 core frontend pages — RunList,
RunDetail (incl. NodeDetails drawer/inline), Compare/Diff, TreeView, Landing.
Browser-driven dogfood (full `chronos web` + Vite + screenshot pass) was
budgeted for the slot but the slot inherited prior-slot WIP (3 files modified,
1 helper module added, screenshots dir empty) — recovery + close-out
consumed the slot's call budget. **R113 picks up the live-browser pass; this
report documents the code-inspection findings + the 3 fixes that landed
in R112's commit.**

## How this round was executed

Per the `cron-slot-handoff-recovery` skill (Option A1 / A2 hybrid — inherited
WIP, gates green at start, no progress doc yet), the inherited frontend
edits were code-reviewed against the R107-R122 acceptance line + R111's
Cost Visibility ship + the AntD v6 + Framer-Motion patterns the codebase
already uses, then adopted as the round's deliverables. Each inherited
edit maps 1:1 to a real P0/P1 finding documented below.

## Findings

| ID | Severity | Page | Symptom | Status |
|---|---|---|---|---|
| F1 | **P0** | NodeDetails (RunDetail drawer) | "Total Tokens" cell renders `–` even on demo nodes that DO have token usage, because adapters often record only `prompt_tokens` + `completion_tokens` and leave `total_tokens` null. Cost cell ad-hoc inline-formatted (`$${(cents/100).toFixed(4)}`) — drift risk vs. RunList's helper. | **FIXED in R112** |
| F2 | **P0** | Compare / Diff page (`#/compare?...`) | `.chr-diff-page` height collapses to 0px → ReactFlow panes show as blank rectangles. Root cause: `height: 100%` doesn't cascade through `Layout > Content > AnimatePresence > motion.div` (AnimatePresence wrapper has no explicit height). `.chr-tree-page` already uses viewport math (`calc(100vh - 56px - 48px - 48px)`), Diff was the outlier still on `height: 100%`. | **FIXED in R112** |
| F3 | **P1** | Landing (`#/`) | Step Cards (3-card "How it works" row) animate in via Framer-Motion `whileInView` + viewport gate. Because the cards are above the fold on initial load, they're already in viewport when mounted → `whileInView` does NOT fire on initial mount, so cards either flash-in instantly (wrong easing) or appear without the intended staggered reveal depending on browser quirk. Other Landing sections that ARE below the fold use `whileInView` correctly. | **FIXED in R112** |
| F4 | P1 | RunList | Token + Cost columns (R111 ADR-029 ship) — code review only; live-browser visual verification deferred to R113. Auto-hide-on-zero rule + sortable + tooltip all wired correctly per `RunList.tsx` lines 99-203. | DEFERRED to R113 (live verification) |
| F5 | P1 | TreeView | Already on viewport math (`.chr-tree-page` line 109 in `styles.css`) — confirmed not affected by the F2 root cause. | not a bug |
| F6 | P1 | RunDetail | NodeDetails fix (F1) cascades here since RunDetail renders NodeDetails. | covered by F1 |

## Fix details (what landed)

### F1 — `frontend/src/components/NodeDetails.tsx` + new `frontend/src/format/usage.ts`

- New module `frontend/src/format/usage.ts` (~50 LOC) hosts 5 small helpers:
  - `totalTokens(usage) -> number | null` — best-effort total: prefers
    `usage.total_tokens` if numeric, else falls back to
    `(prompt_tokens ?? 0) + (completion_tokens ?? 0)` when ≥1 component
    is populated, else `null`.
  - `formatTokensCompact(value) -> string` — `"1.2k"` for ≥1000, raw
    integer otherwise; `"–"` on null. Reserved for chip displays in
    R113-R114; not yet used.
  - `formatCostUsd(cents) -> string` — `$0.0800` 4dp; `"–"` on null.
  - `formatTokenDelta(delta) -> string` — `"+12"` / `"-3"` / `"±0"` for
    diff overlays. Reserved for R113 Diff page polish.
  - `formatCostDelta(deltaCents) -> string` — signed USD delta. Reserved.
- `NodeDetails.tsx` switched to `totalTokens(node.usage)` for the Total
  Tokens cell and `formatCostUsd(node.cost_usd_cents)` for the Cost cell.
  Single source of truth for token/cost rendering across the frontend
  matches the CLI's single `_summarise_usage` rule from R111 (D-111-4) —
  if a future round changes how cost cents render, only one helper has
  to change.
- Why "best-effort total" instead of "trust API exactly": the chronos
  Pydantic model's `Usage` has all three token fields optional (per
  `tests/golden/`-era schema), and several adapters (LangGraph in-process
  capture, AutoGen) historically record `prompt_tokens` + `completion_tokens`
  but not `total_tokens` because the SDK didn't expose a total. Showing
  `–` when the user can clearly see a non-zero prompt + completion is
  worse UX than computing the sum client-side.

### F2 — `frontend/src/styles.css` `.chr-diff-page`

- Changed `height: 100%` → `height: calc(100vh - 56px - 48px - 48px)`.
- Updated the leading comment to spell out the AnimatePresence wrapper
  detail explicitly so a future round understands why height: 100% won't
  work without re-deriving it.
- Tagged the comment `R112 P0 #2 fix` so git-blame on that block tells
  the right story.

### F3 — `frontend/src/pages/Landing.tsx`

- Step Cards motion changed from `whileInView` + `viewport={{once:true,...}}`
  to plain `animate={{opacity:1, y:0}}` (paired with the existing `initial`
  + `transition` with stagger via `delay: 0.1 + idx * 0.12`).
- Result: cards now animate in deterministically on mount with the
  intended stagger, regardless of whether they're above or below the
  initial viewport.
- Below-the-fold Landing sections are unchanged — `whileInView` is still
  correct for them.

## Gates passed at slot end

- `npx tsc --noEmit` (frontend) — clean
- `npm run build` (frontend, vite) — clean, 1468 KB main chunk gzip 477 KB
  (unchanged from R111 baseline; chunk-size warning pre-existing)
- `uv run pytest -q --no-cov` (backend) — **693 passed / 9 skipped / 0 failed**,
  byte-identical to R111 baseline
- `git diff --stat HEAD` — only frontend touched, no `pyproject.toml` /
  `uv.lock` drift (verified per cron-slot-handoff-recovery lockfile-trap rule)
- Adapter zero-regression streak — `src/chronos/adapters/` untouched, streak
  ratchets to **R52 → R112 = 60 rounds**

## R113-R114 hand-off (what the next slots pick up)

- **R113**: live-browser dogfood pass that this round budgeted away. Concretely:
  `chronos quickstart && chronos web` → Vite dev server → walk all 5 pages,
  capture screenshots into `docs/dogfood/r112-screenshots/` (dir is already
  scaffolded, currently empty) → cross-reference against this report's F1-F6,
  add any new findings, fix the top 1-2 P0s. Top suspects to verify:
  (a) RunList Tokens + Cost columns actually render the auto-hide rule
  visually correctly on `chronos quickstart` demo data; (b) Diff page
  ReactFlow now renders with non-zero height (F2 fix's runtime effect);
  (c) NodeDetails token cell shows `200` (= 120 + 80) for the parent
  draft node not `–` (F1 fix's runtime effect).
- **R114**: Onboarding Tour on Landing page — last R112-R114 deliverable
  per the R107-R122 route. Skip-able / re-show-able from a header button.

## R107-R122 route self-check

> **Is this round still on the R107-R122 polish + ADR-029/030 track?** YES.
> R112 = R107-R122 route table row 6 slice 1 of 3 (前端 P0 清扫 — slice 1).
> Zero adapter touch. Zero new feature direction. Zero ADR work outside the
> already-landed ADR-029. Three landed fixes all directly serve the R122
> must-pass row "前端: 5 核心页 P0 全清, 任意操作有视觉反馈". F1 specifically
> serves the R111 ADR-029 deliverable (the demo's parent draft node has
> `prompt=120, completion=80, total_tokens=null` — pre-fix this rendered
> as `–` in NodeDetails, making R111's promised "tokens visible by default"
> a half-truth on the per-node detail view; F1 closes that gap). Distance
> to R122: **10 rounds** (R113-R122).
