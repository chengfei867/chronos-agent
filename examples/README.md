# Chronos examples

Runnable, self-contained demos of Chronos's core loop (**record → fork → diff**). Each example uses a deterministic fake LLM, so you can run them with zero API keys, zero network calls, and zero flakiness.

## Scripts

| File | What it shows |
|------|---------------|
| [`linear_pipeline.py`](./linear_pipeline.py) | A 5-node LangGraph agent (plan → research → draft → review → finalize). Records a baseline, forks at `research` with an alternative LLM persona, and the diff shows exactly which downstream nodes changed. The canonical "Alex story" walkthrough from [`docs/design/user-stories.md`](../docs/design/user-stories.md). |
| [`router_loop.py`](./router_loop.py) | A LangGraph agent with a conditional edge that loops up to `MAX_ROUNDS` times. The fork overrides the round counter to force early exit, demonstrating how the diff aligner handles **repeated node names** (see [ADR-006](../docs/decisions/ADR-006-diff-alignment.md)). |

## Running

From the repository root:

```bash
uv run python examples/linear_pipeline.py
uv run python examples/router_loop.py
```

Each script prints the recorded run ids, a ready-to-paste set of `chronos` CLI commands, and cleans up its own `examples/chronos.db` on the next run.

## Swapping in a real LLM

The examples import [`examples/_fake_llm.py`](./_fake_llm.py), which is a pure function of `(system, user, seed)`. To use a real LLM, replace `_LLM_BASE = FakeLLM(seed=...)` with whatever client you prefer (`openai.OpenAI()`, `anthropic.Anthropic()`, an `ollama` local model, etc.) — Chronos observes LangGraph state transitions, not LLM APIs, so the recorder is client-agnostic.

## See also

- [`docs/getting-started.md`](../docs/getting-started.md) — 5-minute quickstart
- [`docs/cli-reference.md`](../docs/cli-reference.md) — every CLI flag explained
