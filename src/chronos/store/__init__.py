"""Chronos persistence layer.

Public API:
    SqliteStore — the canonical on-disk store (see sqlite.py)
    SchemaError — raised on incompatible chronos.db files
"""

from chronos.store.sqlite import SchemaError, SqliteStore

__all__ = ["SchemaError", "SqliteStore"]
