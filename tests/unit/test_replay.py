"""Unit tests for ``chronos replay`` — CLI wiring + pure rendering helpers.

Two layers of testing:

1. **Pure-function tests** — :func:`build_frame`, :func:`advance`,
   :func:`render_static` — cover all visual/logical behaviour without a
   live loop or TTY.
2. **run_loop tests** — drive the Live loop with an injected key
   iterator (no real stdin) so we can assert keyboard → cursor → final
   state transitions deterministically.

The real keyboard reader (:func:`_read_key_blocking`) is TTY-only and
covered by manual dogfood, not unit tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from chronos.cli import app
from chronos.cli.replay import (
    KEY_FIRST,
    KEY_LAST,
    KEY_NEXT,
    KEY_PREV,
    KEY_QUIT,
    KEY_UNKNOWN,
    ReplayState,
    advance,
    build_frame,
    render_static,
    run_loop,
)
from chronos.core.models import Node, NodeKind, Run, RunStatus
from chronos.store.sqlite import SqliteStore

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run(run_id: str = "run-1") -> Run:
    t0 = datetime(2026, 4, 23, 4, 0, 0, tzinfo=UTC)
    return Run(
        id=run_id,
        adapter="langgraph",
        adapter_thread_id="thread-A",
        status=RunStatus.COMPLETED,
        started_at=t0,
        ended_at=t0,
        task_description="demo",
        initial_state={},
        final_state={"ok": True},
        tags=[],
        metadata={},
    )


def _make_node(
    *,
    id_: str,
    name: str,
    step: int,
    state: dict | None = None,
    error: str | None = None,
) -> Node:
    t0 = datetime(2026, 4, 23, 4, 0, step, tzinfo=UTC)
    return Node(
        id=id_,
        run_id="run-1",
        step_index=step,
        node_name=name,
        kind=NodeKind.LLM,
        parent_node_id=None,
        started_at=t0,
        ended_at=t0,
        state_after=state or {},
        model_name=None,
        tool_name=None,
        error_message=error,
        metadata={},
    )


@pytest.fixture
def three_node_run() -> tuple[Run, tuple[Node, ...]]:
    run = _make_run()
    nodes = (
        _make_node(id_="n0", name="plan", step=0, state={"plan": "outline"}),
        _make_node(id_="n1", name="draft", step=1, state={"draft": "hello world"}),
        _make_node(id_="n2", name="finalize", step=2, state={"final": "done"}),
    )
    return run, nodes


# ---------------------------------------------------------------------------
# advance() — pure cursor logic
# ---------------------------------------------------------------------------


class TestAdvance:
    def test_next_moves_forward(self) -> None:
        assert advance(0, 3, KEY_NEXT) == 1
        assert advance(1, 3, KEY_NEXT) == 2

    def test_next_clamps_at_end(self) -> None:
        assert advance(2, 3, KEY_NEXT) == 2

    def test_prev_moves_backward(self) -> None:
        assert advance(2, 3, KEY_PREV) == 1

    def test_prev_clamps_at_start(self) -> None:
        assert advance(0, 3, KEY_PREV) == 0

    def test_first_jumps_to_start(self) -> None:
        assert advance(2, 3, KEY_FIRST) == 0

    def test_last_jumps_to_end(self) -> None:
        assert advance(0, 3, KEY_LAST) == 2

    def test_quit_and_unknown_preserve_cursor(self) -> None:
        assert advance(1, 3, KEY_QUIT) == 1
        assert advance(1, 3, KEY_UNKNOWN) == 1
        assert advance(1, 3, "bogus") == 1

    def test_empty_total_returns_zero(self) -> None:
        assert advance(5, 0, KEY_NEXT) == 0


# ---------------------------------------------------------------------------
# ReplayState — validation
# ---------------------------------------------------------------------------


class TestReplayState:
    def test_rejects_empty_nodes(self, three_node_run: tuple[Run, tuple[Node, ...]]) -> None:
        run, _ = three_node_run
        with pytest.raises(ValueError, match="at least one node"):
            ReplayState(run=run, nodes=(), cursor=0)

    def test_rejects_negative_cursor(self, three_node_run: tuple[Run, tuple[Node, ...]]) -> None:
        run, nodes = three_node_run
        with pytest.raises(ValueError, match="out of range"):
            ReplayState(run=run, nodes=nodes, cursor=-1)

    def test_rejects_out_of_range_cursor(
        self, three_node_run: tuple[Run, tuple[Node, ...]]
    ) -> None:
        run, nodes = three_node_run
        with pytest.raises(ValueError, match="out of range"):
            ReplayState(run=run, nodes=nodes, cursor=3)


# ---------------------------------------------------------------------------
# build_frame() — rendering
# ---------------------------------------------------------------------------


def _render_to_text(renderable, width: int = 100) -> str:
    """Capture a Rich renderable into a plain string for assertions."""
    console = Console(record=True, width=width, force_terminal=True, color_system=None)
    console.print(renderable)
    return console.export_text()


class TestBuildFrame:
    def test_shows_cursor_marker_and_position(
        self, three_node_run: tuple[Run, tuple[Node, ...]]
    ) -> None:
        run, nodes = three_node_run
        out = _render_to_text(build_frame(ReplayState(run=run, nodes=nodes, cursor=1)))
        assert "▶" in out
        assert "[2/3]" in out
        assert "draft" in out  # cursor node name
        assert "plan" in out  # neighbour visible

    def test_shows_state_after_preview(self, three_node_run: tuple[Run, tuple[Node, ...]]) -> None:
        run, nodes = three_node_run
        out = _render_to_text(build_frame(ReplayState(run=run, nodes=nodes, cursor=0)))
        assert "outline" in out

    def test_truncates_long_state(self) -> None:
        run = _make_run()
        huge = _make_node(id_="big", name="big", step=0, state={"x": "A" * 5_000})
        out = _render_to_text(build_frame(ReplayState(run=run, nodes=(huge,), cursor=0)))
        assert "…" in out  # truncation marker
        # Never leak the full 5000-char value.
        assert "A" * 1000 not in out

    def test_shows_error_when_present(self) -> None:
        run = _make_run()
        bad = _make_node(id_="e1", name="bad", step=0, error="boom!")
        out = _render_to_text(build_frame(ReplayState(run=run, nodes=(bad,), cursor=0)))
        assert "boom!" in out
        assert "error" in out

    def test_header_includes_run_id_and_status(
        self, three_node_run: tuple[Run, tuple[Node, ...]]
    ) -> None:
        run, nodes = three_node_run
        out = _render_to_text(build_frame(ReplayState(run=run, nodes=nodes, cursor=0)))
        assert run.id in out
        assert "completed" in out


# ---------------------------------------------------------------------------
# render_static() — non-TTY fallback
# ---------------------------------------------------------------------------


class TestRenderStatic:
    def test_prints_every_node(self, three_node_run: tuple[Run, tuple[Node, ...]]) -> None:
        run, nodes = three_node_run
        console = Console(record=True, width=100, force_terminal=True, color_system=None)
        render_static(ReplayState(run=run, nodes=nodes, cursor=0), console)
        out = console.export_text()
        for node in nodes:
            assert node.node_name in out
        # Shows pagination counter for each
        assert "[1/3]" in out
        assert "[2/3]" in out
        assert "[3/3]" in out


# ---------------------------------------------------------------------------
# run_loop — drive with a synthetic key iterator
# ---------------------------------------------------------------------------


class TestRunLoop:
    def test_next_next_quit_lands_on_index_2(
        self, three_node_run: tuple[Run, tuple[Node, ...]]
    ) -> None:
        run, nodes = three_node_run
        state = ReplayState(run=run, nodes=nodes, cursor=0)
        console = Console(record=True, width=80, force_terminal=True, color_system=None)
        final = run_loop(state, console, iter([KEY_NEXT, KEY_NEXT, KEY_QUIT]))
        assert final == 2

    def test_last_then_prev_lands_on_index_1(
        self, three_node_run: tuple[Run, tuple[Node, ...]]
    ) -> None:
        run, nodes = three_node_run
        state = ReplayState(run=run, nodes=nodes, cursor=0)
        console = Console(record=True, width=80, force_terminal=True, color_system=None)
        final = run_loop(state, console, iter([KEY_LAST, KEY_PREV, KEY_QUIT]))
        assert final == 1

    def test_unknown_keys_do_not_move_cursor(
        self, three_node_run: tuple[Run, tuple[Node, ...]]
    ) -> None:
        run, nodes = three_node_run
        state = ReplayState(run=run, nodes=nodes, cursor=0)
        console = Console(record=True, width=80, force_terminal=True, color_system=None)
        final = run_loop(
            state,
            console,
            iter([KEY_UNKNOWN, KEY_UNKNOWN, KEY_QUIT]),
        )
        assert final == 0

    def test_exhausting_iterator_is_same_as_quit(
        self, three_node_run: tuple[Run, tuple[Node, ...]]
    ) -> None:
        """If the key stream ends (e.g. EOF on stdin) we exit cleanly."""
        run, nodes = three_node_run
        state = ReplayState(run=run, nodes=nodes, cursor=0)
        console = Console(record=True, width=80, force_terminal=True, color_system=None)
        final = run_loop(state, console, iter([KEY_NEXT]))
        assert final == 1  # moved once, then stream ended


# ---------------------------------------------------------------------------
# CLI integration — via Typer's CliRunner (stdin is a pipe, so we
# exercise the --no-interactive path which uses render_static).
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_db_with_run(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "c.db"
    store = SqliteStore.open(db)
    try:
        run = _make_run("rrr-1")
        store.put_run(run)
        for node in (
            _make_node(id_="a", name="alpha", step=0, state={"a": 1}),
            _make_node(id_="b", name="beta", step=1, state={"b": 2}),
        ):
            # override run_id so FK matches
            node_with_fk = Node(
                id=node.id,
                run_id=run.id,
                step_index=node.step_index,
                node_name=node.node_name,
                kind=node.kind,
                parent_node_id=node.parent_node_id,
                started_at=node.started_at,
                ended_at=node.ended_at,
                state_after=node.state_after,
                model_name=node.model_name,
                tool_name=node.tool_name,
                error_message=node.error_message,
                metadata=node.metadata,
            )
            store.put_node(node_with_fk)
    finally:
        store.close()
    return db, "rrr-1"


class TestReplayCli:
    def test_replay_unknown_run_errors_code_1(self, tmp_path: Path) -> None:
        db = tmp_path / "c.db"
        SqliteStore.open(db).close()
        result = runner.invoke(app, ["replay", "nope", "--db", str(db)])
        assert result.exit_code == 1
        assert "no such run" in result.stdout

    def test_replay_missing_db_errors_code_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["replay", "any", "--db", str(tmp_path / "ghost.db")])
        assert result.exit_code == 2
        assert "not found" in result.stdout

    def test_replay_run_with_no_nodes_warns(self, tmp_path: Path) -> None:
        db = tmp_path / "c.db"
        store = SqliteStore.open(db)
        try:
            store.put_run(_make_run("empty-r"))
        finally:
            store.close()
        result = runner.invoke(
            app,
            ["replay", "empty-r", "--db", str(db), "--no-interactive"],
        )
        assert result.exit_code == 0
        assert "nothing to replay" in result.stdout

    def test_replay_no_interactive_prints_every_node(
        self, seeded_db_with_run: tuple[Path, str]
    ) -> None:
        db, run_id = seeded_db_with_run
        result = runner.invoke(
            app,
            ["replay", run_id, "--db", str(db), "--no-interactive"],
        )
        assert result.exit_code == 0
        assert "alpha" in result.stdout
        assert "beta" in result.stdout
        assert "[1/2]" in result.stdout
        assert "[2/2]" in result.stdout

    def test_replay_falls_back_to_static_when_not_tty(
        self, seeded_db_with_run: tuple[Path, str]
    ) -> None:
        """CliRunner's stdin is a pipe, not a TTY → static mode auto-picks."""
        db, run_id = seeded_db_with_run
        # Without --no-interactive — should still work because isatty is False.
        result = runner.invoke(app, ["replay", run_id, "--db", str(db)])
        assert result.exit_code == 0
        assert "alpha" in result.stdout
        assert "beta" in result.stdout
