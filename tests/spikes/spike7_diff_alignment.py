"""Spike 7 — diff alignment algorithm validation (M1.8 / ADR-006).

Purpose
-------
Before writing the production ``chronos.core.diff`` module, prove that
``difflib.SequenceMatcher`` over the **node_name sequence** of two runs
produces a sane alignment for the two canonical cases Chronos cares
about:

1. *Parent vs child-of-fork* — child's ``step_index`` continues from the
   fork point, so naive step_index alignment fails. Names still line up
   (child replays the same downstream node names after the fork point,
   possibly diverging in state).
2. *Parent vs child-of-fork with early-exit* — overrides cause the child
   to take a different branch and end earlier. Diff must report
   *REMOVED* nodes for the missing tail, not attempt to pair them.

Also: cycles / repeated node_names within a single run — LangGraph lets
the same node name execute multiple times (think router → worker →
router → worker). The alignment must pair repeats by **order of
occurrence**, not conflate them.

This spike is a live script (not pytest). Run with::

    uv run python tests/spikes/spike7_diff_alignment.py

Findings (to fold into ADR-006 on success)
-------------------------------------------
- SequenceMatcher opcodes ``equal`` / ``replace`` / ``delete`` /
  ``insert`` map cleanly to Chronos diff categories.
- No need for a custom Myers implementation; stdlib is enough.
- ``step_index`` is **never** used for alignment; it's only a
  display-order field.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class FakeNode:
    step_index: int
    node_name: str
    state_after: dict


def align(
    a: list[FakeNode], b: list[FakeNode]
) -> list[tuple[str, FakeNode | None, FakeNode | None]]:
    """Return a list of (tag, node_a, node_b) tuples.

    tag ∈ {"equal", "changed", "removed", "added"}.
    """
    names_a = [n.node_name for n in a]
    names_b = [n.node_name for n in b]
    sm = difflib.SequenceMatcher(a=names_a, b=names_b, autojunk=False)
    out: list[tuple[str, FakeNode | None, FakeNode | None]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                na, nb = a[i1 + k], b[j1 + k]
                tag = "equal" if na.state_after == nb.state_after else "changed"
                out.append((tag, na, nb))
        elif op == "replace":
            # treat replace as removes + adds — simpler than trying to
            # pair them heuristically; UI can render them together
            for k in range(i1, i2):
                out.append(("removed", a[k], None))
            for k in range(j1, j2):
                out.append(("added", None, b[k]))
        elif op == "delete":
            for k in range(i1, i2):
                out.append(("removed", a[k], None))
        elif op == "insert":
            for k in range(j1, j2):
                out.append(("added", None, b[k]))
    return out


def summary(tags: list[tuple[str, FakeNode | None, FakeNode | None]]) -> dict[str, int]:
    s = {"equal": 0, "changed": 0, "added": 0, "removed": 0}
    for t, _a, _b in tags:
        s[t] += 1
    return s


def case1_parent_vs_fork_child() -> None:
    """5-node parent (spike1 shape); child forks at node 2, re-runs 2..4."""
    parent = [
        FakeNode(0, "ingest", {"input": "X"}),
        FakeNode(1, "research", {"facts": ["a", "b"]}),
        FakeNode(2, "draft", {"draft": "original"}),
        FakeNode(3, "polish", {"final": "pretty original"}),
        FakeNode(4, "end", {"final": "pretty original"}),
    ]
    # child_of_fork: fork at "research", override facts → re-run draft/polish/end
    # step_index continues from fork point → 1,2,3,4 (not 0,1,2,3)
    child = [
        FakeNode(1, "research", {"facts": ["a", "b", "c"]}),  # injected override
        FakeNode(2, "draft", {"draft": "alt draft with fact c"}),
        FakeNode(3, "polish", {"final": "pretty alt"}),
        FakeNode(4, "end", {"final": "pretty alt"}),
    ]
    tags = align(parent, child)
    print("=== Case 1: parent vs fork child (common tail) ===")
    for t, a, b in tags:
        aid = f"{a.step_index}:{a.node_name}" if a else "—"
        bid = f"{b.step_index}:{b.node_name}" if b else "—"
        print(f"  [{t:7}] parent={aid:20}  child={bid}")
    s = summary(tags)
    print(f"  summary: {s}")
    # Expectations: ingest REMOVED (only in parent), research CHANGED
    # (facts differ), draft CHANGED, polish CHANGED, end CHANGED
    assert s == {"equal": 0, "changed": 4, "added": 0, "removed": 1}, s
    print("  OK\n")


def case2_early_exit_fork() -> None:
    """Override causes child to exit earlier than parent."""
    parent = [
        FakeNode(0, "ingest", {"x": 1}),
        FakeNode(1, "research", {"x": 2}),
        FakeNode(2, "draft", {"x": 3}),
        FakeNode(3, "polish", {"x": 4}),
        FakeNode(4, "end", {"x": 5}),
    ]
    # child bails out after draft (overrides caused router to decide
    # "good enough, skip polish, go to end")
    child = [
        FakeNode(2, "draft", {"x": 999}),
        FakeNode(3, "end", {"x": 1000}),
    ]
    tags = align(parent, child)
    print("=== Case 2: fork child with early exit ===")
    for t, a, b in tags:
        aid = f"{a.step_index}:{a.node_name}" if a else "—"
        bid = f"{b.step_index}:{b.node_name}" if b else "—"
        print(f"  [{t:7}] parent={aid:20}  child={bid}")
    s = summary(tags)
    print(f"  summary: {s}")
    # ingest REMOVED, research REMOVED, draft CHANGED, polish REMOVED,
    # end CHANGED — equal 0
    assert s["changed"] == 2
    assert s["removed"] == 3
    assert s["added"] == 0
    print("  OK\n")


def case3_cycle_repeated_node_names() -> None:
    """router → worker → router → worker pattern (LangGraph loops)."""
    run_a = [
        FakeNode(0, "start", {"n": 0}),
        FakeNode(1, "router", {"decision": "work"}),
        FakeNode(2, "worker", {"n": 1}),
        FakeNode(3, "router", {"decision": "work"}),
        FakeNode(4, "worker", {"n": 2}),
        FakeNode(5, "router", {"decision": "stop"}),
        FakeNode(6, "end", {"n": 2}),
    ]
    # run_b: same structure but worker produced different values and
    # took ONE extra loop iteration
    run_b = [
        FakeNode(0, "start", {"n": 0}),
        FakeNode(1, "router", {"decision": "work"}),
        FakeNode(2, "worker", {"n": 10}),
        FakeNode(3, "router", {"decision": "work"}),
        FakeNode(4, "worker", {"n": 20}),
        FakeNode(5, "router", {"decision": "work"}),
        FakeNode(6, "worker", {"n": 30}),
        FakeNode(7, "router", {"decision": "stop"}),
        FakeNode(8, "end", {"n": 30}),
    ]
    tags = align(run_a, run_b)
    print("=== Case 3: cycles with repeated names ===")
    for t, a, b in tags:
        aid = f"{a.step_index}:{a.node_name}" if a else "—"
        bid = f"{b.step_index}:{b.node_name}" if b else "—"
        print(f"  [{t:7}] parent={aid:20}  child={bid}")
    s = summary(tags)
    print(f"  summary: {s}")
    # SequenceMatcher should align start/router/worker/router/worker/
    # router... pairs — 2 extra (router, worker) inserted in run_b
    assert s["added"] == 2, s
    assert s["removed"] == 0, s
    print("  OK\n")


def case4_identical_runs() -> None:
    """Sanity: two identical runs → all equal, no changes."""
    a = [
        FakeNode(0, "ingest", {"x": 1}),
        FakeNode(1, "draft", {"x": 2}),
        FakeNode(2, "end", {"x": 3}),
    ]
    b = [FakeNode(n.step_index, n.node_name, dict(n.state_after)) for n in a]
    tags = align(a, b)
    s = summary(tags)
    print("=== Case 4: identical runs ===")
    print(f"  summary: {s}")
    assert s == {"equal": 3, "changed": 0, "added": 0, "removed": 0}
    print("  OK\n")


def case5_step_index_naive_would_fail() -> None:
    """Explicitly demonstrate why step_index alignment is wrong.

    If we paired parent[i].step_index with child[j].step_index we'd
    compare parent's step 2 (draft) against child's step 2 (draft) —
    that actually happens to match, but it's a lucky coincidence.
    Rename the parent's node 0 to 'prelude' so step_index alignment
    would pair 'prelude' with 'research' — clearly wrong.
    """
    parent = [
        FakeNode(0, "prelude", {"x": 0}),
        FakeNode(1, "ingest", {"x": 1}),
        FakeNode(2, "draft", {"x": 2}),
        FakeNode(3, "end", {"x": 3}),
    ]
    child = [
        FakeNode(2, "draft", {"x": 999}),
        FakeNode(3, "end", {"x": 999}),
    ]
    tags = align(parent, child)
    print("=== Case 5: step_index naive would misalign ===")
    for t, a, b in tags:
        aid = f"{a.step_index}:{a.node_name}" if a else "—"
        bid = f"{b.step_index}:{b.node_name}" if b else "—"
        print(f"  [{t:7}] parent={aid:20}  child={bid}")
    # name-based alignment: prelude REMOVED, ingest REMOVED, draft
    # CHANGED, end CHANGED
    # naive step_index alignment would have paired prelude[0] with
    # child[2] (draft) — total garbage.
    s = summary(tags)
    assert s == {"equal": 0, "changed": 2, "added": 0, "removed": 2}
    print(f"  summary: {s}")
    print("  OK\n")


if __name__ == "__main__":
    case1_parent_vs_fork_child()
    case2_early_exit_fork()
    case3_cycle_repeated_node_names()
    case4_identical_runs()
    case5_step_index_naive_would_fail()
    print(
        "spike7: all 5 cases passed — SequenceMatcher over node_name "
        "sequence is the alignment primitive for ADR-006."
    )
