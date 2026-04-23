# ADR-007: Replay TUI Framework Selection

- **Status**: Accepted
- **Date**: 2026-04-23 (Round 10)
- **Supersedes / Related**: ADR-003 (node ordering via `step_index`), ADR-006 (diff alignment — the replay view will reuse the alignment concept when we add side-by-side replay in Phase 2).

---

## Context

Milestone **M1.7** is the `chronos replay <run_id>` command: step through
the nodes of a recorded `Run` interactively, showing each node's
`node_name`, `kind`, `state_after` preview, and token/cost when present.
Keyboard drives the cursor (`space`/`→` = next, `←` = previous, `q` =
quit, `home`/`end` = jump to start/end).

This is the "catch up to competitors" feature — Langfuse, Laminar, and
Phoenix all have trace viewers; our differentiator is fork+diff, not
replay. So the bar for M1.7 is **"works, looks fine, ships in one
round"**, not "best-in-class TUI". Over-investing here would steal time
from the Phase 2 AutoGen adapter work which **is** on the critical path
for our moat.

The design decision that matters: which TUI library do we adopt? Once
chosen, the replay module inherits that dependency forever, and every
future interactive TUI command (e.g. `chronos fork --interactive` in
Phase 2/3, a real-time tail mode, etc.) will use the same framework for
consistency.

---

## Candidates Considered

### A. `rich.live` (**chosen**)

> Use the `rich.live.Live` context manager to re-render a
> `rich.layout.Layout` on keystrokes. Keyboard capture via stdlib
> `termios`/`tty` raw mode (or `readchar` as a 30-line helper).

Already a direct dependency (`rich` 15.0.0, used everywhere in the CLI).
Zero new dependencies. The screens we need are static-looking
"paginated detail panel"-style, not games or dashboards — `rich.live`
handles this exactly right.

Tradeoffs accepted:
- **No built-in keyboard abstraction**: we roll our own ~20-line raw-mode
  reader. Acceptable because the key set is tiny (arrows + space + q).
- **No widget model**: we can't drop in a scrollable list widget; we
  render a fresh Layout each frame. Fine at our scale (<1000 nodes;
  humans scroll one step at a time).
- **No mouse support**: explicitly out-of-scope for M1.7. If Phase 2
  wants mouse, we revisit.

### B. `textual`

> Full reactive-TUI framework from the Textualize team (same authors as
> rich). Widget-based, async, CSS-styled, mouse-aware.

Strong fit for *ambitious* TUIs (think k9s, btop clones). Overkill for a
linear "prev/next" pager:

1. **New runtime dependency**: textual is 4 MB installed + its own event
   loop. `rich` is ~500 KB and synchronous.
2. **Async contagion**: textual's `App.run()` is async; every handler is
   async; leaks into how we load data. Our codebase is sync elsewhere.
3. **Learning surface**: textual has a non-trivial mental model (CSS,
   reactive attributes, DOM-like widget tree). A future contributor
   debugging `chronos replay` would need to climb that curve.
4. **CI cost**: textual's test harness (`Pilot`) is good but adds
   non-trivial CI wall-time; our pytest suite is 3.23s today and we want
   to keep it snappy.

Defer to whenever we build something that genuinely needs widgets —
likely a real-time tail-of-runs dashboard in Phase 3, or never, if the
Web UI lands first.

### C. `prompt_toolkit`

> Full-screen apps via a proven foundation (used by IPython, pgcli,
> poetry-shell). Synchronous, no asyncio required.

Technically viable but:
- Another new dep (~1.5 MB).
- Its full-screen API is awkward for our case (the "Application" concept
  + Layout + Key bindings + Containers adds up to ~100 lines of
  boilerplate for what's essentially a paged viewer).
- We already have `typer` (which uses `click`) for the command parser;
  adding `prompt_toolkit` for the TUI gives us three console-UI libraries
  in one project.

### D. `curses` (stdlib)

> Zero dependencies. Built into Python.

Powerful but we'd be reinventing `rich`'s styling, tables, panels, and
truecolor handling from scratch. The one thing stdlib `curses` gives us
(no install step) isn't worth the ~200 lines we'd write to match what
`rich.live` does in ~20.

### E. Non-interactive "pager" mode (simplest)

> Print each node one per page, use standard `$PAGER`/`less` integration
> (`rich.pager.pager_cls`), no keyboard capture at all.

Considered as the **lower bound** of M1.7 scope. Rejected because:
- Replay is about *direction* (forward / backward / jump). A pager can
  only scroll, so you can't "reverse step" without re-opening.
- Users expect arrow keys for stepping through — less-style navigation
  is wrong affordance.
- We can keep `--no-interactive`/`--json` flags as escape hatches for
  CI/piping (and will).

---

## Decision

**Use `rich.live` for M1.7.** Roll a ~20-line raw-mode keyboard reader
in `chronos.cli.replay._keyboard.py` with a guarded stdin fallback that
prints instructions when we're not on a TTY (for CI / docs-generation
use).

## Consequences

### Positive

- **Zero new dependencies**: lockfile doesn't move.
- **Consistent render layer**: every piece of UI across our CLI uses
  `rich`. Contributors know one library.
- **Fast CI**: pytest stays sync, no textual test harness added.
- **Graceful degradation**: non-TTY callers get a legible read-only
  dump (not a hang on stdin).

### Negative / accepted

- **Writing our own keyboard reader**: ~20 lines of `termios`/`tty` raw
  mode, plus a `sys.platform == "win32"` branch using `msvcrt.getwch`.
  Covered by the replay unit tests via a mock keyboard iterator.
- **No mouse / no resize handling**: replay is a focused stepper, not a
  dashboard. Revisit in Phase 3 if needed.
- **Widget-rich future TUIs are not yet enabled**: if/when we want a
  live-updating multi-pane viewer, we'll open ADR-N for textual and
  keep `rich.live` for the simple panes. The two can coexist.

### Follow-ups

- M1.7 adds `chronos.cli.replay` submodule — refactors `cli/__init__.py`
  to split commands into sibling modules (`runs.py`, `forks.py`,
  `diff.py`, `replay.py`, `info.py`). No behavior change — purely a file
  split that keeps files under 250 lines.
- Document the keyboard cheat sheet in `docs/cli-reference.md`.
- Add `chronos replay` to the `examples/linear_pipeline.py` "Try these
  commands" block once replay ships (dogfood will verify it).

---

*Decision authority: Hermes Agent, Round 10. No human intervention.
Overturning this decision needs a new ADR citing real evidence (e.g.
"we built a multi-pane live viewer and rich.live wasn't enough") — not
preference.*
