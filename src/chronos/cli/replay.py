"""Chronos replay TUI — step through a recorded run node-by-node.

See ``docs/decisions/ADR-007-replay-tui-framework.md`` for why we picked
``rich.live`` + a minimal stdlib raw-mode keyboard reader over
``textual`` / ``prompt_toolkit`` / ``curses``.

Public entry point: the ``replay`` Typer command registered in
``chronos.cli.__init__`` via :func:`register`.

Testing strategy
----------------
The view is split so unit tests don't need a TTY:

* :func:`build_frame` — *pure* function ``(nodes, cursor) -> Renderable``.
  Every visual assertion goes here.
* :func:`run_loop` — the live loop. Takes an injected ``key_iter``
  iterator so tests can drive ``next``/``prev``/``quit`` sequences
  without touching stdin.
* :func:`_read_key_blocking` — the real keyboard reader. Only invoked by
  ``chronos replay`` on a TTY. Not unit-tested directly (would require
  a pty); exercised manually + via dogfood script.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from chronos.core.models import Node, Run

# ---------------------------------------------------------------------------
# Key-code aliases
# ---------------------------------------------------------------------------

KEY_NEXT = "next"
KEY_PREV = "prev"
KEY_FIRST = "first"
KEY_LAST = "last"
KEY_QUIT = "quit"
KEY_UNKNOWN = "unknown"

_ALL_KEYS = {KEY_NEXT, KEY_PREV, KEY_FIRST, KEY_LAST, KEY_QUIT, KEY_UNKNOWN}


# ---------------------------------------------------------------------------
# Pure rendering (easy to unit-test)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayState:
    """Input to :func:`build_frame` — what the user currently sees."""

    run: Run
    nodes: tuple[Node, ...]
    cursor: int  # 0-based index into ``nodes``

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("ReplayState requires at least one node")
        if not 0 <= self.cursor < len(self.nodes):
            raise ValueError(f"cursor {self.cursor} out of range [0, {len(self.nodes) - 1}]")


def _preview_state(state: Any, max_chars: int = 600) -> str:
    """Render a node's ``state_after`` for the detail panel.

    Prefers JSON pretty-print for dict/list (the common case from our
    canonical schema). Falls back to ``repr`` for other shapes. Truncates
    long values with an ellipsis so one node never blows the panel.
    """
    if state is None:
        return "(none)"
    try:
        rendered = json.dumps(state, indent=2, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered = repr(state)
    if len(rendered) > max_chars:
        rendered = rendered[: max_chars - 1] + "…"
    return rendered


def build_frame(state: ReplayState) -> Group:
    """Render one replay frame. Pure function — test this, not the Live loop."""
    run = state.run
    nodes = state.nodes
    cursor = state.cursor
    current = nodes[cursor]
    total = len(nodes)

    # ---- Header -----------------------------------------------------------
    header = Text.assemble(
        ("chronos replay", "bold cyan"),
        "  ",
        (run.id, "cyan"),
        "  ",
        (f"[{cursor + 1}/{total}]", "yellow"),
        "  ",
        (run.status.value, "green" if run.status.value == "completed" else "magenta"),
    )

    # ---- Node list (shows a sliding window around the cursor) -------------
    list_table = Table.grid(padding=(0, 1))
    list_table.add_column(justify="right", style="dim", width=4)
    list_table.add_column()  # cursor marker
    list_table.add_column(style="green")
    list_table.add_column(style="dim")

    # Window of 7 nodes centered on cursor — keeps rendering bounded on
    # long runs while always showing neighbours for orientation.
    window = 3
    lo = max(0, cursor - window)
    hi = min(total, cursor + window + 1)
    if lo > 0:
        list_table.add_row("…", "", "", "")
    for i in range(lo, hi):
        n = nodes[i]
        marker = "▶" if i == cursor else " "
        marker_style = "bold yellow" if i == cursor else "dim"
        row_style = "bold" if i == cursor else ""
        list_table.add_row(
            f"[{n.step_index}]",
            Text(marker, style=marker_style),
            Text(n.node_name, style=row_style),
            n.kind.value,
        )
    if hi < total:
        list_table.add_row("…", "", "", "")

    nodes_panel = Panel(list_table, title="nodes", border_style="cyan")

    # ---- Detail panel for the cursor's node ------------------------------
    detail_table = Table.grid(padding=(0, 2))
    detail_table.add_column(style="dim", justify="right")
    detail_table.add_column()
    detail_table.add_row("step", str(current.step_index))
    detail_table.add_row("name", current.node_name)
    detail_table.add_row("kind", current.kind.value)
    detail_table.add_row("id", current.id)
    detail_table.add_row("started", current.started_at.isoformat(timespec="seconds"))
    if current.ended_at:
        detail_table.add_row("ended", current.ended_at.isoformat(timespec="seconds"))
    if current.model_name:
        detail_table.add_row("model", current.model_name)
    if current.tool_name:
        detail_table.add_row("tool", current.tool_name)
    if current.parent_node_id:
        detail_table.add_row("parent_id", current.parent_node_id)
    if current.error_message:
        detail_table.add_row("error", Text(current.error_message, style="red"))
    detail_table.add_row("state_after", Text(_preview_state(current.state_after)))

    detail_panel = Panel(
        detail_table,
        title=f"node @ {current.node_name}",
        border_style="green",
    )

    # ---- Footer (keyboard cheat sheet) ------------------------------------
    footer = Text.assemble(
        ("space/→ ", "bold"),
        "next  ",
        ("← ", "bold"),
        "prev  ",
        ("home ", "bold"),
        "first  ",
        ("end ", "bold"),
        "last  ",
        ("q ", "bold"),
        "quit",
        style="dim",
    )

    return Group(header, Text(""), nodes_panel, detail_panel, footer)


# ---------------------------------------------------------------------------
# Static (no-TTY) rendering — used on pipes, CI, --no-interactive
# ---------------------------------------------------------------------------


def render_static(state: ReplayState, console: Console) -> None:
    """Print every node one after another. Used when stdin isn't a TTY.

    Keeping this a pure function means tests can capture the output via
    ``Console(record=True)`` and assert on the full dump.
    """
    for i in range(len(state.nodes)):
        frame_state = ReplayState(run=state.run, nodes=state.nodes, cursor=i)
        console.print(build_frame(frame_state))
        console.print()  # blank line between frames


# ---------------------------------------------------------------------------
# Cursor logic (tested standalone)
# ---------------------------------------------------------------------------


def advance(cursor: int, total: int, key: str) -> int:
    """Apply one key press to the cursor. Pure. Never raises on bad key."""
    if total <= 0:
        return 0
    if key == KEY_NEXT:
        return min(cursor + 1, total - 1)
    if key == KEY_PREV:
        return max(cursor - 1, 0)
    if key == KEY_FIRST:
        return 0
    if key == KEY_LAST:
        return total - 1
    # KEY_QUIT / KEY_UNKNOWN / anything else → no move
    return cursor


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------


def run_loop(
    state: ReplayState,
    console: Console,
    key_iter: Iterable[str],
) -> int:
    """Drive the live TUI. Returns the final cursor position.

    ``key_iter`` yields normalised key codes (:data:`KEY_NEXT`, etc.). In
    production this is a wrapper around :func:`_read_key_blocking`; in
    tests we pass a list.
    """
    cursor = state.cursor
    # Start with the initial frame already rendered so the user sees
    # *something* before touching a key.
    with Live(
        build_frame(state),
        console=console,
        auto_refresh=False,
        screen=False,
    ) as live:
        for key in key_iter:
            if key == KEY_QUIT:
                break
            cursor = advance(cursor, len(state.nodes), key)
            new_state = ReplayState(run=state.run, nodes=state.nodes, cursor=cursor)
            live.update(build_frame(new_state), refresh=True)
    return cursor


# ---------------------------------------------------------------------------
# Real keyboard reader (Unix + Windows)
# ---------------------------------------------------------------------------


def _read_key_blocking() -> Iterator[str]:  # pragma: no cover — TTY-only
    """Yield one normalised key code per physical keypress until EOF.

    Supports arrow keys (CSI escape sequences on Unix, 0xE0-prefix on
    Windows), space, q/Q/Ctrl-C, Home, End.

    Only called when ``sys.stdin.isatty()``. Callers on non-TTY stdin
    should use :func:`render_static` instead.
    """
    if os.name == "nt":
        import msvcrt  # Windows-only

        while True:
            ch = msvcrt.getwch()  # type: ignore[attr-defined]
            if ch in ("\x03", "\x04", "q", "Q"):
                yield KEY_QUIT
                return
            if ch in (" ", "\r", "\n"):
                yield KEY_NEXT
                continue
            if ch in ("\x00", "\xe0"):
                # Extended key — arrow/home/end
                ch2 = msvcrt.getwch()  # type: ignore[attr-defined]
                yield {
                    "H": KEY_PREV,  # wait, H is up — we treat up as prev
                    "P": KEY_NEXT,  # down → next (alt binding)
                    "K": KEY_PREV,  # left
                    "M": KEY_NEXT,  # right
                    "G": KEY_FIRST,  # home
                    "O": KEY_LAST,  # end
                }.get(ch2, KEY_UNKNOWN)
                continue
            yield KEY_UNKNOWN
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if not ch:
                    return
                if ch in ("\x03", "\x04", "q", "Q"):
                    yield KEY_QUIT
                    return
                if ch in (" ", "\r", "\n"):
                    yield KEY_NEXT
                    continue
                if ch == "\x1b":
                    # Escape sequence: CSI A/B/C/D for arrows, H/F for home/end.
                    seq = sys.stdin.read(2)
                    if seq == "[A":
                        yield KEY_PREV  # up
                    elif seq == "[B":
                        yield KEY_NEXT  # down
                    elif seq == "[C":
                        yield KEY_NEXT  # right
                    elif seq == "[D":
                        yield KEY_PREV  # left
                    elif seq == "[H" or seq == "OH":
                        yield KEY_FIRST
                    elif seq == "[F" or seq == "OF":
                        yield KEY_LAST
                    elif seq == "[1":
                        # Some terminals send ESC [ 1 ~ for Home
                        sys.stdin.read(1)
                        yield KEY_FIRST
                    elif seq == "[4":
                        sys.stdin.read(1)
                        yield KEY_LAST
                    else:
                        yield KEY_UNKNOWN
                    continue
                yield KEY_UNKNOWN
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------------------------------------------------------------------
# Typer command wiring
# ---------------------------------------------------------------------------


def replay_command(
    run_id: str,
    db: Path | None,
    no_interactive: bool,
    open_store_fn: Any,
    console: Console,
) -> None:
    """Implementation shared between the real Typer wiring and the tests.

    ``open_store_fn`` is injected so tests can hand in a dummy store
    without recreating the SqliteStore.
    """
    store = open_store_fn(db)
    try:
        run = store.get_run(run_id)
        if run is None:
            console.print(f"[red]error:[/] no such run: [bold]{run_id}[/]")
            raise typer.Exit(code=1)
        nodes = store.get_nodes_for_run(run_id)
    finally:
        store.close()

    if not nodes:
        console.print(
            f"[yellow]warning:[/] run [bold]{run_id}[/] has no nodes — nothing to replay."
        )
        return

    state = ReplayState(run=run, nodes=tuple(nodes), cursor=0)

    # Fall back to static rendering when not on a TTY or when explicitly
    # asked. This keeps `chronos replay` safe to use in CI / pipelines /
    # `tee file.log`.
    use_interactive = not no_interactive and sys.stdin.isatty() and sys.stdout.isatty()

    if not use_interactive:
        render_static(state, console)
        return

    run_loop(state, console, _read_key_blocking())
