# Chronos Agent ⏳

> **Time-Travel Debugger for Multi-Agent AI Systems.**
> Record every reasoning step. Fork at any node. Diff branches.

**🤖 100% AI-generated** — every commit, design doc, and architectural decision in this repository is authored autonomously by an AI agent (Hermes Agent / Claude Opus). The human instigator only fired the starting pistol.

---

## English

### What is this?

`chronos-agent` is a debugger for multi-agent AI systems. Think `pdb` + `git` for LLM reasoning:

- **Record** — Transparently capture every node, prompt, tool call, and state transition of an agent run
- **Fork** — Branch from any recorded node, swap a prompt / tool / model / value, and re-execute the downstream nodes in a parallel timeline
- **Diff** — Structurally compare two runs (or a run and one of its forks) — which nodes diverged, which state keys changed, and how
- **Replay** — Step through a historical run interactively in a TUI (`chronos replay <run_id>`)

### Quickstart (5 minutes)

```bash
git clone https://github.com/chengfei867/chronos-agent.git
cd chronos-agent
uv sync

# Record a baseline + fork with a swapped prompt + show the diff.
uv run python examples/linear_pipeline.py

# Inspect the runs from the CLI:
chronos runs list --db examples/chronos.db
chronos diff <PARENT_ID> <CHILD_ID> --db examples/chronos.db

# Or browse them in your browser (install the web extra once):
uv pip install 'chronos-agent[web]'
chronos web --db examples/chronos.db
# → http://127.0.0.1:8765 opens automatically
```

See [`docs/getting-started.md`](./docs/getting-started.md) for the full walkthrough and [`docs/cli-reference.md`](./docs/cli-reference.md) for every command.

### Status

Phase 1 MVP — **feature-complete for single-agent record/fork/diff on LangGraph**:

| Capability               | Milestone | Status                  |
|--------------------------|-----------|-------------------------|
| Spikes (capture/fork/diff) | M1.1    | ✅ all 3 green          |
| Project skeleton + CI    | M1.2      | ✅                      |
| SQLite canonical store   | M1.3      | ✅                      |
| LangGraph adapter (record) | M1.4    | ✅                      |
| Fork primitive (adapter) | M1.5      | ✅                      |
| CLI read-side (`runs`, `forks`) | M1.6 | ✅                   |
| Replay TUI (`chronos replay`) | M1.7 | ✅ (ADR-007)           |
| Structural diff (`chronos diff`) | M1.8 | ✅ (ADR-006)        |
| Docs + `examples/` + v0.1.0 tag | M1.9 | ✅ released 2026-04-23 |
| `chronos fork` CLI + plan artifact | M1.10 | ✅ (ADR-008)       |

**Next phases**: multi-agent reasoning trees (v0.2), additional framework adapters (AutoGen / CrewAI / raw OpenAI tool-loops), Web UI (v0.3+).

Detailed milestones: [`docs/roadmap.md`](./docs/roadmap.md).

### Why now?

2026 is the year multi-agent systems go to production. Yet when they fail, the dominant debugging tool is "read the trace and hope you spot it, then rerun the whole thing". There is no `pdb`. There is no `git rebase -i`. That's the gap `chronos-agent` fills.

### Why 100% AI?

This is an experiment in **agentic software engineering at full autonomy**. An AI agent is the sole developer — not "copilot" style assistance, but **end-to-end ownership**: research, design, code, docs, ops, releases. Every commit trail, ADR, and progress log is a public record of what AI can build when left alone.

See [`docs/CONTEXT.md`](./docs/CONTEXT.md) — the onboarding document the AI reads at the start of every autonomous cycle.

---

## 中文

### 这是什么？

`chronos-agent` 是多 agent AI 系统的**时间旅行调试器**。给 LLM 推理过程做的 `pdb` + `git`：

- **记录 (Record)** — 透明拦截 agent 每一步的状态、prompt、工具调用
- **分叉 (Fork)** — 在任意记录节点 checkout 出分支，改一个 prompt / 工具 / 模型 / 状态键，重跑下游得到平行世界
- **差分 (Diff)** — 结构化对比两个 run（或同一 run 的 parent 和 fork child），哪个节点分叉了、哪些 state key 变了、怎么变的
- **回放 (Replay)** — TUI 逐步回放历史 run（`chronos replay <run_id>`）

### 5 分钟上手

```bash
git clone https://github.com/chengfei867/chronos-agent.git
cd chronos-agent
uv sync

uv run python examples/linear_pipeline.py

chronos runs list --db examples/chronos.db
chronos diff <PARENT_ID> <CHILD_ID> --db examples/chronos.db

# 浏览器里看推理树（首次运行先装 web extra）：
uv pip install 'chronos-agent[web]'
chronos web --db examples/chronos.db
# → 浏览器自动打开 http://127.0.0.1:8765
```

详细见 [`docs/getting-started.md`](./docs/getting-started.md) 和 [`docs/cli-reference.md`](./docs/cli-reference.md)。

### 当前阶段

Phase 1 MVP — **LangGraph 单 agent 的 record/replay/fork/diff 功能完整**。M1.1–M1.10 已全部 ship，v0.1.0 已发布（2026-04-23），v0.1.1 候选含 replay TUI + `chronos fork` CLI。详细里程碑见 [`docs/roadmap.md`](./docs/roadmap.md)。

### 为什么是现在？

2026 年多 agent 系统进入生产。但一旦翻车，调试手段只有 "看 trace 猜错在哪，然后整个重跑"。没有 `pdb`，没有 `git rebase -i`。这个缺口就是 `chronos-agent` 要填的。

### 为什么是 100% AI？

这是一个 **agent 级软件工程完全自主化** 的实验。一个 AI agent 是项目的唯一开发者 —— 不是 copilot 模式的辅助，而是**端到端所有权**：调研、设计、编码、文档、运维、发布。每一个 commit、ADR、进展日志都是 AI 独立操作留下的公开记录。

详见 [`docs/CONTEXT.md`](./docs/CONTEXT.md) —— AI 每轮 cron 启动时读的那份 onboarding 文档。

---

## Repository Layout

```
chronos-agent/
├── README.md
├── pyproject.toml
├── src/chronos/
│   ├── adapters/            ← framework adapters (LangGraph today)
│   ├── cli/                 ← `chronos` typer app
│   ├── core/                ← models, diff engine
│   └── store/               ← SQLite canonical store
├── examples/                ← runnable demos (no API key required)
│   ├── linear_pipeline.py   ← record → fork → diff on a 5-node graph
│   └── router_loop.py       ← same, on a graph with loops
├── tests/
│   ├── unit/                ← 100+ unit tests (duck-typed fakes)
│   ├── integration/         ← real SqliteStore + real LangGraph
│   └── spikes/              ← empirical validation scripts (M1.1)
├── docs/
│   ├── getting-started.md   ← 5-minute onboarding
│   ├── cli-reference.md     ← every command documented
│   ├── CONTEXT.md           ← AI agent onboarding entry point
│   ├── research/            ← competitive analysis, feasibility, risks
│   ├── design/              ← user stories, architecture, diagrams
│   ├── decisions/           ← Architecture Decision Records (ADRs)
│   └── roadmap.md
├── progress/                ← per-cron-cycle summaries
└── CHANGELOG.md
```

---

## Development

```bash
uv sync
uv run pytest            # 112+ tests, ~92% coverage
uv run ruff check .
uv run ruff format .
```

---

## License

MIT (added on first public release).

---

*🤖 Built autonomously by AI. Overseen by [@chengfei867](https://github.com/chengfei867).*
