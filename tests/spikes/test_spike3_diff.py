"""Spike 3 — Structural diff between two runs.

Proves: given two runs (original + forked) captured via checkpointer, we can
compute a structured diff that tells a human:
  - which nodes produced different outputs
  - which nodes were skipped / added
  - first divergence point (the "fork" moment)
  - simple stats (count of divergent fields)

Exit criterion: diff function works on Spike 2's outputs, identifies
'research' as the first divergence, and reports downstream nodes
(draft/review/finalize) as also divergent.

This is the core algorithm behind the future `chronos diff` CLI command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from tests.spikes.test_spike1_capture import AgentState, build_graph

# --- Diff data model -------------------------------------------------------


@dataclass(frozen=True)
class FieldDiff:
    """A single field that differs between two state snapshots."""

    field_name: str
    value_a: Any
    value_b: Any

    def __str__(self) -> str:
        a = repr(self.value_a)[:60]
        b = repr(self.value_b)[:60]
        return f"  {self.field_name}: {a} → {b}"


@dataclass
class StepDiff:
    """Diff for a single step (1-per-node)."""

    step: int
    next_node: tuple[str, ...]
    field_diffs: list[FieldDiff] = field(default_factory=list)

    @property
    def diverged(self) -> bool:
        return bool(self.field_diffs)


@dataclass
class RunDiff:
    """Full structured diff of two runs.

    Invariant: steps are aligned by index. If one run has more steps,
    the overflow is reported separately.
    """

    step_diffs: list[StepDiff] = field(default_factory=list)
    only_in_a_steps: list[int] = field(default_factory=list)
    only_in_b_steps: list[int] = field(default_factory=list)

    @property
    def first_divergence_step(self) -> int | None:
        """Step number at which the two runs first diverge, or None if identical."""
        for sd in self.step_diffs:
            if sd.diverged:
                return sd.step
        if self.only_in_a_steps or self.only_in_b_steps:
            return min(self.only_in_a_steps + self.only_in_b_steps)
        return None

    @property
    def is_identical(self) -> bool:
        return self.first_divergence_step is None

    def summary(self) -> str:
        lines = []
        if self.is_identical:
            lines.append("🟢 Runs are IDENTICAL")
            return "\n".join(lines)
        lines.append(f"🟡 First divergence at step {self.first_divergence_step}")
        for sd in self.step_diffs:
            if sd.diverged:
                lines.append(
                    f"Step {sd.step} (next={sd.next_node}) — {len(sd.field_diffs)} field(s) differ:"
                )
                for fd in sd.field_diffs:
                    lines.append(str(fd))
        if self.only_in_a_steps:
            lines.append(f"Steps only in A: {self.only_in_a_steps}")
        if self.only_in_b_steps:
            lines.append(f"Steps only in B: {self.only_in_b_steps}")
        return "\n".join(lines)


# --- Diff algorithm --------------------------------------------------------


def _collect_post_input_snaps(graph: CompiledStateGraph, config: dict) -> list:
    """Return snapshots with step>=0, ordered oldest→newest."""
    history = list(graph.get_state_history(config))
    post = [s for s in history if s.metadata.get("step", -999) >= 0]
    # get_state_history returns newest first; we want chronological order
    return list(reversed(post))


def diff_runs(
    graph: CompiledStateGraph,
    config_a: dict,
    config_b: dict,
    *,
    ignore_fields: set[str] | None = None,
) -> RunDiff:
    """Compute a structured diff of two checkpointed runs.

    Args:
        graph: compiled graph whose checkpointer holds both runs
        config_a: {"configurable": {"thread_id": ...}} for run A
        config_b: same for run B
        ignore_fields: state fields to exclude from comparison (e.g., 'log')

    Returns:
        RunDiff with step-by-step alignment.
    """
    ignore = ignore_fields or set()
    snaps_a = _collect_post_input_snaps(graph, config_a)
    snaps_b = _collect_post_input_snaps(graph, config_b)

    result = RunDiff()
    n = min(len(snaps_a), len(snaps_b))

    for i in range(n):
        sa, sb = snaps_a[i], snaps_b[i]
        step = sa.metadata.get("step", i)
        sd = StepDiff(step=step, next_node=tuple(sa.next))
        all_fields = set(sa.values.keys()) | set(sb.values.keys())
        for f in sorted(all_fields - ignore):
            va = sa.values.get(f)
            vb = sb.values.get(f)
            if va != vb:
                sd.field_diffs.append(FieldDiff(field_name=f, value_a=va, value_b=vb))
        result.step_diffs.append(sd)

    # Overflow
    for i in range(n, len(snaps_a)):
        result.only_in_a_steps.append(snaps_a[i].metadata.get("step", i))
    for i in range(n, len(snaps_b)):
        result.only_in_b_steps.append(snaps_b[i].metadata.get("step", i))

    return result


# --- Tests -----------------------------------------------------------------


@pytest.mark.spike
def test_spike3_diff_identical_runs() -> None:
    """Two runs with the same input should produce zero diffs."""
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)
    initial: AgentState = {
        "task": "identical",
        "plan": "",
        "research": "",
        "draft": "",
        "review": "",
        "final": "",
        "log": [],
    }

    config_a = {"configurable": {"thread_id": "spike3-id-a"}}
    config_b = {"configurable": {"thread_id": "spike3-id-b"}}
    graph.invoke(initial, config_a)
    graph.invoke(initial, config_b)

    diff = diff_runs(graph, config_a, config_b)
    assert diff.is_identical, f"identical runs should have no diff, but got:\n{diff.summary()}"
    print(f"\n✅ Spike 3a PASS — {diff.summary()}")


@pytest.mark.spike
def test_spike3_diff_forked_runs() -> None:
    """A fork at 'research' should produce: step 0 identical, step 1+ divergent."""
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)
    initial: AgentState = {
        "task": "Compose a tweet.",
        "plan": "",
        "research": "",
        "draft": "",
        "review": "",
        "final": "",
        "log": [],
    }

    # Run A — full normal execution
    config_a = {"configurable": {"thread_id": "spike3-fork-a"}}
    graph.invoke(initial, config_a)

    # Run B — fork after 'research' with modified research
    hist_a = list(graph.get_state_history(config_a))
    fork_snap = next(s for s in hist_a if s.next == ("draft",))
    config_b = {"configurable": {"thread_id": "spike3-fork-b"}}
    forked = dict(fork_snap.values)
    forked["research"] = "[HIJACKED-DIFF-TEST]"
    graph.update_state(config_b, forked, as_node="research")
    graph.invoke(None, config_b)

    # Ignore 'log' field for cleaner diff — it intentionally differs due to FORK marker
    diff = diff_runs(graph, config_a, config_b, ignore_fields={"log"})

    assert not diff.is_identical, "forked runs must differ"

    # The first divergence should be on the 'research' field — since fake_llm is
    # deterministic, plan is identical in both A and B (same task → same plan).
    first_div = diff.first_divergence_step
    assert first_div is not None
    print(f"\n--- Diff summary ---\n{diff.summary()}\n--------------------")

    # Find the divergent step that contains 'research' field diff
    research_div_step = next(
        (sd for sd in diff.step_diffs if any(fd.field_name == "research" for fd in sd.field_diffs)),
        None,
    )
    assert research_div_step is not None, "expected 'research' field to appear in diff"

    # Downstream fields (draft, review, final) must all diverge too
    late_step = diff.step_diffs[-1]  # last aligned step (post-finalize)
    divergent_fields = {fd.field_name for fd in late_step.field_diffs}
    assert "research" in divergent_fields
    assert "draft" in divergent_fields
    assert "review" in divergent_fields
    assert "final" in divergent_fields

    print("✅ Spike 3b PASS — fork correctly identified")
    print(f"   divergent fields at final step: {sorted(divergent_fields)}")


@pytest.mark.spike
def test_spike3_diff_summary_is_human_readable() -> None:
    """The diff.summary() should render something useful for a CLI."""
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)
    initial: AgentState = {
        "task": "X",
        "plan": "",
        "research": "",
        "draft": "",
        "review": "",
        "final": "",
        "log": [],
    }

    config_a = {"configurable": {"thread_id": "spike3-hr-a"}}
    config_b = {"configurable": {"thread_id": "spike3-hr-b"}}
    graph.invoke(initial, config_a)

    hist_a = list(graph.get_state_history(config_a))
    fork_snap = next(s for s in hist_a if s.next == ("draft",))
    forked = dict(fork_snap.values)
    forked["research"] = "[different]"
    graph.update_state(config_b, forked, as_node="research")
    graph.invoke(None, config_b)

    summary = diff_runs(graph, config_a, config_b, ignore_fields={"log"}).summary()
    assert "First divergence" in summary
    assert "research" in summary
    assert "→" in summary  # field-level arrow
    print(f"\n✅ Spike 3c PASS — summary renderable:\n{summary}")
