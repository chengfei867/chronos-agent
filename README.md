# Chronos Agent ⏳

> **Time-Travel Debugger for Multi-Agent AI Systems.**
> Record every reasoning step. Fork at any node. Diff branches. Compare timelines side by side.

**🤖 100% AI-generated** — every commit, design doc, and architectural decision in this repository is authored autonomously by an AI agent (Hermes Agent / Claude Opus). The human instigator only fired the starting pistol. The CrewAI adapter shipped in v0.4.0 spans a seven-round arc (R49–R55) entirely authored by the agent across three time zones of autonomous cron slots.

---

## English

### What is this?

`chronos-agent` is a debugger for multi-agent AI systems. Think `pdb` + `git` for LLM reasoning:

- **Record** — Transparently capture every node, prompt, tool call, and state transition of an agent run
- **Fork** — Branch from any recorded node, swap a prompt / tool / model / value, and re-execute the downstream nodes in a parallel timeline
- **Diff** — Structurally compare two runs (or a run and one of its forks) — which nodes diverged, which state keys changed, and how
- **Compare** — Line up two runs side by side in the Web UI and see exactly where they diverged, with the alignment list spelling out same / changed / added / missing node by node
- **Replay** — Step through a historical run interactively in a TUI (`chronos replay <run_id>`) or visually in the Web UI

### See it in action

The Web UI ships in the `chronos web` command — one binary, zero Node.js required at install time.

**Run list** — every captured run, filterable by status / framework, selectable for comparison:

![RunList](./docs/assets/screenshot-runs-list.png)

**Single-run reasoning tree** — nodes for every LLM call, tool call, router decision, with token counts and cost:

![TreeView](./docs/assets/screenshot-tree-single-run.png)

**Family tree** — when a run has forks, see all timelines stacked as lanes with cross-lane fork edges:

![Family tree](./docs/assets/screenshot-family-tree.png)

**Compare two runs** — pick any two runs from the list, hit Compare, get a side-by-side diff with an alignment list:

![DiffView](./docs/assets/screenshot-diff-view.png)

### Quickstart (5 minutes)

```bash
git clone https://github.com/chengfei867/chronos-agent.git
cd chronos-agent
uv sync

# Record a baseline + fork with a swapped prompt + show the diff.
uv run python examples/linear_pipeline.py

# Inspect the runs from the CLI:
chronos runs list --db examples/chronos.db
chronos diff <PARENT_ID> <CHILD_ID> --db examples/chronos.db   # the "compare" verb

# Or browse them in your browser (install the web extra once):
uv pip install 'chronos-agent[web]'
chronos web --db examples/chronos.db
# → http://127.0.0.1:8765 opens automatically

# Prefer a demo with fork tree + diff out of the box?
python scripts/seed_demo.py --db /tmp/chronos-demo.db
chronos web --db /tmp/chronos-demo.db
```

See [`docs/getting-started.md`](./docs/getting-started.md) for the full walkthrough and [`docs/cli-reference.md`](./docs/cli-reference.md) for every command.

### Status

Phase 3 **complete** — **three-adapter matrix (LangGraph + AutoGen + CrewAI) shipping, effect-aware fork UX end-to-end, Web UI and CLI in lockstep**:

| Capability                                                      | Milestone             | Status                                                                            |
|-----------------------------------------------------------------|-----------------------|-----------------------------------------------------------------------------------|
| Spikes (capture/fork/diff)                                      | M1.1                  | ✅ all 3 green                                                                     |
| Core four-verb loop (record/replay/fork/diff)                   | M1.*                  | ✅ shipped in v0.1.x                                                               |
| Token usage & cost visibility                                   | v0.1.2+               | ✅ (three-extractor family)                                                        |
| Adapter contract v2 (ADR-015/016)                               | v0.2.0a               | ✅ Phase-2 unblocked                                                               |
| Linear pipeline reference adapter                               | v0.2.0a               | ✅ zero-dep, ships as R1 impl                                                      |
| **LangGraph adapter**                                           | v0.2.0                | ✅ state-dict paradigm (checkpointer-backed fork)                                  |
| **AutoGen adapter**                                             | v0.4.0a2              | ✅ message-list paradigm + per-tool `effects_map` override ([ADR-020])             |
| **CrewAI adapter**                                              | **v0.4.0**            | **✅ event-bus paradigm, pin `>=0.80,<2.0` ([ADR-021] / [ADR-022])**               |
| Web UI — TreeView + Run Info + playback                         | v0.2.0                | ✅ AntD v6 + ReactFlow v12, zh/en i18n                                             |
| Multi-run family tree + lane layout                             | v0.2.0                | ✅ R37.5                                                                           |
| Compare: side-by-side diff viewer (UI)                          | v0.2.1                | ✅ R39-A — ADR-018 "compare" narrative                                             |
| **Effect-aware fork UX** — adapter tags, CLI preview, Web modal | v0.3.0 → v0.4.0       | ✅ PH3-02 + PH3-03 + PH3-04, see [`docs/guides/forking-safely.md`][forksafely]     |
| Release pipeline (semver, tags, changelog)                      | ongoing               | ✅ [`chronos-release-pattern`] skill, 12x validated                                |

[forksafely]: ./docs/guides/forking-safely.md
[ADR-020]: ./docs/decisions/ADR-020-adapter-tool-node-name-shape.md
[ADR-021]: ./docs/decisions/ADR-021-crewai-adapter.md
[ADR-022]: ./docs/decisions/ADR-022-crewai-version-pin-bump.md

**Next phases**: Phase 4 candidates (multi-run tree comparison, fork-tree visualization, fourth adapter #4, Jupyter integration).

Detailed milestones: [`docs/roadmap.md`](./docs/roadmap.md). Design decisions: [`docs/decisions/`](./docs/decisions/).

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
- **对比 (Compare)** — Web UI 里把两个 run 并排展示，对齐清单逐行标出「相同 / 改变 / 新增 / 缺失」，一眼看出在哪里走向了不同
- **回放 (Replay)** — TUI 逐步回放 (`chronos replay <run_id>`) 或者在 Web UI 里点播放按钮看时间线推进

### 几张图先睹为快

Web UI 打包在 `chronos web` 里，一条命令起服务，装包时不需要 Node.js。

**运行列表** — 抓到的每一次 Agent 任务，可以按状态和框架过滤，支持勾选两个做对比：

![运行列表](./docs/assets/screenshot-runs-list.png)

**单次运行的推理树** — 每个 LLM 调用、工具调用、路由决策都有节点，附带 token 用量和成本：

![推理树](./docs/assets/screenshot-tree-single-run.png)

**族谱视图** — 这个 run 有 fork 时，所有时间线并排成 lane，fork 边跨 lane 连接：

![族谱](./docs/assets/screenshot-family-tree.png)

**并排对比两个 run** — 列表里勾选两个点「对比」，侧边栏列出每个节点位置的对齐结果：

![对比视图](./docs/assets/screenshot-diff-view.png)

### 5 分钟上手

```bash
git clone https://github.com/chengfei867/chronos-agent.git
cd chronos-agent
uv sync

uv run python examples/linear_pipeline.py

chronos runs list --db examples/chronos.db
chronos diff <PARENT_ID> <CHILD_ID> --db examples/chronos.db   # 就是 "compare" 这个动词

# 浏览器里看推理树（首次运行先装 web extra）：
uv pip install 'chronos-agent[web]'
chronos web --db examples/chronos.db
# → 浏览器自动打开 http://127.0.0.1:8765

# 想看一个自带 fork 族谱 + 对比的 demo？
python scripts/seed_demo.py --db /tmp/chronos-demo.db
chronos web --db /tmp/chronos-demo.db
```

详细见 [`docs/getting-started.md`](./docs/getting-started.md) 和 [`docs/cli-reference.md`](./docs/cli-reference.md)。

### 当前阶段

Phase 3 **已收官** — **三 adapter 矩阵 (LangGraph + AutoGen + CrewAI) 全部上线, 副作用感知 fork UX 端到端打通, Web UI 与 CLI 同步对齐**:

| 能力                                             | 里程碑        | 状态                                                                |
|--------------------------------------------------|---------------|---------------------------------------------------------------------|
| 三条 spike (capture/fork/diff)                   | M1.1          | ✅ 全绿                                                              |
| 四段动词 (record/replay/fork/diff)               | M1.*          | ✅ v0.1.x 系列已 ship                                                |
| Token 用量 & 成本可视                            | v0.1.2+       | ✅ 三种 extractor 合流                                               |
| Adapter 契约 v2 (ADR-015/016)                    | v0.2.0a       | ✅ Phase 2 正式解锁                                                  |
| Linear pipeline 参考 adapter                     | v0.2.0a       | ✅ 零依赖                                                            |
| **LangGraph adapter**                            | v0.2.0        | ✅ state-dict 范式 (checkpointer-backed fork)                        |
| **AutoGen adapter**                              | v0.4.0a2      | ✅ message-list 范式 + 工具粒度 `effects_map` 覆写 ([ADR-020])       |
| **CrewAI adapter**                               | **v0.4.0**    | **✅ event-bus 范式, pin `>=0.80,<2.0` ([ADR-021] / [ADR-022])**     |
| Web UI — TreeView + 运行信息 + 回放              | v0.2.0        | ✅ AntD v6 + ReactFlow v12, 中英双语                                 |
| 多 run 族谱视图                                  | v0.2.0        | ✅ R37.5                                                             |
| 并排对比视图 Compare (Web UI)                    | v0.2.1        | ✅ R39-A — ADR-018 "compare" 叙事                                    |
| **副作用感知 Fork UX** — tag + CLI preview + Web | v0.3.0 → v0.4.0 | ✅ PH3-02 + PH3-03 + PH3-04, 见 [`docs/guides/forking-safely.md`][forksafely] |
| Release 流程 (SemVer + tag + changelog)          | 长期          | ✅ [`chronos-release-pattern`] skill, 12 轮验证                      |

**下一阶段**: Phase 4 候选 (多 run 树形对比 / fork tree 可视化 / 第 4 个 adapter / Jupyter 集成).

详细里程碑见 [`docs/roadmap.md`](./docs/roadmap.md)。设计决策见 [`docs/decisions/`](./docs/decisions/)。

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
│   ├── adapters/            ← framework adapters (LangGraph + AutoGen + CrewAI + Linear)
│   ├── api/                 ← FastAPI Web UI backend (/runs, /runs/compare, …)
│   ├── cli/                 ← `chronos` typer app (runs/diff/fork/replay/web)
│   ├── core/                ← models, diff engine
│   └── store/               ← SQLite canonical store
├── frontend/                ← Web UI (React + AntD v6 + ReactFlow v12, bundled into the wheel)
├── examples/                ← runnable demos (no API key required)
│   ├── linear_pipeline.py   ← record → fork → diff on a 5-node graph
│   └── router_loop.py       ← same, on a graph with loops
├── scripts/
│   └── seed_demo.py         ← 10-second demo DB (5 runs, 3-gen fork chain)
├── tests/
│   ├── unit/                ← 470+ unit tests (duck-typed fakes)
│   ├── integration/         ← real SqliteStore + real LangGraph
│   ├── live/                ← real-LLM smoke tests, opt-in via CHRONOS_LIVE=1
│   └── spikes/              ← empirical validation scripts (M1.1 + per-adapter)
├── docs/
│   ├── assets/              ← README screenshots
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
uv run pytest            # 470+ tests, ~94% coverage
uv run ruff check .
uv run ruff format .
uv run mypy src/         # src is typed; tests are not
```

Frontend rebuild (only when changing `frontend/src/**`):

```bash
cd frontend
npm ci --registry=https://registry.npmmirror.com --include=dev
npm run build            # output goes to frontend/dist/, committed to the repo
```

---

## License

MIT (added on first public release).

---

*🤖 Built autonomously by AI. Overseen by [@chengfei867](https://github.com/chengfei867).*
