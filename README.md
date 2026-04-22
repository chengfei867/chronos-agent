# Chronos Agent ⏳

> **Time-Travel Debugger for Multi-Agent AI Systems.**
> Record every reasoning step. Fork at any node. Diff branches.

**🚧 Status: Research Phase — No code yet. All docs are the artifact.**

**🤖 100% AI-generated** — This entire project, including this README, is written and maintained autonomously by an AI agent (Hermes Agent / Claude). The human instigator only provided the initial prompt; every commit, design doc, and architectural decision is made by AI.

---

## English

### What is this?

`chronos-agent` is a debugger for multi-agent AI systems. Think `pdb` + `git` for LLM reasoning:

- **Record** — Transparently capture every prompt, tool call, and state transition of your agent runs
- **Replay** — Step through any historical run node-by-node
- **Fork** — Branch from any step, swap a prompt / tool / model / temperature, and re-run downstream in a parallel timeline
- **Diff** — Structurally compare two runs (or two forks of the same run) — what diverged, token delta, cost delta, final output delta

### Why now?

2026 is the year multi-agent systems go to production. Yet when they fail, the only debugging tool is "read the trace and hope you spot it, then rerun the whole thing". There is no `pdb`. There is no `git rebase -i`. That's the gap `chronos-agent` fills.

### Status

- **Phase 0: Research & Design** (current) — full competitive analysis, technical feasibility, architecture design, language selection ADR
- **Phase 1: v0.1 MVP** — single-agent record/replay/fork for one framework
- **Phase 2: v0.2** — multi-agent reasoning tree support
- **Phase 3: v0.3+** — framework adapters expansion, web UI, collaboration features

See [`docs/roadmap.md`](./docs/roadmap.md) for detailed milestones (WIP).

### Why 100% AI?

This is an experiment in **agentic software engineering at full autonomy**. An AI agent is the sole developer — not "copilot" style assistance, but **end-to-end ownership**: research, design, code, docs, ops, releases. Every commit author trail, ADR, and progress log is a public record of what AI can build when left alone.

See [`docs/CONTEXT.md`](./docs/CONTEXT.md) — the onboarding document the AI reads at the start of every autonomous cycle.

---

## 中文

### 这是什么？

`chronos-agent` 是多 agent AI 系统的 **时间旅行调试器**。给 LLM 推理过程做的 `pdb` + `git`：

- **记录 (Record)** — 透明拦截 agent 每一步的 prompt、工具调用、状态变化
- **回放 (Replay)** — 对任意历史 run 逐步回放，看当时 agent 在想什么
- **分叉 (Fork)** — 任意节点 checkout 出分支，改一个 prompt / 工具 / 模型 / temperature，重跑下游得到平行世界
- **差分 (Diff)** — 结构化对比两个 run（或同一 run 的两个 fork），哪里分叉了、token 差异、成本差异、最终输出差异

### 为什么是现在？

2026 年是多 agent 系统真正进入生产的一年。但一旦 agent 翻车，调试手段只有 "看 trace 猜错在哪，然后整个重跑"。没有 `pdb`，没有 `git rebase -i`。这个缺口就是 `chronos-agent` 要填的。

### 当前阶段

- **Phase 0: 调研 + 设计**（当前）—— 竞品分析、技术可行性、架构设计、语言选型 ADR
- **Phase 1: v0.1 MVP** —— 单 agent 的 record/replay/fork，支持一个主流框架
- **Phase 2: v0.2** —— 多 agent 推理树支持
- **Phase 3: v0.3+** —— 框架适配扩展、Web UI、协作功能

详细里程碑见 [`docs/roadmap.md`](./docs/roadmap.md)（持续更新）。

### 为什么是 100% AI？

这是一个 **agent 级软件工程完全自主化** 的实验。一个 AI agent 是项目的唯一开发者 —— 不是 copilot 模式的辅助，而是**端到端所有权**：调研、设计、编码、文档、运维、发布。每一个 commit、ADR、进展日志都是 AI 独立操作留下的公开记录。

详见 [`docs/CONTEXT.md`](./docs/CONTEXT.md) —— 这是 AI 每 4 小时 cron 启动时读的那份 onboarding 文档。

---

## Repository Layout

```
chronos-agent/
├── docs/
│   ├── CONTEXT.md           ← AI agent onboarding entry point
│   ├── research/            ← competitive analysis, feasibility, risks
│   ├── design/              ← user stories, architecture, diagrams
│   ├── decisions/           ← Architecture Decision Records (ADRs)
│   └── roadmap.md
├── progress/                ← per-cron-cycle summaries (every 4h)
└── (source code — language TBD by ADR-001)
```

---

## License

MIT (to be added formally once the repo goes public).

---

*🤖 Built autonomously by AI. Overseen by [@chengfei867](https://github.com/chengfei867).*
