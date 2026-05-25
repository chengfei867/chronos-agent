"""Chronos CLI — entry point and command registration.

v0.1 scope: read-only inspection of runs, nodes, and forks (`runs`, `forks
show`, `diff`, `replay`), plus `fork plan` which emits a portable plan
artifact consumed by user code (ADR-008). Write-side execution (`record`,
`fork run`) stays in adapter APIs.

Command surface::

    chronos --version
    chronos info
    chronos web [--host HOST] [--port N] [--db PATH] [--no-browser]
    chronos runs list [--db PATH] [--limit N] [--json] [--with-usage]
    chronos runs show <run_id> [--db PATH] [--json]
    chronos forks show <fork_id> [--db PATH] [--json]
    chronos diff <run_a> <run_b> [--db PATH] [--json] [--verbose] [--full]
        [--show-usage]
    chronos replay <run_id> [--db PATH] [--no-interactive]
    chronos fork plan <run_id> (--at-node N | --at-index K | --at-node-id ID)
        [--override k=v]... [--override-json JSON] [--child-thread-id T]
        [--reason R] [--tag T]... [--out PATH] [--json] [--allow-new-keys]
        [--db PATH]

All commands honour ``CHRONOS_DB`` env var as a fallback for ``--db``, and
default to ``./chronos.db`` if neither is set.

Module layout (R14 split):
- ``_common.py`` / ``_usage.py``  — shared helpers (DB open, serialise, usage)
- ``runs.py`` / ``forks.py`` / ``diff.py`` / ``replay.py`` / ``fork.py``
  — one implementation module per command group, each exposing a
  ``*_command(...)`` function called from the thin typer wrappers below.
"""

from __future__ import annotations

from pathlib import Path

import typer

from chronos import __version__
from chronos.cli._common import _open_store, console

app = typer.Typer(
    name="chronos",
    help="Time-travel debugger for multi-agent AI systems.",
    no_args_is_help=True,
    add_completion=False,
)

runs_app = typer.Typer(
    name="runs",
    help="Inspect recorded runs.",
    no_args_is_help=True,
)
forks_app = typer.Typer(
    name="forks",
    help="Inspect recorded forks (parent ↔ child lineage).",
    no_args_is_help=True,
)
fork_app = typer.Typer(
    name="fork",
    help="Plan a fork — emit a JSON artifact the user's code consumes.",
    no_args_is_help=True,
)
app.add_typer(runs_app, name="runs")
app.add_typer(forks_app, name="forks")
app.add_typer(fork_app, name="fork")


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"chronos {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Chronos Agent — record, replay, fork, and diff AI agent runs."""


@app.command()
def info() -> None:
    """Print environment diagnostics (version, phase, command surface).

    Use this first when triaging a chronos install — it reports the package
    version, the current phase / release line, and the list of available
    verbs. ``chronos doctor`` (R110) will layer health checks on top.

    Example::

        chronos info
    """
    console.print(f"[bold]chronos[/bold] {__version__}")
    console.print(
        "Status: Phase 5 Arc D complete (v0.9.0 R100-R106, golden-trace data contract + capture driver + verify-golden CLI + CI gate), "
        "Phase 6 RC kickoff (R107-R120 polish target: quickstart/doctor verbs, frontend P0 clearance, onboarding tour, bilingual README, docs site), "
        "adapter zero-regression streak R52->R107 = 55 rounds, "
        "v0.9.0"
    )
    console.print(
        "Commands: [green]runs list/show, forks show, diff, replay, fork plan, web, verify-golden[/green] "
        "available; [dim]record[/dim] [yellow](adapter-level only)[/yellow]"
    )


@app.command("web")
def web_cmd(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Bind address. Default is loopback — don't expose to a network.",
    ),
    port: int = typer.Option(
        8765,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="TCP port to serve on.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Don't auto-open a browser tab (useful on headless hosts or over SSH).",
    ),
) -> None:
    """Serve the local HTTP API and open the viewer in your browser.

    Starts a local FastAPI server (read-only, loopback-only) backed by your
    ``chronos.db`` and opens a browser tab at the landing page. From there
    you can hit ``/runs``, ``/runs/{id}/tree``, and ``/docs`` (Swagger UI).

    Install the ``[web]`` extra once: ``uv pip install 'chronos-agent[web]'``.

    Example::

        chronos web                    # default: 127.0.0.1:8765
        chronos web --port 9000        # custom port
        chronos web --no-browser       # don't auto-open a tab (SSH/headless)

    Exit codes:
      0 — server started cleanly (Ctrl-C to stop).
      1 — port already in use, or ``[web]`` extra not installed
          (hint: ``uv pip install 'chronos-agent[web]'``).
      2 — chronos.db missing or unreadable.
    """
    from chronos.cli.web import web_command

    web_command(
        host=host,
        port=port,
        db=db,
        no_browser=no_browser,
        open_store_fn=_open_store,
        console=console,
    )


@app.command("replay")
def replay_cmd(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    no_interactive: bool = typer.Option(
        False,
        "--no-interactive",
        help="Force static (non-TTY) rendering — useful for CI / piping / logs.",
    ),
) -> None:
    """Step through a recorded run node-by-node (interactive TUI).

    Keyboard controls: space/→ = next · ← = prev · home/end = first/last · q = quit.

    On a non-TTY stdin/stdout (CI, pipes, ``tee``) the command falls back
    to printing every node's detail view in order. Pass
    ``--no-interactive`` to force that fallback on a TTY too.

    Example::

        chronos replay 7c3f9e2a-...-a91         # interactive on a TTY
        chronos replay 7c3f9e2a --no-interactive   # static dump (CI / pipe)
        chronos replay 7c3f9e2a --db ./other.db    # explicit DB path

    Exit codes:
      0 — happy path (run replayed to completion or printed in full).
      1 — run id not found (hint: ``chronos runs list``).
      2 — chronos.db missing or unreadable.
    """
    from chronos.cli.replay import replay_command

    replay_command(
        run_id=run_id,
        db=db,
        no_interactive=no_interactive,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos runs`
# ---------------------------------------------------------------------------


@runs_app.command("list")
def runs_list(
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=10_000, help="Max rows to return."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    with_usage: bool = typer.Option(
        False,
        "--with-usage",
        help="Include summed tokens / cost columns. Extra SELECT per run — slower for large DBs.",
    ),
) -> None:
    """List recorded runs (most recent first).

    Example::

        chronos runs list                  # most recent 50 runs (default)
        chronos runs list -n 10            # last 10 runs only
        chronos runs list --json           # machine-readable
        chronos runs list --with-usage     # include token / cost columns

    Exit codes:
      0 — happy path (table or JSON printed; empty store prints empty table).
      2 — chronos.db missing or unreadable.
    """
    from chronos.cli.runs import runs_list_command

    runs_list_command(
        db=db,
        limit=limit,
        json_out=json_out,
        with_usage=with_usage,
        open_store_fn=_open_store,
        console=console,
    )


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a tree."),
) -> None:
    """Show one run, including its node tree.

    Renders the Run header (id, adapter, status, timing) plus an indented
    list of every Node (kind, name, state-after preview). Pass ``--json``
    for the machine-readable shape — the ``runs list`` row is a strict
    subset of this payload.

    Example::

        chronos runs show 7c3f9e2a-...-a91
        chronos runs show 7c3f9e2a --json | jq '.nodes | length'

    Exit codes:
      0 — happy path.
      1 — run id not found (hint: ``chronos runs list``).
      2 — chronos.db missing or unreadable.
    """
    from chronos.cli.runs import runs_show_command

    runs_show_command(
        run_id=run_id,
        db=db,
        json_out=json_out,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos forks`
# ---------------------------------------------------------------------------


@forks_app.command("show")
def forks_show(
    fork_id: str = typer.Argument(..., help="Fork id (see `chronos runs show`)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a tree."),
) -> None:
    """Show a fork: parent run + fork point + overrides + child run summary.

    Each fork record links a parent Run to a child Run via a Node id and
    a small set of state overrides. ``runs show`` already lists fork ids
    on the parent — use this verb to expand one of them.

    Example::

        chronos forks show 4ab1...c2d
        chronos forks show 4ab1c2d --json

    Exit codes:
      0 — happy path.
      1 — fork id not found (hint: ``chronos runs show <parent_run_id>`` lists forks).
      2 — chronos.db missing or unreadable.
    """
    from chronos.cli.forks import forks_show_command

    forks_show_command(
        fork_id=fork_id,
        db=db,
        json_out=json_out,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos tree`
# ---------------------------------------------------------------------------


@app.command("tree")
def tree(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    descendants: bool = typer.Option(
        False,
        "--descendants",
        help=(
            "Include every run that descends from this one via forks "
            "(the whole fork family, rooted at run_id)."
        ),
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit JSON (byte-for-byte the HTTP response shape)."
    ),
) -> None:
    """Show the fork-family tree rooted at a run (ADR-025).

    By default, walks upward to the run's root and prints every run that
    descends from that root via fork records. Pass ``--descendants`` to
    only show the family of runs that descend from the input run id (a
    sub-tree rooted at *this* run, not the family root).

    Example::

        chronos tree 7c3f9e2a                 # full family tree
        chronos tree 7c3f9e2a --descendants   # only this run's children/grand-children
        chronos tree 7c3f9e2a --json          # HTTP-equivalent JSON shape

    Exit codes:
      0 — happy path.
      1 — run id not found (hint: ``chronos runs list``).
      2 — chronos.db missing or unreadable.
    """
    from chronos.cli.tree import tree_command

    tree_command(
        run_id=run_id,
        db=db,
        descendants=descendants,
        json_out=json_out,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos diff`
# ---------------------------------------------------------------------------


@app.command()
def diff(
    run_a: str = typer.Argument(..., help="First run id (the 'A' side)."),
    run_b: str = typer.Argument(..., help="Second run id (the 'B' side)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show per-key state_after diffs inline."
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Compare entire runs even when B is a fork child of A. "
            "Default is to restrict to post-fork-point nodes (upstream is "
            "identical by construction)."
        ),
    ),
    show_usage: bool = typer.Option(
        False,
        "--show-usage",
        help="Include token/cost comparison between run A and run B (ADR-009).",
    ),
) -> None:
    """Compare two recorded runs side-by-side (the 'compare' verb — ADR-006 alignment).

    Renders a row-aligned table where each row is one logical step
    (model_call / tool_call / state_update / agent_end). When run B is a
    fork-child of run A, the shared prefix is hidden by default — pass
    ``--full`` to compare end-to-end. Pass ``--verbose`` to expand
    state_after deltas inline; ``--show-usage`` adds token / cost columns.

    Example::

        chronos diff 7c3f9e2a 9b1d8e4c
        chronos diff 7c3f9e2a 9b1d8e4c --full --verbose
        chronos diff 7c3f9e2a 9b1d8e4c --json | jq '.summary'
        chronos diff 7c3f9e2a 9b1d8e4c --show-usage

    Exit codes:
      0 — happy path (table or JSON printed, runs aligned).
      1 — either run id not found (hint: ``chronos runs list``).
      2 — chronos.db missing or unreadable.
    """
    from chronos.cli.diff import diff_command

    diff_command(
        run_a=run_a,
        run_b=run_b,
        db=db,
        json_out=json_out,
        verbose=verbose,
        full=full,
        show_usage=show_usage,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos compare` — N-run pivot-anchored diff (Phase 4 Arc A, R59)
# ---------------------------------------------------------------------------


@app.command("compare")
def compare_cmd(
    pivot_run_id: str = typer.Argument(
        ..., help="Pivot run id — the 'before' / reference run all others align against."
    ),
    other_run_ids: list[str] = typer.Argument(
        ...,
        help=(
            "One or more other run ids to compare against the pivot. "
            "Minimum 1 other; N > 8 prints a soft warning."
        ),
        show_default=False,
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit the merged alignment as JSON (stable contract — design doc §5.1).",
    ),
    restrict_to_downstream: bool = typer.Option(
        True,
        "--restrict-to-downstream/--full",
        "-R/-F",
        help=(
            "When an other run is a forked child of the pivot, skip the shared prefix. "
            "Default. Applied per (pivot, other) pair. Use --full for apples-to-apples."
        ),
    ),
    columns: str = typer.Option(
        "changed-or-added",
        "--columns",
        help="Which rows to render in text mode: all | changed | changed-or-added.",
    ),
    show_equal: bool = typer.Option(
        False,
        "--show-equal",
        help="In --columns=all text mode, also print rows where every column is equal.",
    ),
    width: int | None = typer.Option(
        None,
        "--width",
        help="Override terminal width for the rendered table (useful in narrow panes).",
    ),
    auto_pivot: bool = typer.Option(
        False,
        "--auto-pivot",
        help=(
            "Pick the pivot automatically via pairwise structural distance "
            "(Arc A slice 4, ADR-024). Under this flag, every positional is "
            "a candidate — no designated pivot. Tie-break: lexicographic run id."
        ),
    ),
    show_matrix: bool = typer.Option(
        False,
        "--show-matrix",
        help=(
            "With --auto-pivot, render the full pairwise distance matrix "
            "instead of the default first-3-rows snippet. No-op without "
            "--auto-pivot."
        ),
    ),
    matrix: bool = typer.Option(
        False,
        "--matrix",
        help=(
            "Emit only the pairwise distance matrix (Arc A slice 5, R65). "
            "All positionals are candidates; no pivot selection, no merged "
            "alignment. Cheaper than --auto-pivot when you only need to see "
            "how far apart N runs are. Mutually exclusive with --auto-pivot."
        ),
    ),
) -> None:
    """Compare N recorded runs against a pivot (fork-sweep debugger).

    First positional is the pivot; all other positionals are aligned
    against it. N=2 is numerically identical to ``chronos diff`` on
    the summary row. See ``docs/design/n-run-compare.md`` for the
    full spec.

    With ``--auto-pivot`` (ADR-024, Arc A slice 4), all positionals are
    treated as candidates and the pivot is selected by argmin mean
    structural distance (tie-break: lex smallest run id).

    With ``--matrix`` (Arc A slice 5, R65), all positionals are treated
    as candidates and only the pairwise distance matrix is printed — no
    centroid selection or merged alignment. Mutually exclusive with
    ``--auto-pivot``.

    Examples::

        chronos compare run_001 run_002                        # N=2
        chronos compare run_001 run_002 run_003 run_004        # N=4
        chronos compare run_001 run_002 run_003 --json         # JSON contract
        chronos compare run_001 run_002 --full                 # don't slice
        chronos compare --auto-pivot run_001 run_002 run_003   # auto-centroid
        chronos compare --matrix run_001 run_002 run_003       # matrix only

    Exit codes:
      0 — happy path (alignment table or JSON printed).
      1 — runtime "no such run" — at least one id wasn't found
          (hint: ``chronos runs list``).
      2 — input validation error: bad ``--columns`` value, mutually-
          exclusive flags, fewer than 2 candidate runs, or duplicate ids
          (the error message is actionable).
    """
    from chronos.cli.compare import compare_command

    compare_command(
        pivot_run_id=pivot_run_id,
        other_run_ids=list(other_run_ids),
        db=db,
        json_out=json_out,
        restrict_to_downstream=restrict_to_downstream,
        columns=columns,
        show_equal=show_equal,
        width=width,
        auto_pivot=auto_pivot,
        show_matrix=show_matrix,
        matrix=matrix,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos verify-golden` — golden-trace fixture verification (Phase 5 Arc D)
# ---------------------------------------------------------------------------


@app.command("verify-golden")
def verify_golden_cmd(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    golden_dir: Path = typer.Option(
        ...,
        "--golden-dir",
        help=(
            "Path to a `tests/golden/<adapter>/<scenario>/` directory containing "
            "`expected_run.json` + `envelopes.jsonl`."
        ),
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
) -> None:
    """Verify a recorded run matches an on-disk golden-trace fixture.

    Projects the run to its canonical RunSummary (via `chronos.golden`),
    compares byte-for-byte against `<golden-dir>/expected_run.json`, AND
    audits `<golden-dir>/envelopes.jsonl` for known-secret shapes at load
    time (belt + suspenders, ADR-028 §4).

    Exit codes:
      0 — happy path (byte-equal AND sanitiser-clean).
      1 — projection mismatch (unified diff printed).
      2 — missing fixture or unknown run id.
      3 — secret detected in envelopes.jsonl (re-record needed).
    """
    from chronos.cli.verify_golden import verify_golden_command

    code = verify_golden_command(
        db=db,
        run_id=run_id,
        golden_dir=golden_dir,
        open_store_fn=_open_store,
        console=console,
    )
    if code != 0:
        raise typer.Exit(code=code)


# ---------------------------------------------------------------------------
# `chronos fork plan` — emit fork plan artifact (ADR-008)
# ---------------------------------------------------------------------------


@fork_app.command("plan")
def fork_plan_cmd(
    run_id: str = typer.Argument(..., help="Parent run id (see `chronos runs list`)."),
    at_node: str | None = typer.Option(
        None, "--at-node", help="Fork at node with this name (errors if ambiguous)."
    ),
    at_index: int | None = typer.Option(
        None, "--at-index", help="Fork at this 0-based step index."
    ),
    at_node_id: str | None = typer.Option(
        None, "--at-node-id", help="Fork at the node with this exact id."
    ),
    overrides: list[str] = typer.Option(
        [],
        "--override",
        "-o",
        help="State override as key=value (value is JSON-parsed if possible). Repeatable.",
    ),
    overrides_json: list[str] = typer.Option(
        [],
        "--override-json",
        help="State overrides as a JSON object string; merged last, wins on collisions.",
    ),
    child_thread_id: str | None = typer.Option(
        None,
        "--child-thread-id",
        help="Override the auto-generated child thread id.",
    ),
    reason: str | None = typer.Option(
        None, "--reason", help="Human-readable reason stored on the fork record."
    ),
    tags: list[str] = typer.Option([], "--tag", help="Tag to attach to the child run. Repeatable."),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Path to write the plan JSON (default: ./fork_plan.json).",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit plan JSON to stdout instead of writing a file (no preview).",
    ),
    emit: str = typer.Option(
        "json",
        "--emit",
        help=(
            "Output format: 'json' (default, writes fork_plan.json) or "
            "'python' (writes a pastable fork_stub.py, ADR-013 alt C)."
        ),
    ),
    allow_new_keys: bool = typer.Option(
        False,
        "--allow-new-keys",
        help="Permit override keys that aren't already present in parent state_after.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
) -> None:
    """Emit a fork plan JSON artifact (see ADR-008).

    The CLI does not execute your graph. It resolves the fork point,
    validates overrides against the parent node's ``state_after``, and
    writes a small portable plan file. Consume it in your code::

        from chronos.fork_plan import load_plan
        plan = load_plan("fork_plan.json")
        with recorder.fork(graph, **plan.recorder_kwargs()) as ref:
            graph.invoke(None, {"configurable": {"thread_id": plan.child_thread_id}})

    Example::

        chronos fork plan <run_id> --at-node tool_call -o retries=3
        chronos fork plan <run_id> --at-index 4 --override-json '{"flag": true}'
        chronos fork plan <run_id> --at-node-id <node_id> --emit python --out fork.py
        chronos fork plan <run_id> --at-index 0 --json | jq .

    Exit codes:
      0 — happy path (plan written or printed).
      1 — fork point not found / ambiguous, override key missing in
          parent state_after (use ``--allow-new-keys`` if intentional).
      2 — chronos.db missing or unreadable, or unknown ``--emit`` value.
    """
    from chronos.cli.fork import fork_plan_command

    fork_plan_command(
        run_id=run_id,
        at_node=at_node,
        at_index=at_index,
        at_node_id=at_node_id,
        overrides=overrides,
        overrides_json=overrides_json,
        child_thread_id=child_thread_id,
        reason=reason,
        tags=tags,
        out=out,
        as_json=as_json,
        emit=emit,
        allow_new_keys=allow_new_keys,
        db=db,
        open_store_fn=_open_store,
        console=console,
    )


if __name__ == "__main__":
    app()
