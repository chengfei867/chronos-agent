"""Top-level pytest conftest.

Hosts test-wide autouse fixtures.

Autouse fixtures:

- `_strip_color_env`: neutralise shell color env vars and replace the
  module-level `chronos.cli._common.console` with a no-color, non-tty
  `Console`, so tests that assert on CLI stdout substrings pass
  regardless of the developer's shell configuration.

Rationale (R24, Finding #1 from v0.1.6 demo report):

Five CLI tests use `CliRunner` from `click.testing` and assert on
substrings of `result.stdout`:

- `tests/unit/test_cli.py::test_diff_help_surfaces`
- `tests/unit/test_cli.py::test_runs_help_surfaces`
- `tests/unit/test_cli.py::test_replay_help_surfaces`
- `tests/unit/test_fork_cli.py::test_cli_fork_plan_json_to_stdout`
- `tests/unit/test_fork_cli.py::test_cli_fork_plan_emit_python_writes_valid_stub`

When the developer's shell exports `FORCE_COLOR=1` (common for
terminal-capture workflows, e.g. generating demo screenshots via
ANSI-to-PNG pipelines), `rich` — which powers Typer `--help` output and
`Console.print_json` — emits ANSI escape sequences. ANSI codes
interleave with text across line wraps and break naive `substring in
stdout` matching.

Two layers are at play:

1. **Env-var layer.** `FORCE_COLOR`, `NO_COLOR`, `CLICOLOR`,
   `CLICOLOR_FORCE`, `PY_COLORS`, `TERM`. `rich.Console()` reads these
   at construction time.
2. **Already-constructed Console.** `chronos.cli._common.console` is
   instantiated at module import, **before** pytest fixtures run. Just
   delenv-ing the shell vars is too late — the Console's
   `_force_terminal`/`no_color` have already been decided from the
   host's environment.

Fix is two-step: clear the env vars for any Console constructed during
the test, **and** rebind `chronos.cli._common.console` to a freshly
built Console that explicitly disables color. Use `monkeypatch.setattr`
so the real module-level Console is restored after the test — normal
user CLI invocations retain their colors.

This is not a CLI bug; it's an env-sensitivity in the test harness,
fixed once at harness level.
"""

from __future__ import annotations

import pytest
from rich.console import Console

_COLOR_ENV_VARS = (
    "FORCE_COLOR",
    "NO_COLOR",
    "CLICOLOR",
    "CLICOLOR_FORCE",
    "PY_COLORS",
)


@pytest.fixture(autouse=True)
def _strip_color_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise all color sources for every test.

    1. Delete shell color env vars so any Console built during the test
       won't emit ANSI.
    2. Set TERM=dumb and COLUMNS=80 so `rich` picks a plain, fixed-width
       renderer.
    3. Rebind the module-level `chronos.cli._common.console` (already
       constructed at import time) to a fresh Console configured to
       never emit ANSI and never wrap oddly.

    Restoration is automatic via pytest's `monkeypatch`.
    """
    for var in _COLOR_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "80")

    # Rebind every module that re-exports the same Console instance.
    # `chronos.cli._common` creates the Console at import time; the
    # Typer app in `chronos.cli.__init__` does `from chronos.cli._common
    # import console`, which copies the reference into a second module
    # namespace. Both bindings must be patched.
    #
    # Import inside the fixture so collection never fails on import order.
    from chronos import cli as _cli_pkg
    from chronos.cli import _common as _cli_common

    plain_console = Console(
        force_terminal=False,
        no_color=True,
        color_system=None,
        width=80,
        highlight=False,
    )
    monkeypatch.setattr(_cli_common, "console", plain_console, raising=True)
    monkeypatch.setattr(_cli_pkg, "console", plain_console, raising=True)
