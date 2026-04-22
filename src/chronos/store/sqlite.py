"""SQLite storage for Chronos traces.

This module is the canonical persistence layer. See
``docs/decisions/ADR-003-sqlite-schema.md`` for the full design.

Usage::

    store = SqliteStore.open("chronos.db")  # creates file + applies migrations
    run = Run(id=..., adapter="langgraph", adapter_thread_id="t1")
    store.put_run(run)
    store.put_node(Node(run_id=run.id, ...))
    all_nodes = store.get_nodes_for_run(run.id)
    store.close()

Or as a context manager::

    with SqliteStore.open("chronos.db") as store:
        ...

All methods are synchronous and thread-safe *enough* for v0.1 — they take a
short-lived cursor on each call. Heavy concurrent usage should wrap calls in
a transaction via ``store.transaction()``.

The store never stores LangGraph-native objects directly; adapters are
responsible for reshaping into :class:`Run` / :class:`Node` / :class:`Fork`
before calling ``put_*``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from chronos.core.models import (
    SCHEMA_VERSION,
    Fork,
    Node,
    NodeKind,
    Run,
    RunStatus,
    Usage,
)

# Directory (inside the package) containing forward-only SQL migrations.
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class SchemaError(RuntimeError):
    """Raised when a chronos.db schema_version is incompatible with this library."""


class SqliteStore:
    """Thin wrapper around ``sqlite3.Connection`` with Chronos semantics.

    Instances are NOT inherently thread-safe beyond SQLite's own guarantees
    (serialized mode by default). For concurrent writes, wrap calls in
    ``with store.transaction():``.
    """

    # -----------------------------------------------------------------
    # Construction / lifecycle
    # -----------------------------------------------------------------

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: str | Path) -> SqliteStore:
        """Open (or create) a chronos.db file and apply pending migrations.

        Args:
            path: Filesystem path, or ``":memory:"`` for an ephemeral DB.

        Returns:
            A ready-to-use ``SqliteStore``.

        Raises:
            SchemaError: If the existing DB was created by an incompatible
                future major version of Chronos.
        """
        conn = sqlite3.connect(
            str(path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # autocommit; we manage tx explicitly
        )
        conn.execute("PRAGMA foreign_keys = ON")
        store = cls(conn)
        store._apply_migrations()
        store._verify_schema_version()
        return store

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -----------------------------------------------------------------
    # Migrations
    # -----------------------------------------------------------------

    def _apply_migrations(self) -> None:
        """Run every ``NNN_*.sql`` file in migrations/ in numeric order.

        Each file is expected to be idempotent (``CREATE TABLE IF NOT EXISTS``,
        ``INSERT OR REPLACE`` for schema_info) so re-running is safe.
        """
        files = sorted(_MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
        for f in files:
            sql = f.read_text()
            self._conn.executescript(sql)

    def _verify_schema_version(self) -> None:
        """Ensure the DB's schema_version is readable by this library.

        Rule: library and DB must share the same MAJOR version. Minor/patch
        differences are assumed forward-compatible (we only add columns).
        """
        row = self._conn.execute("SELECT schema_version FROM schema_info WHERE id = 1").fetchone()
        if row is None:
            raise SchemaError("schema_info row missing — migrations did not run")
        db_ver = row["schema_version"]
        db_major = db_ver.split(".", 1)[0]
        lib_major = SCHEMA_VERSION.split(".", 1)[0]
        if db_major != lib_major:
            raise SchemaError(
                f"DB schema_version={db_ver!r} incompatible with library "
                f"SCHEMA_VERSION={SCHEMA_VERSION!r} (major mismatch). "
                "Open with an older Chronos or export-import."
            )

    @property
    def schema_version(self) -> str:
        row = self._conn.execute("SELECT schema_version FROM schema_info WHERE id = 1").fetchone()
        return str(row["schema_version"])

    # -----------------------------------------------------------------
    # Transactions
    # -----------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block inside a single BEGIN/COMMIT.

        Rolls back on exception. Use for multi-row writes that must be atomic
        (e.g., inserting a Fork + the child Run in one shot).
        """
        self._conn.execute("BEGIN")
        try:
            yield self._conn
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    # -----------------------------------------------------------------
    # Writes
    # -----------------------------------------------------------------

    def put_run(self, run: Run) -> None:
        """INSERT OR REPLACE a Run. ID-addressable (idempotent by id)."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                id, adapter, adapter_thread_id, status,
                started_at, ended_at, task_description,
                initial_state_json, final_state_json,
                tags_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.adapter,
                run.adapter_thread_id,
                run.status.value,
                _iso(run.started_at),
                _iso_or_none(run.ended_at),
                run.task_description,
                json.dumps(run.initial_state),
                json.dumps(run.final_state) if run.final_state is not None else None,
                json.dumps(run.tags),
                json.dumps(run.metadata),
            ),
        )

    def put_node(self, node: Node) -> None:
        """INSERT OR REPLACE a Node."""
        usage_json = json.dumps(node.usage.model_dump()) if node.usage is not None else None
        self._conn.execute(
            """
            INSERT OR REPLACE INTO nodes (
                id, run_id, step_index, node_name, kind, parent_node_id,
                started_at, ended_at, state_after_json,
                model_name, usage_json, cost_usd_cents,
                tool_name, tool_input_json, tool_output_json, error_message,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.run_id,
                node.step_index,
                node.node_name,
                node.kind.value,
                node.parent_node_id,
                _iso(node.started_at),
                _iso_or_none(node.ended_at),
                json.dumps(node.state_after),
                node.model_name,
                usage_json,
                node.cost_usd_cents,
                node.tool_name,
                json.dumps(node.tool_input) if node.tool_input is not None else None,
                json.dumps(node.tool_output) if node.tool_output is not None else None,
                node.error_message,
                json.dumps(node.metadata),
            ),
        )

    def put_fork(self, fork: Fork) -> None:
        """INSERT a Fork (append-only).

        Forks model historical causal events. UNIQUE on ``forks.child_run_id``
        means attempting to fork onto an already-forked child raises
        ``sqlite3.IntegrityError``. Callers who want idempotent retries should
        catch and check via :meth:`get_fork`.
        """
        self._conn.execute(
            """
            INSERT INTO forks (
                id, parent_run_id, parent_node_id, child_run_id,
                created_at, edited_fields_json, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fork.id,
                fork.parent_run_id,
                fork.parent_node_id,
                fork.child_run_id,
                _iso(fork.created_at),
                json.dumps(fork.edited_fields),
                fork.reason,
            ),
        )

    # -----------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------

    def get_run(self, run_id: str) -> Run | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self, *, limit: int = 100) -> list[Run]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_run(r) for r in rows]

    def get_node(self, node_id: str) -> Node | None:
        row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return _row_to_node(row) if row else None

    def get_nodes_for_run(self, run_id: str) -> list[Node]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE run_id = ? ORDER BY step_index ASC",
            (run_id,),
        ).fetchall()
        return [_row_to_node(r) for r in rows]

    def get_fork(self, fork_id: str) -> Fork | None:
        row = self._conn.execute("SELECT * FROM forks WHERE id = ?", (fork_id,)).fetchone()
        return _row_to_fork(row) if row else None

    def get_fork_for_child(self, child_run_id: str) -> Fork | None:
        row = self._conn.execute(
            "SELECT * FROM forks WHERE child_run_id = ?", (child_run_id,)
        ).fetchone()
        return _row_to_fork(row) if row else None


# -----------------------------------------------------------------
# Row → model helpers
# -----------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _iso_or_none(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _json_or_default(s: str | None, default: Any) -> Any:
    if s is None or s == "":
        return default
    return json.loads(s)


def _row_to_run(row: sqlite3.Row) -> Run:
    started = _parse_dt(row["started_at"])
    assert started is not None  # non-null in schema
    return Run(
        id=row["id"],
        adapter=row["adapter"],
        adapter_thread_id=row["adapter_thread_id"],
        status=RunStatus(row["status"]),
        started_at=started,
        ended_at=_parse_dt(row["ended_at"]),
        task_description=row["task_description"],
        initial_state=_json_or_default(row["initial_state_json"], {}),
        final_state=(
            json.loads(row["final_state_json"]) if row["final_state_json"] is not None else None
        ),
        tags=_json_or_default(row["tags_json"], []),
        metadata=_json_or_default(row["metadata_json"], {}),
    )


def _row_to_node(row: sqlite3.Row) -> Node:
    started = _parse_dt(row["started_at"])
    assert started is not None
    usage = None
    if row["usage_json"] is not None:
        usage = Usage(**json.loads(row["usage_json"]))
    return Node(
        id=row["id"],
        run_id=row["run_id"],
        step_index=row["step_index"],
        node_name=row["node_name"],
        kind=NodeKind(row["kind"]),
        parent_node_id=row["parent_node_id"],
        started_at=started,
        ended_at=_parse_dt(row["ended_at"]),
        state_after=_json_or_default(row["state_after_json"], {}),
        model_name=row["model_name"],
        usage=usage,
        cost_usd_cents=row["cost_usd_cents"],
        tool_name=row["tool_name"],
        tool_input=(
            json.loads(row["tool_input_json"]) if row["tool_input_json"] is not None else None
        ),
        tool_output=(
            json.loads(row["tool_output_json"]) if row["tool_output_json"] is not None else None
        ),
        error_message=row["error_message"],
        metadata=_json_or_default(row["metadata_json"], {}),
    )


def _row_to_fork(row: sqlite3.Row) -> Fork:
    created = _parse_dt(row["created_at"])
    assert created is not None
    return Fork(
        id=row["id"],
        parent_run_id=row["parent_run_id"],
        parent_node_id=row["parent_node_id"],
        child_run_id=row["child_run_id"],
        created_at=created,
        edited_fields=_json_or_default(row["edited_fields_json"], {}),
        reason=row["reason"],
    )


__all__ = ["SchemaError", "SqliteStore"]
