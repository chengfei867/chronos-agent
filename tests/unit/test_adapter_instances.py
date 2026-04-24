"""Tests for R32-B module-level :class:`AdapterProtocol` instances.

Covers:
  * ``langgraph_adapter`` / ``linear_adapter`` satisfy ``AdapterProtocol``.
  * ``build_recorder()`` returns a ``RecorderProtocol``-conformant object.
  * Metadata (``name`` / ``version_constraint``) is the documented value.
  * Error channels:
      - LangGraph rejects unknown ``**adapter_specific`` kwargs.
      - Linear rejects ``kind_map`` / ``usage_extractor`` / unknown
        ``**adapter_specific`` kwargs.
      - Linear accepts the documented ``adapter_name`` kwarg.
  * Top-level ``chronos.adapters`` package re-exports both instances.
"""

from __future__ import annotations

import pytest

import chronos.adapters as ca
from chronos.adapters import (
    AdapterError,
    AdapterProtocol,
    LangGraphRecorder,
    LinearRecorder,
    RecorderProtocol,
    langgraph_adapter,
    linear_adapter,
)
from chronos.store import SqliteStore


@pytest.fixture()
def store(tmp_path):
    """Fresh, empty SqliteStore in a temp file."""
    with SqliteStore.open(tmp_path / "r32b.db") as s:
        yield s


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_langgraph_adapter_name(self) -> None:
        assert langgraph_adapter.name == "langgraph"

    def test_langgraph_adapter_version_constraint(self) -> None:
        assert langgraph_adapter.version_constraint == ">=1.1,<2"

    def test_linear_adapter_name(self) -> None:
        assert linear_adapter.name == "linear"

    def test_linear_adapter_version_constraint_is_empty(self) -> None:
        # Zero-dep adapter — ADR-016 P2 allows empty version_constraint.
        assert linear_adapter.version_constraint == ""


# ---------------------------------------------------------------------------
# Protocol conformance (AdapterProtocol)
# ---------------------------------------------------------------------------


class TestAdapterProtocolConformance:
    def test_langgraph_adapter_isinstance(self) -> None:
        assert isinstance(langgraph_adapter, AdapterProtocol)

    def test_linear_adapter_isinstance(self) -> None:
        assert isinstance(linear_adapter, AdapterProtocol)

    def test_build_recorder_returns_recorder_protocol_langgraph(self, store: SqliteStore) -> None:
        rec = langgraph_adapter.build_recorder(store)
        assert isinstance(rec, LangGraphRecorder)
        assert isinstance(rec, RecorderProtocol)

    def test_build_recorder_returns_recorder_protocol_linear(self, store: SqliteStore) -> None:
        rec = linear_adapter.build_recorder(store)
        assert isinstance(rec, LinearRecorder)
        assert isinstance(rec, RecorderProtocol)


# ---------------------------------------------------------------------------
# LangGraph build_recorder behaviour
# ---------------------------------------------------------------------------


class TestLangGraphBuildRecorder:
    def test_forwards_kind_map(self, store: SqliteStore) -> None:
        from chronos.core.models import NodeKind

        kmap = {"llm_step": NodeKind.LLM}
        rec = langgraph_adapter.build_recorder(store, kind_map=kmap)
        assert rec._kind_map == kmap

    def test_forwards_usage_extractor(self, store: SqliteStore) -> None:
        def noop_extractor(ctx):  # type: ignore[no-untyped-def]
            return None

        rec = langgraph_adapter.build_recorder(store, usage_extractor=noop_extractor)
        assert rec._usage_extractor is noop_extractor

    def test_rejects_unknown_adapter_specific(self, store: SqliteStore) -> None:
        with pytest.raises(AdapterError, match="does not accept"):
            langgraph_adapter.build_recorder(store, some_unknown_kwarg=42)

    def test_default_kwargs_build_a_recorder(self, store: SqliteStore) -> None:
        rec = langgraph_adapter.build_recorder(store)
        assert rec._kind_map == {}
        assert rec._usage_extractor is None


# ---------------------------------------------------------------------------
# Linear build_recorder behaviour
# ---------------------------------------------------------------------------


class TestLinearBuildRecorder:
    def test_default(self, store: SqliteStore) -> None:
        rec = linear_adapter.build_recorder(store)
        assert rec._adapter_name == "linear"

    def test_accepts_adapter_name(self, store: SqliteStore) -> None:
        rec = linear_adapter.build_recorder(store, adapter_name="linear-alt")
        assert rec._adapter_name == "linear-alt"

    def test_rejects_kind_map(self, store: SqliteStore) -> None:
        with pytest.raises(AdapterError, match="kind_map is carried on LinearRuntime"):
            linear_adapter.build_recorder(store, kind_map={})

    def test_rejects_usage_extractor(self, store: SqliteStore) -> None:
        def extractor(ctx):  # type: ignore[no-untyped-def]
            return None

        with pytest.raises(AdapterError, match="__chronos_usage__"):
            linear_adapter.build_recorder(store, usage_extractor=extractor)

    def test_rejects_unknown_adapter_specific(self, store: SqliteStore) -> None:
        with pytest.raises(AdapterError, match="unknown adapter-specific"):
            linear_adapter.build_recorder(store, unknown_knob="oops")


# ---------------------------------------------------------------------------
# Package-level exports
# ---------------------------------------------------------------------------


class TestTopLevelExports:
    def test_langgraph_adapter_in_package_namespace(self) -> None:
        assert ca.langgraph_adapter is langgraph_adapter

    def test_linear_adapter_in_package_namespace(self) -> None:
        assert ca.linear_adapter is linear_adapter

    def test_both_instances_in_all(self) -> None:
        assert "langgraph_adapter" in ca.__all__
        assert "linear_adapter" in ca.__all__

    def test_roster(self) -> None:
        """The two shipping adapters can be enumerated uniformly."""
        adapters = [ca.langgraph_adapter, ca.linear_adapter]
        names = {a.name for a in adapters}
        assert names == {"langgraph", "linear"}
        for a in adapters:
            assert isinstance(a, AdapterProtocol)
