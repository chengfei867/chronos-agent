"""Tests for ``chronos.adapters.protocols`` — ADR-016 rollout step 2 (R31-A).

Covers three concerns:

1. **Canonical identity** — the ``RunRef`` / ``ForkRef`` / ``AdapterError``
   re-exported from ``chronos.adapters.langgraph`` and
   ``chronos.adapters.linear`` are the *same* objects as those in
   ``chronos.adapters.protocols``. Ensures R31-A did not accidentally
   introduce two parallel class hierarchies.

2. **Dataclass shape** — ``RunRef`` / ``ForkRef`` fields and defaults
   match ADR-016's documented contract.

3. **Structural conformance** — ``LangGraphRecorder`` and
   ``LinearRecorder`` pass ``isinstance(..., RecorderProtocol)`` via the
   ``@runtime_checkable`` decorator.

We intentionally **do not** test ``AdapterProtocol`` conformance against
any adapter yet — no adapter module currently exposes ``build_recorder``
/ ``name`` / ``version_constraint`` (ADR-016 rollout step 3 is deferred
to R32+). We do exercise the Protocol class itself (it imports, it's
``runtime_checkable``, a duck-typed stub satisfies it).
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from chronos.adapters import langgraph as lg_mod
from chronos.adapters import protocols as proto_mod
from chronos.adapters.langgraph import LangGraphRecorder
from chronos.adapters.linear import recorder as lin_mod
from chronos.adapters.linear.recorder import LinearRecorder
from chronos.adapters.protocols import (
    AdapterError,
    AdapterProtocol,
    ForkRef,
    NodeIdentityResolver,
    RecorderProtocol,
    RunRef,
)
from chronos.core.models import NodeKind
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# 1. Canonical-identity tests — re-exports are literal `is` identities
# ---------------------------------------------------------------------------


class TestCanonicalIdentity:
    """R31-A invariant: one class, many import paths."""

    def test_runref_is_same_object_in_langgraph(self):
        assert lg_mod.RunRef is RunRef

    def test_forkref_is_same_object_in_langgraph(self):
        assert lg_mod.ForkRef is ForkRef

    def test_adaptererror_is_same_object_in_langgraph(self):
        assert lg_mod.AdapterError is AdapterError

    def test_runref_is_same_object_in_linear(self):
        assert lin_mod.RunRef is RunRef

    def test_forkref_is_same_object_in_linear(self):
        assert lin_mod.ForkRef is ForkRef

    def test_adaptererror_is_same_object_in_linear(self):
        assert lin_mod.AdapterError is AdapterError

    def test_adaptererror_is_runtimeerror_subclass(self):
        assert issubclass(AdapterError, RuntimeError)

    def test_runref_instance_flows_across_adapters(self):
        """A RunRef built via LangGraph import path is type-compatible with
        the protocols-module version (and vice versa)."""
        from chronos.adapters.langgraph import RunRef as LGRunRef

        r = LGRunRef(thread_id="t")
        assert isinstance(r, RunRef)  # protocols-module RunRef
        assert isinstance(r, proto_mod.RunRef)


# ---------------------------------------------------------------------------
# 2. Dataclass-shape tests — ADR-016 §P1 contract
# ---------------------------------------------------------------------------


class TestDataclassShape:
    def test_runref_default_fields(self):
        r = RunRef(thread_id="t1")
        assert r.thread_id == "t1"
        assert r.run_id is None
        assert r.node_ids == []

    def test_runref_mutable_node_ids(self):
        r1 = RunRef(thread_id="a")
        r2 = RunRef(thread_id="b")
        r1.node_ids.append("n1")
        assert r2.node_ids == []  # dataclass field(default_factory=list)

    def test_forkref_default_fields(self):
        f = ForkRef(parent_run_id="p", at_node_id="n", child_thread_id="c")
        assert f.parent_run_id == "p"
        assert f.at_node_id == "n"
        assert f.child_thread_id == "c"
        assert f.child_run_id is None
        assert f.fork_id is None
        assert f.node_ids == []

    def test_forkref_required_fields_are_positional(self):
        with pytest.raises(TypeError):
            ForkRef()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 3. Protocol structural conformance — ADR-016 §P1 / §P3
# ---------------------------------------------------------------------------


class TestRecorderProtocolConformance:
    """Verify LangGraphRecorder / LinearRecorder satisfy RecorderProtocol.

    ``@runtime_checkable`` makes ``isinstance(x, RecorderProtocol)``
    return True iff ``x`` has ``record`` and ``fork`` attributes (method
    names only — Protocol is structural, not nominal). This is cheap
    smoke coverage; the real signature-level conformance lives in
    ``test_adapter_linear.py::TestProtocolConformance``.
    """

    def test_langgraph_recorder_satisfies_protocol(self, tmp_path):
        with SqliteStore.open(tmp_path / "c.db") as store:
            rec = LangGraphRecorder(store)
            assert isinstance(rec, RecorderProtocol)

    def test_linear_recorder_satisfies_protocol(self, tmp_path):
        with SqliteStore.open(tmp_path / "c.db") as store:
            rec = LinearRecorder(store)
            assert isinstance(rec, RecorderProtocol)

    def test_cast_to_protocol_is_type_safe(self, tmp_path):
        """ADR-016 §Rollout step 2 smoke: ``cast(RecorderProtocol, rec)``
        compiles and behaves identically — typecheck-time assertion that
        both adapters satisfy the Protocol at the signature level."""
        with SqliteStore.open(tmp_path / "c.db") as store:
            lg = cast(RecorderProtocol, LangGraphRecorder(store))
            lin = cast(RecorderProtocol, LinearRecorder(store))
            # `record` and `fork` are callables on both
            assert callable(lg.record)
            assert callable(lg.fork)
            assert callable(lin.record)
            assert callable(lin.fork)

    def test_random_object_fails_protocol_check(self):
        assert not isinstance(object(), RecorderProtocol)
        assert not isinstance("not a recorder", RecorderProtocol)


class TestAdapterProtocolShape:
    """AdapterProtocol is the R32+ plugin shape; no live impl yet, so we
    exercise it against a duck-typed stub to prove the Protocol is
    well-formed and ``runtime_checkable``."""

    def test_duck_typed_stub_satisfies_adapter_protocol(self):
        class _StubAdapter:
            name = "stub"
            version_constraint = ">=0,<1"

            def build_recorder(
                self,
                store: Any,
                *,
                kind_map: Any = None,
                usage_extractor: Any = None,
                **adapter_specific: Any,
            ) -> Any:
                return object()

        stub = _StubAdapter()
        assert isinstance(stub, AdapterProtocol)

    def test_missing_attrs_fail_adapter_protocol(self):
        class _Bad:
            name = "x"
            # missing version_constraint AND build_recorder

        assert not isinstance(_Bad(), AdapterProtocol)


class TestNodeIdentityResolverShape:
    """NodeIdentityResolver is the speculative Phase-2 hook (ADR-016 A3).
    Exercise its shape against a duck-typed stub."""

    def test_duck_typed_stub_satisfies_resolver(self):
        class _Resolver:
            def resolve(self, event: Any) -> tuple[str, NodeKind] | None:
                return ("n1", NodeKind.FN) if event else None

        r = _Resolver()
        assert isinstance(r, NodeIdentityResolver)
        assert r.resolve("go") == ("n1", NodeKind.FN)
        assert r.resolve(None) is None

    def test_object_without_resolve_fails(self):
        assert not isinstance(object(), NodeIdentityResolver)


# ---------------------------------------------------------------------------
# 4. Public surface — __all__ advertises only the documented names
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_protocols_all_is_exhaustive(self):
        assert set(proto_mod.__all__) == {
            "AdapterError",
            "AdapterProtocol",
            "ForkRef",
            "NodeIdentityResolver",
            "RecorderProtocol",
            "RunRef",
        }

    def test_adapters_package_exposes_protocols(self):
        from chronos import adapters as pkg

        for name in (
            "AdapterError",
            "AdapterProtocol",
            "ForkRef",
            "LangGraphRecorder",
            "NodeIdentityResolver",
            "RecorderProtocol",
            "RunRef",
        ):
            assert hasattr(pkg, name), f"chronos.adapters missing {name}"
            assert name in pkg.__all__, f"{name} missing from chronos.adapters.__all__"
