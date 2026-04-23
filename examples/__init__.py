"""Chronos examples — runnable end-to-end demos.

Each script is self-contained and runs without any external API key
(all LLM calls are served by a deterministic FakeLLM). Run them with:

    uv run python examples/linear_pipeline.py
    uv run python examples/router_loop.py

After a run, inspect the resulting ``chronos.db`` with the CLI:

    chronos runs list --db examples/chronos.db
    chronos diff <parent> <fork_child> --db examples/chronos.db
"""
