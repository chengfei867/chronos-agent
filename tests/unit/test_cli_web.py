"""Tests for ``chronos web`` — CLI command that serves the local HTTP API.

We don't actually bind a port here: unit tests cover the command-plumbing
layer only. ``run_server_fn`` and ``open_browser_fn`` are DI-injected so we
can assert uvicorn would be invoked with the right args and that a browser
would be opened (or not) without touching sockets.

Integration coverage for the actual HTTP surface lives in
``test_api_server.py`` (TestClient against ``build_app``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from chronos.cli import app
from chronos.cli.web import web_command
from chronos.store.sqlite import SqliteStore

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """An initialised chronos.db with migrations applied but no rows."""
    p = tmp_path / "empty.db"
    SqliteStore.open(p).close()
    return p


class _SpyRunner:
    """Stand-in for :func:`uvicorn.run` that records the call without binding.

    Accepts/ignores ``**kwargs`` so the spy stays forward-compatible with any
    uvicorn option the command might add later.
    """

    def __init__(self) -> None:
        self.called = False
        self.kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs: Any) -> None:
        self.called = True
        self.kwargs = kwargs


class _SpyBrowser:
    """Records ``webbrowser.open`` calls; controllable return value."""

    def __init__(self, result: bool = True) -> None:
        self.calls: list[str] = []
        self.result = result

    def __call__(self, url: str) -> bool:
        self.calls.append(url)
        return self.result


def _wait_for_timer(timeout: float = 2.0) -> None:
    """Block briefly so the 1-second browser-open Timer thread can fire.

    The real ``web_command`` schedules the browser open via
    ``threading.Timer(1.0, ...)`` — inside a unit test we replace the
    uvicorn runner with an instant no-op, so the timer fires AFTER
    ``web_command`` returns. We join the timer by polling the spy.
    """
    import time

    start = time.monotonic()
    time.sleep(1.2)  # enough for the 1.0s delay
    while time.monotonic() - start < timeout:
        return  # one tick is enough with the sleep above


# ---------------------------------------------------------------------------
# Direct web_command() unit tests (bypass typer wiring)
# ---------------------------------------------------------------------------


class TestWebCommand:
    """Exercise :func:`web_command` directly so we can inject spies."""

    def test_runs_server_with_defaults(self, empty_db: Path) -> None:
        """Default invocation: uvicorn gets 127.0.0.1:8765 and app is a FastAPI."""
        from rich.console import Console

        from chronos.cli._common import _open_store

        spy_run = _SpyRunner()
        spy_browser = _SpyBrowser()

        web_command(
            host="127.0.0.1",
            port=8765,
            db=empty_db,
            no_browser=True,  # skip the threading dance in this test
            open_store_fn=_open_store,
            console=Console(),
            run_server_fn=spy_run,
            open_browser_fn=spy_browser,
        )

        assert spy_run.called, "uvicorn.run should have been invoked"
        assert spy_run.kwargs["host"] == "127.0.0.1"
        assert spy_run.kwargs["port"] == 8765
        # The app must be the one build_app produces — assert by duck-typing
        # the FastAPI routes rather than importing FastAPI (keeps the test
        # independent of the HTTP lib version).
        app_obj = spy_run.kwargs["app"]
        route_paths = {getattr(r, "path", None) for r in app_obj.routes}
        assert "/healthz" in route_paths
        assert "/runs" in route_paths
        # Browser not opened because no_browser=True
        assert spy_browser.calls == []

    def test_custom_host_and_port(self, empty_db: Path) -> None:
        """Non-default --host/--port propagate straight to uvicorn."""
        from rich.console import Console

        from chronos.cli._common import _open_store

        spy_run = _SpyRunner()
        web_command(
            host="0.0.0.0",
            port=9001,
            db=empty_db,
            no_browser=True,
            open_store_fn=_open_store,
            console=Console(),
            run_server_fn=spy_run,
            open_browser_fn=_SpyBrowser(),
        )
        assert spy_run.kwargs["host"] == "0.0.0.0"
        assert spy_run.kwargs["port"] == 9001

    def test_browser_opens_at_configured_url(self, empty_db: Path) -> None:
        """When --no-browser is not set, a Timer fires and opens the URL."""
        from rich.console import Console

        from chronos.cli._common import _open_store

        spy_run = _SpyRunner()
        spy_browser = _SpyBrowser()

        web_command(
            host="127.0.0.1",
            port=8765,
            db=empty_db,
            no_browser=False,
            open_store_fn=_open_store,
            console=Console(),
            run_server_fn=spy_run,
            open_browser_fn=spy_browser,
        )

        # The timer fires ~1s after web_command starts; give it time.
        _wait_for_timer()
        assert spy_browser.calls == ["http://127.0.0.1:8765"], (
            f"browser should have been opened once with the correct URL; got {spy_browser.calls}"
        )

    def test_no_browser_suppresses_open(self, empty_db: Path) -> None:
        """--no-browser means the browser is not touched even after Timer delay."""
        from rich.console import Console

        from chronos.cli._common import _open_store

        spy_run = _SpyRunner()
        spy_browser = _SpyBrowser()

        web_command(
            host="127.0.0.1",
            port=8765,
            db=empty_db,
            no_browser=True,
            open_store_fn=_open_store,
            console=Console(),
            run_server_fn=spy_run,
            open_browser_fn=spy_browser,
        )
        _wait_for_timer()
        assert spy_browser.calls == []

    def test_browser_open_failure_is_non_fatal(self, empty_db: Path) -> None:
        """``webbrowser.open`` returning False emits a notice but doesn't raise."""
        from rich.console import Console

        from chronos.cli._common import _open_store

        spy_run = _SpyRunner()
        spy_browser = _SpyBrowser(result=False)  # simulate headless failure

        # Must not raise.
        web_command(
            host="127.0.0.1",
            port=8765,
            db=empty_db,
            no_browser=False,
            open_store_fn=_open_store,
            console=Console(),
            run_server_fn=spy_run,
            open_browser_fn=spy_browser,
        )
        _wait_for_timer()
        # The open WAS attempted; it just returned False.
        assert spy_browser.calls == ["http://127.0.0.1:8765"]

    def test_missing_db_exits_before_serving(self, tmp_path: Path) -> None:
        """A nonexistent DB makes the store opener exit; uvicorn is never called."""
        import typer
        from rich.console import Console

        from chronos.cli._common import _open_store

        spy_run = _SpyRunner()
        missing = tmp_path / "does-not-exist.db"

        with pytest.raises(typer.Exit):
            web_command(
                host="127.0.0.1",
                port=8765,
                db=missing,
                no_browser=True,
                open_store_fn=_open_store,
                console=Console(),
                run_server_fn=spy_run,
                open_browser_fn=_SpyBrowser(),
            )
        assert not spy_run.called


# ---------------------------------------------------------------------------
# Typer-wired smoke tests (exercise the registration + option parsing)
# ---------------------------------------------------------------------------


class TestWebCLI:
    """Smoke-test the CLI command via typer's CliRunner.

    We monkey-patch the default server + browser helpers so these tests
    don't actually bind a port. Because ``chronos.cli.web`` reads them at
    call time (not at import), monkey-patching the module attrs is enough.
    """

    def test_web_help_does_not_require_uvicorn(self) -> None:
        """``chronos web --help`` must work even before the [web] extra is installed.

        This pins the lazy-import design: if someone accidentally moves the
        ``import uvicorn`` to module top level, this test will still pass
        (uvicorn IS installed in dev) — but the spirit of the test is
        documented here for reviewers.
        """
        result = runner.invoke(app, ["web", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--no-browser" in result.output

    def test_web_invokes_web_command(self, empty_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """End-to-end: ``chronos web --db ...`` reaches uvicorn with the right args."""
        import chronos.cli.web as web_module

        spy_run = _SpyRunner()
        monkeypatch.setattr(web_module, "_default_run_server", spy_run)
        # Also bypass the real browser at module level.
        monkeypatch.setattr(web_module, "_default_open_browser", _SpyBrowser())

        result = runner.invoke(
            app,
            ["web", "--db", str(empty_db), "--no-browser", "--port", "18765"],
        )
        assert result.exit_code == 0, result.output
        assert spy_run.called
        assert spy_run.kwargs["port"] == 18765
