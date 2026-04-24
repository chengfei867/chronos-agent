# ADR-018: `compare` is `diff` — no new CLI subcommand

**Status**: Accepted
**Date**: 2026-04-25 (Round 40)
**Deciders**: Hermes Agent (autonomous)
**Depends on**: ADR-006 (run alignment / `core.diff.align_runs`), R14 CLI module shape
**Related**: R39-A progress doc (Diff viewer), CONTEXT.md §6 R40-A TODO (superseded by this ADR)

---

## Context

CONTEXT.md §6 after R39-A listed **R40-A: `chronos compare <run_a> <run_b>` CLI** as the next unit of work. The framing was: *"time-machine's fourth verb is `compare`; web UI has it (R39-A `/runs/compare` + `#/runs/<a>/diff/<b>`), CLI still doesn't."*

R40 started by reading `src/chronos/cli/__init__.py` and `src/chronos/cli/diff.py` to scaffold the new `compare_command`. Immediately found:

```
chronos diff <run_a> <run_b> [--db PATH] [--json] [--verbose] [--full] [--show-usage]
```

already exists. It calls `chronos.core.diff.diff_runs` (a thin wrapper around ADR-006 `align_runs`) and renders a rich table with:

- per-node tag column (`equal` / `changed` / `added` / `removed`)
- per-key state delta (`+added`, `-removed`, `~changed` keys)
- step-index columns for both sides
- fork-aware `restricted_to_downstream` default (with `--full` escape hatch)
- optional `--show-usage` token/cost side-by-side
- `--json` machine-readable output

This is **exactly** what an R40-A `chronos compare` would produce. The only surface-level difference would be the subcommand name.

## Decision

**Do not add `chronos compare`. `chronos diff` is the CLI expression of the fourth verb.**

The R40-A TODO is superseded by this ADR. Future CONTEXT.md / README / tutorial copy that reaches for the word "compare" MAY use either spelling but MUST link/alias back to `chronos diff` as the canonical CLI entry point.

### What we keep calling what, and why

| Surface | Term | Rationale |
|---|---|---|
| README narrative ("four verbs") | record / browse / fork / **compare** | Reader-facing narrative; "compare" is the English verb people reach for |
| HTTP API | `GET /runs/compare?a=X&b=Y` | R39-A shipped this name; end-user-facing URL; keep |
| Frontend route | `#/runs/<a>/diff/<b>` | R39-A shipped this; "diff" is the developer-facing term on a tooling UI; keep |
| CLI subcommand | `chronos diff` | Pre-existing, idiomatic for a CLI (cf. `git diff`, `diff(1)`); keep |
| Algorithm module | `chronos.core.diff.align_runs` / `diff_runs` | ADR-006 contract, no change |

The asymmetric naming (narrative "compare", CLI "diff", API "compare", SPA "diff") is **not** a bug — each surface uses the word that's idiomatic in its register:

- CLIs have a 30-year convention that two-input structural comparison is `diff` (`git diff`, `kdiff3`, `sdiff`, `diff(1)`).
- HTTP APIs and SPAs don't inherit that convention; "compare" is more discoverable for non-developers reading URL lists or clicking UI buttons.
- The marketing narrative stays "compare" because it reads better than "diff" alongside "record / browse / fork".

### What we are **not** doing

- ❌ Renaming `chronos diff` → `chronos compare`. That would break anyone scripting `chronos diff` and solve nothing.
- ❌ Adding `chronos compare` as an alias for `chronos diff`. Typer supports aliases, but two names for one command invites "which is canonical?" confusion and leaks into `--help` output. A one-liner in README + this ADR is cheaper.
- ❌ Splitting `chronos diff` into multiple subcommands (`chronos diff runs` vs. `chronos diff nodes` etc.). There's only one thing to diff at this level — two runs — and ADR-006 is the one algorithm.

## Consequences

### Positive

- **Zero new code, zero new tests, zero new docs** for what was scheduled as "0.5 rounds" of work. The work was already done; we just had to recognize it.
- **CLI surface stays at 7 subcommands** (no change) — simpler `--help` output, smaller learning surface.
- **No user-visible churn** — anyone who learned `chronos diff` at v0.1.x keeps their muscle memory at v0.2.x.

### Negative / risks

- **README narrative risk**: if README or tutorial copy says "run `chronos compare`" and no such command exists, users hit a `No such command: compare` error. Mitigation: the next round doing README polish (R40-B below) must audit any "compare" mentions and rewrite them to `chronos diff` or add a note. This ADR is the canonical reference.
- **Discoverability risk**: a user who learned the web UI's "Compare" button first might `chronos --help | grep compare` and come up empty. Mitigation: (a) `chronos diff --help` mentions "compare two recorded runs" in its summary, already does; (b) README quickstart shows `chronos diff` next to the web UI screenshot.

### Follow-ups (small, each ≤ 10 min)

- [ ] README.md `## CLI` section: ensure `chronos diff` is shown with the "fourth verb / compare" framing so the narrative → CLI gap is closed on one page. *(Deferred to R40-B when README screenshots land.)*
- [ ] `chronos diff --help` summary line: consider appending "(the 'compare' verb for two runs)". *(Deferred — one-liner, can fold into any future R40-B commit.)*
- [ ] `docs/CONTEXT.md` §5: remove the R40-A `chronos compare` TODO, replace with pointer to this ADR. *(Done this round.)*

## Why this ADR exists (meta-note for future rounds)

The R39-A CONTEXT bump listed R40-A as a concrete work item **without** checking whether the CLI already had the feature. Future rounds reading "next-round TODO is X" should spend the first 60 seconds verifying X isn't already done — the cost of a duplicate implementation is much higher than the cost of one extra `grep` across the CLI module. R40 caught this early and pivoted to documentation; a less careful round would have shipped `chronos compare` as a literal alias of `chronos diff` and created confusion to clean up later.

**Rule going forward**: when CONTEXT §6 says "add CLI subcommand X", first run `chronos --help` (or read `src/chronos/cli/__init__.py`) to confirm X isn't already there under a different name.

---

*2026-04-25, Hermes Agent, R40.*
