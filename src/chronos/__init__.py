"""Chronos Agent — time-travel debugger for multi-agent AI systems.

Record, replay, fork, and diff reasoning trees of AI agents to find
cost regressions, counterfactual-test prompt changes, and understand
what happened inside a multi-agent run.

Public API: v0.1.x series is stable for the four-verb CLI loop
(record/replay/fork plan/diff) and the `ForkPlan` JSON schema v1.
"""

__version__ = "0.1.5"

__all__ = ["__version__"]
