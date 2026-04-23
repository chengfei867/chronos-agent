"""Deterministic FakeLLM used by the examples.

No external API key is needed to run any Chronos example — the
``FakeLLM`` below is a pure function of ``(system_prompt, user_prompt,
seed)`` so runs are 100% reproducible. This lets the examples focus
on Chronos's record/fork/diff mechanics instead of LLM flakiness.

If you want to swap in a real LLM (OpenAI, Anthropic, a local llama,
…), replace ``FakeLLM.call`` with whatever client you prefer — the
Chronos recorder is LLM-agnostic, it only observes the LangGraph
state transitions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FakeLLMResponse:
    content: str
    fingerprint: str


class FakeLLM:
    """Deterministic fake LLM keyed on (system, user, seed) text.

    Two ``FakeLLM(seed="A")`` instances given the same inputs always
    return the same output. Different seeds simulate "different
    models" — useful for diff demos where we fork a run under an
    alternative model persona and compare.
    """

    def __init__(self, *, seed: str = "default") -> None:
        self._seed = seed

    def call(self, system: str, user: str) -> FakeLLMResponse:
        digest = hashlib.sha256(f"{self._seed}|{system}|{user}".encode()).hexdigest()[:8]
        sys_hint = system.strip().split()[0] if system.strip() else "none"
        user_short = user.strip()[:40]
        content = f"[{self._seed}:{digest}] sys={sys_hint!r} user={user_short!r}"
        return FakeLLMResponse(content=content, fingerprint=digest)
