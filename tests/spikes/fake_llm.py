"""Fake LLM for deterministic spike testing.

Goal: prove Chronos can capture / replay / fork reasoning trees WITHOUT
depending on external LLM APIs (which are non-deterministic and rate-limited).

The FakeLLM is a pure function of (system_prompt, messages) -> response.
This makes spike results reproducible and lets us focus on the orchestration
problem rather than fighting API flakiness.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FakeLLMResponse:
    content: str
    fingerprint: str


class FakeLLM:
    """Deterministic fake LLM keyed on (system, user) text.

    - Response is a short, traceable string that shows inputs.
    - Same inputs → same output (the whole point).
    - A `seed` lets us simulate different "models" with different style.
    """

    def __init__(self, *, seed: str = "default") -> None:
        self._seed = seed

    def call(self, system: str, user: str) -> FakeLLMResponse:
        digest = hashlib.sha256(f"{self._seed}|{system}|{user}".encode()).hexdigest()[:8]
        # A minimal "reasoning" — quote back a compressed view of inputs
        sys_hint = system.strip().split()[0] if system.strip() else "none"
        user_short = user.strip()[:40]
        content = f"[{self._seed}:{digest}] sys={sys_hint!r} user={user_short!r}"
        return FakeLLMResponse(content=content, fingerprint=digest)
