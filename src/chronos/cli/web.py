"""Implementation for ``chronos web`` — spin up the local HTTP API (R34-B).

This is the "one-command" on-ramp that turns a recorded ``chronos.db`` into
a browseable surface: the user runs ``chronos web``, a tab pops open, and
they can inspect runs / nodes / forks without writing any integration code.

Why a dedicated subcommand instead of asking users to run uvicorn
themselves?

1. **Friction.** ``uvicorn chronos.api.server:app`` can't work as-is —
   :func:`chronos.api.server.build_app` is a factory that needs a store,
   not a module-level ``app``. Exposing a module-level ``app`` would
   require a global, which forces an implicit default DB path and bakes
   "one store per process" into the contract. Bad trade.
2. **DB resolution consistency.** ``web`` reuses the same
   ``--db`` / ``$CHRONOS_DB`` / ``./chronos.db`` resolution as every
   other subcommand (via ``open_store_fn``), so nobody has to learn a
   second convention.
3. **Browser auto-open.** A local dev tool that doesn't open the tab
   for you is a local dev tool nobody remembers the URL of.

Design notes
------------

* **uvicorn import is lazy.** Kept inside the function so missing the
  ``[web]`` extra (``uv pip install chronos-agent[web]``) produces a
  friendly install hint instead of an ImportError at CLI startup.
* **Store lifecycle is bound to the request to serve.** We open the
  store, build the app, run uvicorn — and when uvicorn returns (user
  hit Ctrl-C), the ``with`` block closes the connection. The server
  owns the store for its lifetime; no connection pool, no reload.
* **``reload=True`` is deliberately NOT supported.** Uvicorn's reloader
  spawns a subprocess that re-imports the module path, which would lose
  our closure-bound store. ``chronos web`` is an inspection tool, not
  a dev server for editing ``server.py`` — if you're hacking on the API,
  run uvicorn directly with your own factory wrapper.
* **Browser-open timing.** We use a background :class:`threading.Timer`
  that fires ~1s after ``uvicorn.run`` starts, which is a hack but the
  idiomatic one — uvicorn's public API doesn't expose an
  "after startup" hook that works from the caller side without
  subclassing ``Server``. 1s is empirically enough on a loopback bind.
* **Testability.** ``uvicorn.run`` and ``webbrowser.open`` are injected
  via ``_run_server`` / ``_open_browser`` parameters so unit tests can
  assert the call was made without actually binding a port.
"""

from __future__ import annotations

import contextlib
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from chronos.cli._common import _resolve_db_path
from chronos.store.sqlite import SqliteStore

# Default uvicorn invocation. Factored out so tests can pass a stand-in
# without monkey-patching the uvicorn module at import time.
_UvicornRunFn = Callable[..., None]
_BrowserOpenFn = Callable[[str], bool]


def _default_run_server(**kwargs: Any) -> None:
    """Thin wrapper around :func:`uvicorn.run` kept importable lazily.

    Imported inside the function so that listing ``chronos --help`` doesn't
    require the optional ``[web]`` dependencies to be installed.
    """
    import uvicorn

    uvicorn.run(**kwargs)


def _default_open_browser(url: str) -> bool:
    """Open ``url`` in the user's default browser; return success."""
    return webbrowser.open(url)


def web_command(
    *,
    host: str,
    port: int,
    db: Path | None,
    no_browser: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
    run_server_fn: _UvicornRunFn | None = None,
    open_browser_fn: _BrowserOpenFn | None = None,
) -> None:
    """Serve the local HTTP API against a ``chronos.db`` and open a browser.

    The store is opened once (reusing ``open_store_fn`` so DB resolution is
    identical to every other subcommand), a fresh FastAPI app is built
    around it, and uvicorn blocks serving until the user presses Ctrl-C.

    Browser-open is best-effort and non-fatal: a failure prints a notice
    and falls through to serving normally, since the user can always
    copy the URL out of the banner.
    """
    # Defer imports that require optional deps so that bare ``chronos --help``
    # keeps working on a minimal install. The try/except catches an
    # ImportError for fastapi OR uvicorn (either on their own is enough to
    # fail ``chronos web``).
    try:
        from chronos.api import build_app
    except ImportError as exc:  # pragma: no cover — defensive, hard to hit in CI
        console.print(
            f"[red]error:[/] chronos web requires the [bold]web[/] extra.\n"
            f"Install with: [cyan]uv pip install 'chronos-agent[web]'[/] "
            f"(or [cyan]pip install 'chronos-agent[web]'[/]).\n"
            f"Underlying import error: {exc}"
        )
        raise typer.Exit(code=1) from exc

    run_server = run_server_fn if run_server_fn is not None else _default_run_server
    open_browser = open_browser_fn if open_browser_fn is not None else _default_open_browser

    # Banner BEFORE opening the store so a missing DB error stays readable
    # (the store opener prints its own error and exits code 2).
    # Resolve the DB path ourselves (not just trusting the ``--db`` CLI arg)
    # so the banner shows the same path that $CHRONOS_DB / default-cwd
    # fallback resolved to — otherwise users debugging a "wrong DB" confusion
    # would see ``None`` in the banner and have no idea what was actually opened.
    resolved_db = _resolve_db_path(db)
    store = open_store_fn(db)

    url = f"http://{host}:{port}"
    console.print()
    console.print(f"[bold green]chronos web[/] — serving {resolved_db}")
    console.print(f"  [cyan]{url}/[/]         landing page")
    console.print(f"  [cyan]{url}/runs[/]     list runs (JSON)")
    console.print(f"  [cyan]{url}/docs[/]     Swagger UI")
    console.print("  [dim]Ctrl-C to stop[/]")
    console.print()

    # Schedule the browser-open slightly after uvicorn.run() starts.
    # uvicorn.run() blocks, so if we called open_browser before it we'd
    # race the server coming up — the tab might load before the port is
    # listening. A 1-second Timer on a daemon thread is the simplest
    # cross-platform answer that doesn't require subclassing uvicorn.Server.
    if not no_browser:

        def _open_after_startup() -> None:
            try:
                ok = open_browser(url)
                if not ok:
                    # webbrowser.open returns False on some headless platforms.
                    # Keep it informational — the server is still useful.
                    console.print(
                        f"[yellow]note:[/] could not auto-open a browser; "
                        f"visit [cyan]{url}[/] manually."
                    )
            except Exception as exc:  # pragma: no cover — defensive
                console.print(f"[yellow]note:[/] browser open failed: {exc}")

        timer = threading.Timer(1.0, _open_after_startup)
        timer.daemon = True
        timer.start()

    # Build app and hand off to uvicorn. ``store`` is closed in the
    # ``finally`` so a uvicorn startup crash still releases the SQLite handle.
    try:
        app = build_app(store)
        run_server(
            app=app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
        )
    finally:
        with contextlib.suppress(Exception):
            store.close()
