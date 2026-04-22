# Roadmap — Chronos Agent

> ⚠️ This roadmap is a **living document**. Milestones are defined at the end of each design phase, not upfront.
> The purpose of this file at the start of the project is to be a **skeleton** — concrete scope for each version is set once research/design docs are complete.

---

## Phase 0 — Research & Design (Current)

**Goal**: Turn gut-feeling product idea into documented, falsifiable engineering spec.

**Deliverables (all docs, no code yet):**
- [ ] `docs/research/competitors.md` — Global competitor deep dive (≥10 competitors analyzed)
- [ ] `docs/research/feasibility.md` — Technical feasibility study (OTel GenAI, MCP trace, agent framework hooks)
- [ ] `docs/research/risks.md` — Risk register (technical, legal, commercial)
- [ ] `docs/design/user-stories.md` — CLI & web use case walkthroughs
- [ ] `docs/design/architecture.md` — Architecture design with Mermaid diagrams
- [ ] `docs/decisions/ADR-001-language.md` — Implementation language selection
- [ ] Additional ADRs as needed (trace format, storage backend, framework priority)

**Exit criteria**: All seven deliverables merged on `main`. User-facing `README.md` reflects latest thinking.

**Estimated rounds**: 3–6 (cron rounds, each ~4h cycle)

---

## Phase 1 — v0.1 MVP

**Goal**: First usable demo — record/replay/fork a real agent run for a single framework.

**Scope (TBD at end of Phase 0, placeholder):**
- Trace capture: instrument one agent framework (TBD)
- Storage: local file-based trace DB
- Replay: CLI walk-through of a recorded run
- Fork: swap prompt/LLM at a node, re-run downstream
- No web UI yet — CLI-only

**Exit criteria**: Full demo video-able flow end-to-end on one example agent program.

---

## Phase 2 — v0.2 Multi-Agent

**Goal**: Extend to multi-agent reasoning trees.

**Scope (placeholder):**
- Multiple parallel/nested agent calls represented as tree
- Cross-agent dependency tracking
- Fork of sub-tree
- Structured diff between two tree runs

---

## Phase 3 — v0.3+ Web UI & Adapters

**Goal**: Make it useful for humans, not just the AI itself.

**Scope (placeholder):**
- Web UI (visualize reasoning tree + fork + diff)
- Additional framework adapters
- Trace sharing / collaboration features

---

## Phase 4+ — Future (Vague on Purpose)

- Cloud-hosted trace storage
- Team / organization features
- Pricing / commercial model experiments

---

*Each phase ends with a retrospective in `progress/retrospective-phase-N.md`.*
