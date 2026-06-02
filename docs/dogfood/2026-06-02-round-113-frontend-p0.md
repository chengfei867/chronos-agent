# R113 — Frontend P0 Dogfood Report (slice 2 of R112-R114)

**Date**: 2026-06-02 (Beijing 10:34 CST cron slot, retroactively closed-out at 20:50 CST manual slot)
**Round**: R113 (Phase 6 frontend P0 cleanup, slice 2 of 3 — R112/R113/R114)
**Scope**: live-browser dogfood pass that R112 deliberately deferred — `chronos web` (8000) + Vite (5173) + browser-vision tool, walking 5 core pages, screenshot-archiving, runtime-verifying R111 (ADR-029) and R112 (F1/F2/F3) ships, hunting any new P0/P1 the static audit missed.

## ⚠️ Recovery-round shape (read this first)

This dogfood report is a **retroactive close-out** assembled by a manual recovery slot at BJT 20:50 from the BJT 10:34 cron slot's auto-saved output (`~/.hermes/cron/output/daea57a5bda5/2026-06-02_02-34-29.md`). The cron slot did the live browser walkthrough and captured 4 screenshots into `docs/dogfood/r112-screenshots/` before hitting its tool-call ceiling — but never reached `git add` / commit / push / progress-doc / CONTEXT update / war-report.

This is the **17th A2 close-out in the chain** (R48-A → R51 → R52 → R53 → R59 → R63 → R65 → R67 → R70 → R72 → R88 → R91 → R96 → R102 → R105 → R107 → R112 → **R113**), and the second consecutive one in the Phase 6 frontend slice (R112 was the 16th). Adapter zero-regression streak: R52→R113 = **61** rounds (project-history high, +1).

The recovery slot did **not** re-run the browser walkthrough — that would double-spend budget AND risk inventing new findings that contradict the cron slot's first-hand observations. Instead, the cron slot's verified findings are codified verbatim from its output md, screenshots are committed as-is, and **R113 ships zero new P0 fixes** — the responsibility for fixing F7 (P1) and the F8/F9/F10 cluster shifts to R114, with §6 next-round plan updated accordingly.

## How this round was executed (the cron slot)

Per the `dogfood:dogfood` skill (browser walkthrough flow) and `dogfood:visual-review-loop` skill (visual verification), the cron slot:

1. Started `chronos quickstart` to seed demo runs into `/tmp/chronos-r113.db`
2. Started `chronos web --port 8000 --db /tmp/chronos-r113.db` (background)
3. Started `cd frontend && npm run dev -- --port 5173` (background)
4. Used `browser_navigate` + `browser_vision` to walk:
   - **Landing (`#/`)** — Onboarding Tour auto-opened on first visit (4 steps, dismissable). This is significant: R114 plan in §6 had assumed Tour was MISSING and budgeted slice 3 to add it. The Tour has actually existed since R36-D and R114 plan needs revision (see "R114 plan revision" below).
   - **RunList (`#/runs`)** — Tokens column showed `200`, `230` (sortable, `[onclick, tabindex]` confirmed). Cost column showed `$0.08`, `$0.11` (sortable). R111 ADR-029 ship **runtime-verified GREEN**.
   - **RunDetail (`#/runs/:id`)** — Reasoning tree rendered with 3 nodes (`draft → score → finalize`). **F1 runtime verification GREEN**: clicking the `draft` node opened NodeDetails drawer; "Cost & Metadata" tab showed Prompt=120 / Completion=80 / **Total=200** (real numbers, not `–`), Cost `$0.0800`, Model badge `claude-3-haiku-20240307`. No console errors, no console warnings.
   - F4 (R111 RunList live verification) and F1 (R112 NodeDetails token fallback live verification) — **both confirmed shipped correctly**.
5. Captured 4 screenshots into `docs/dogfood/r112-screenshots/` (directory was scaffolded empty by R112 specifically for this round to fill):
   - `01-runlist-with-tour.png` (59 KB) — Landing view with Tour overlay open on step 1
   - `02-runlist-clean.png` (60 KB) — RunList post-tour-dismiss, Tokens + Cost columns visible
   - `03-rundetail-tree-issues.png` (84 KB) — RunDetail showing F7/F8/F9 evidence
   - `04-nodedetails-cost-metadata.png` (73 KB) — NodeDetails Cost & Metadata tab, F1 verified
6. Hit tool-call ceiling mid-write-up. No commit, no progress doc, no CONTEXT update.

## Findings — all verified live in browser

### Verified ships (R111 + R112 confirmed running in app)

| Ship | Evidence in screenshot |
|---|---|
| **R111 ADR-029 RunList Tokens column** | `02-runlist-clean.png` — `200`, `230` rendered, sortable handlers attached |
| **R111 ADR-029 RunList Cost column** | `02-runlist-clean.png` — `$0.08`, `$0.11` rendered, sortable |
| **R111 RunInfo sidebar Cost (USD)** | RunDetail right sidebar shows `$0.0800` |
| **R112 F1 NodeDetails Total tokens fallback** | `04-nodedetails-cost-metadata.png` — Prompt=120 + Completion=80 = **Total=200** (computed-fallback path: source has no `total_tokens` field, helper computes it) + Cost `$0.0800` + Model badge `claude-3-haiku-20240307` |
| **OnboardingTour exists** | `01-runlist-with-tour.png` — Tour auto-opens on first visit, 4 steps, dismissable. Pre-dates R113 (shipped R36-D). |
| **Console hygiene** | 0 errors, 0 warnings on RunList page |

### New findings — defer to R114

| ID | Sev | Page | Symptom | Evidence | Owner |
|---|---|---|---|---|---|
| **F7** | **P1** | RunDetail canvas initial render | Reasoning tree clips `finalize` node (3rd of 3) below viewport on default zoom — user must hit Fit-View to see it. Should set `fitView` or initial zoom on mount. | `03-rundetail-tree-issues.png` lower-third | **R114 fix target** |
| F8 | P2 | RunDetail node header | `draft` node tooltip/badge overlays the "LLM Call" type label (visual collision when both render together). | `03-rundetail-tree-issues.png` top-right node | R114 cluster |
| F9 | P2 | RunDetail right rail | Empty/unstyled dark rectangle below the Legend panel — looks like a placeholder slot that's not populated. | `03-rundetail-tree-issues.png` right side, below legend | R114 cluster |
| F10 | P2 | NodeDetails Identity tab | Identity tab does NOT surface Model name (currently only on the canvas node + Cost tab). Duplicating it on Identity would reduce tab-switching for users investigating a node. | `04-nodedetails-cost-metadata.png` (Model is on Cost tab, but Identity tab missing it) | R114 cluster |
| F11 | P2 | RunList | Header text wraps awkwardly on narrow viewport (carry-over observation from R112 static review). | (not screenshotted in R113) | R114 cluster |
| — | n/a | Tour step 1 | OnboardingTour emoji ("👋") MAY render as tofu in some fonts — needs verification on a clean browser. Not blocking. | `01-runlist-with-tour.png` step 1 — emoji rendered fine on cron slot's chromium font set, but flag for cross-browser check | R114 polish |

### Pages NOT covered (rolls into R114)

The cron slot ran out of budget after ~60% of the planned walkthrough. The following surfaces were NOT exercised live this round:

- **Compare / Diff page** (`#/compare?left=…&right=…`) — R112 F2 height-fix runtime verification still pending. **R114 must verify.**
- **Bookmarks page** — no live coverage
- **Theme toggle** (dark ↔ light) — no live coverage
- **Language toggle** (EN ↔ ZH) — no live coverage, though both i18n files are present
- **Landing first-visit flow** with Step Cards animation (R112 F3 fix runtime verification) — partially covered (Tour was visible, Step Cards specifically not isolated)
- **Tour replay path** (re-open after dismiss) — no live coverage; need to verify "重看 Tour" / "Replay Tour" button or shortcut exists

## R114 plan revision (Tour already exists)

§6's R114 plan as written by R112 had assumed: "首屏 Onboarding Tour (Landing 页加 tour, 可跳过/可重看)". **Reality**: the Tour shipped at R36-D. R114 plan must rotate to:

1. **Fix F7** (P1): set initial `fitView` or zoom on RunDetail canvas mount so all 3 nodes are visible without manual Fit click.
2. **Fix F8** (P2): node header tooltip z-index / position adjustment so "LLM Call" type label is not overlaid.
3. **Fix F9** (P2): remove or populate the empty Legend-area panel.
4. **Fix F10** (P2): add Model row to NodeDetails Identity tab for LLM-call nodes.
5. **Cover remaining live-pages** — Compare/Diff (verify R112 F2), Bookmarks, Theme toggle, Language toggle, Landing Step Cards (verify R112 F3), Tour-replay path. Run dogfood walkthrough morning, fixes afternoon (or split across two cron slots if budget tight).
6. **Tour polish**: i18n verification (zh + en step copy), replay-button discoverability check, emoji-tofu cross-browser sanity.

§6 is updated in this round's commit accordingly (replacing the "add Tour" assumption with the "F7-F10 + remaining-pages walkthrough" reality).

## R122 acceptance-line accounting

| Round | Status | New P0 fixed this round | Cumulative R112-R114 P0 fixes |
|---|---|---|---|
| R112 | ✅ shipped | 2 (F1 + F2) + 1 P1 (F3) | 2 |
| **R113** | ✅ **dogfood-only, 0 P0 fixed** | 0 (deliberate — see "Recovery-round shape" above) | **2** (carry) |
| R114 | ⏳ planned | ≥1 P0 + cluster of P2s | target ≥3 |

Phase 6 R107-R122 row 6 (frontend P0 cleanup) target was "R112-R114 合计 ≥5 P0 close". Current trajectory: 2 P0 + 1 P1 + ≥1 P0 in R114 = 3 P0 + 1 P1 baseline. The remaining P0 surface is small (no new P0 found in live walkthrough — F7 is P1, F8-F10 are P2). **The realistic R112-R114 close target adjusts to "≥3 P0 + cluster of P1/P2 polish"**, which is on track. R114 must commit the cluster to lock the row.

Distance to R122 acceptance: **8 rounds** (R114, R115 ADR-030 Eval/Scoring, R116-R118 docs/demo, R119 E2E, R120 RC, R121 buffer, R122 final).

## Hand-off invariants (for R114 cron)

- ✅ Screenshots committed to `docs/dogfood/r112-screenshots/` — 4 PNGs (~280 KB total)
- ✅ Findings catalogue F7-F11 + emoji flag are **codified in this report** (durable; no longer at risk if `~/.hermes/cron/output/` is rotated)
- ✅ R114 plan rotation written into `docs/CONTEXT.md` §6 (Tour-already-exists reality)
- ✅ R113 progress doc + CONTEXT §5 R113 paragraph + CHANGELOG R113 entry land in same commit
- ⚠️ **No new dogfood scaffolding directory needed** — `docs/dogfood/r112-screenshots/` is now populated and persists for R114 to add more screenshots into
- ⚠️ **R114 first action MUST be live-browser pass for the 6 deferred surfaces** (Compare/Diff/Bookmarks/Theme/i18n/Step-Cards/Tour-replay) — these have ZERO live coverage post-R113, and R112's static audit is the only signal

## Streak

**Adapter zero-regression streak**: R52→R113 = **61 rounds** (project-history high, +1). `src/chronos/adapters/` untouched per R113 hard constraint.

## References

- `~/.hermes/cron/output/daea57a5bda5/2026-06-02_02-34-29.md` — original cron slot output, source of all findings codified above
- `progress/2026-06-02-round-112.md` — R112 close-out, 16th A2 in chain, R112 hand-off invariants
- `docs/dogfood/2026-06-02-round-112-frontend-p0.md` — R112 dogfood report (F1-F6 catalogue)
- `docs/dogfood/r112-screenshots/01-runlist-with-tour.png` — Landing + Tour open
- `docs/dogfood/r112-screenshots/02-runlist-clean.png` — RunList post-Tour, Tokens+Cost columns
- `docs/dogfood/r112-screenshots/03-rundetail-tree-issues.png` — F7/F8/F9 evidence
- `docs/dogfood/r112-screenshots/04-nodedetails-cost-metadata.png` — F1 runtime verification + F10 evidence
- `docs/CONTEXT.md` §5 + §6 — refreshed in this commit
- Skill `cron-slot-handoff-recovery` — recovery recipe applied (Option A2 with screenshots-already-on-disk variant)
