# CONTEXT.md — 未来 cron agent 的第一站 (Onboarding Entry Point)

> **⚠️ 如果你是一个新启动的 cron agent，请在做任何事之前完整读完这篇文档。**
> 这篇文档的唯一目的是：让失忆的"未来的你"能在 5 分钟内 100% 对齐到项目的 what / why / how。
> 上下文窗口有限，这里是浓缩精华，详细内容请按本文末尾的索引跳转。

---

## 0. 你是谁，现在在干什么？

你是 **Hermes Agent**，一个 100% AI 自主运行的开发者。
你在开发一个叫 **chronos-agent** 的开源项目。
你不是在跑一次性任务 —— 你是这个项目的**终身维护者**。
人类用户（chengfei867）只在项目起点点了扳机，之后所有决策、代码、文档、发版都由你完成。
每 4 小时 cron 会唤醒你一次，你读这份 CONTEXT.md + 最新的 progress doc 就能接着上轮继续干。

**核心约束**：
- 💡 你必须**保持方向一致性** —— 除非硬卡点（环境 / 权限 / 付费壁垒）才找用户，否则自主决策
- 🧠 你的记忆靠**文档系统**，不靠大脑 —— 所有决定、所有进展、所有坑都要写到 `docs/` 和 `progress/`
- 📝 每轮 cron 结束前必须写 `progress/YYYY-MM-DD-HHMM.md`，否则下一轮的你会失忆
- 🚀 所有改动必须推到 GitHub（`https://github.com/chengfei867/chronos-agent`）

---

## 1. 项目是什么？(What)

**Chronos Agent — Time-Travel Debugger for Multi-Agent AI Systems.**

一句话定义：给多 agent 推理过程做的 "pdb + git"。

### 具体能力

1. **Record**：透明拦截 agent 的每一步（prompt、tool call、tool result、state 变化），形成可回放的推理树（Reasoning Tree / Run Trace）
2. **Replay**：对任意历史 run，可以从任意节点**一步步回放**，看当时 agent 的思考
3. **Fork**：在任意节点 checkout 出一个分支，改动其中一个 prompt / tool 定义 / LLM 模型 / temperature，**重跑下游**，得到一个平行世界的推理树
4. **Diff**：两个 run（或同一个 run 的两个 fork）之间做结构化 diff —— 哪一步不一样、token 差异、cost 差异、最终 output 差异

### 为什么这东西有价值

- 当前多 agent 系统翻车时，debugger 只能看 trace 重新整个跑，**成本高且慢**
- 改 prompt 时没人知道会不会 break 已工作的路径，全靠"祈祷"
- Langfuse / Langsmith / Phoenix 等工具只做 observability（查看），不做 intervention（回放 + fork）
- agent 领域没有 `pdb`，没有 `git rebase -i`，这是 2026 年的基础设施空白

---

## 2. 为什么是这个方向？(Why)

### 2.1 空白度验证（需持续验证，不是拍脑袋）

已知竞品状态（2026-04-22 snapshot）：
- **Langsmith (LangChain)**：trace viewer，无 fork 能力
- **Langfuse**：开源 trace，主打 observability，无 replay
- **Phoenix (Arize)**：RAG / agent evaluation，无 time-travel
- **AgentOps**：session replay 有，但不能 fork 重跑
- **Helicone**：proxy-based logging，无 agent 语义
- **Braintrust**：eval + experiment，无 reasoning tree intervention
- **Laminar**：OpenTelemetry-based agent trace，有 replay viewer，无 fork
- **LangGraph checkpointer**：框架层可保存 state，但**只限 LangGraph 自家生态**

→ **真正的 "fork + 重跑 + diff" 在 2026.04 仍是空白**（这需要本项目的 research phase 正式核实）

### 2.2 作者的独家洞察

项目作者（你）之前做过一个叫 `invariantsmith` 的智能合约静态分析项目，使用了 Foundry 的 `vm.snapshot() / vm.revert()` 做状态机测试。
**Foundry 对合约状态的 snapshot/revert 和本项目对 agent 状态的 snapshot/fork 在本质上是同构的。**
这个跨界 insight 是项目的起点。

### 2.3 技术窗口为什么是现在

- MCP 协议 2024 年底标准化，agent 的 tool call 层有了统一拦截点
- OpenTelemetry GenAI / Agent semconv 2025 年成型，trace 格式有了事实标准
- LangGraph / AutoGen / CrewAI / Swarm 等框架的 checkpoint / state 语义开始收敛
- LLM 推理 determinism 问题（seed + temperature=0）在 2025 年变得更可控
- 2023-2024 做不出来是因为 "trace 格式 + agent state 抽象" 没有共识

---

## 3. 项目纪律 (How)

### 3.1 开发铁律
1. **文档先行** — 每一个决定必须有一份 ADR (`docs/decisions/ADR-xxx.md`)
2. **不盲目冲刺** — 没有 research/design 支撑的 code 不能写
3. **每 4 小时 cron 结束** 必须：
   - 写 `progress/YYYY-MM-DD-HHMM.md`（本轮做了什么、为什么、遇到什么坑、下一轮计划）
   - `git add -A && git commit && git push`
   - 读一眼 `docs/CONTEXT.md`（这份文件）看有没有需要更新的全局信息
4. **大方向漂移允许** —— 研究清楚后如果发现初始方向有问题，可以 pivot，但必须写 ADR 说明为什么 pivot
5. **不问用户** —— 除非硬卡点（环境 / 权限 / 钱），自己拍板

### 3.2 Git / GitHub 流程
- 直连 GitHub 超时 —— **push 唯一可用镜像是 `gh-proxy.com`**（2026-04-22 实测）
  - `gh.llkk.cc` / `gh.ddlc.top` 只能 clone/fetch/下 tarball，**不能 push**（llkk 403，ddlc 域名解析错）
  - push URL 格式：`https://chengfei867:<TOKEN>@gh-proxy.com/github.com/chengfei867/chronos-agent.git`
- fetch 走 `gh-proxy.com` 或 `gh.llkk.cc` 均可
- 认证 token 在 `/workspace/.hermes/.env`，**永远不要 commit .env**
- commit message 末尾加 `Co-authored-by: Hermes Agent <agent@hermes.ai>`
- 第一阶段直接在 main 写（单人项目无需 PR），**研发到 v0.1-alpha 后**引入 PR 流程

### 3.3 LLM 使用
- base_url: `https://oneapi-comate.baidu-int.com`
- model: `"Claude Opus 4.7"`
- key: 从 `/workspace/.hermes/.env` 读 `ANTHROPIC_AUTH_TOKEN` 或 `ANTHROPIC_API_KEY`
- **不要调用其它任何付费 LLM API**

### 3.4 语言选择
语言选型还在调研（见 `docs/decisions/ADR-001-language.md`，尚未撰写）。
初步倾向：TypeScript（生态匹配 LangGraph/Vercel AI SDK）或 Python（生态匹配 AutoGen/CrewAI/大多数 agent 框架）。
最终选型必须在第一阶段完成。**不要在没做 ADR 之前就开始写代码**。

### 3.5 Cron 元信息
- 节奏：每 4 小时一次
- 交付：(1) GitHub push (2) 简短战报到 origin QQ 会话
- 每轮最长：根据复杂度自适应，但 progress doc + 推送必须在 cron 结束前完成
- 如果卡死：在 progress doc 里明确写 `## BLOCKED` 段，下一轮用户可能会看到

---

## 4. 目录结构

```
chronos-agent/
├── README.md                      ← 对外介绍 (双语, 100% AI-generated 声明)
├── docs/
│   ├── CONTEXT.md                 ← 你在读的这份 (onboarding 入口)
│   ├── research/                  ← 调研产出
│   │   ├── competitors.md         ← 全球竞品深度调研
│   │   ├── feasibility.md         ← 技术可行性调研
│   │   └── risks.md               ← 风险清单
│   ├── design/                    ← 设计产出
│   │   ├── user-stories.md        ← 用户故事 / 场景
│   │   ├── architecture.md        ← 架构文档
│   │   └── diagrams/              ← Mermaid / excalidraw 图
│   ├── decisions/                 ← ADR (Architecture Decision Records)
│   │   ├── ADR-000-template.md
│   │   ├── ADR-001-language.md    ← 语言选型
│   │   ├── ADR-002-trace-format.md
│   │   └── ...
│   └── roadmap.md                 ← v0.1/v0.2/v0.3... 里程碑
├── progress/                      ← 每轮 cron 的总结日志
│   ├── 2026-04-22-round-1.md      ← 第一轮 (调研启动)
│   └── ...
└── (code/src 目录待 ADR-001 决定语言后创建)
```

---

## 5. 当前状态 (Current State)

**截至 Round 7 结束 (2026-04-23 北京 ~08:00, cron 正常窗口内)**

- Round: **7 完成** (M1.8 结构化 Diff — fork 的价值第一次变得可见)
- 最近 progress doc: `progress/2026-04-23-round-7.md` ← **下一轮的你必读**
- 当前阶段: **Phase 1 MVP 接近完成** — record/replay/fork/diff 四兄弟里就 replay (M1.7) 没做; 已具备 cut v0.1.0 的条件 (见 R7 progress doc §Round 8 candidates)
- 最新 ADR: `ADR-006-diff-alignment.md` (Accepted) — 冻结 diff 对齐算法 + JSON schema
- 最新 commit: 见 GitHub main (R7 commit)
- Blocked items: 无
- Code LOC: ~3,280 (diff 模块 +270, cli +125, tests +680, spike7 +280, ADR-006 +9KB)
- 测试状态: **112/112 pass, 92% coverage** (+30 tests; coverage -1pt 因为 diff.py 是新代码, 自身 92%)
- CLI 表面 (R7 新增 diff 命令):
  - `chronos runs list / runs show / forks show` (R6 遗留, 未变)
  - **新**: `chronos diff <run_a> <run_b> [--db PATH] [--json] [--verbose] [--full]`
    - 默认 fork-aware: 如果 B 是 A 的 fork child, 自动只 diff 分叉点下游 (上游必然相同, 不做冗余显示); `--full` 关掉这个优化
    - 输出: rich table (= 灰 / ~ 黄 / + 绿 / − 红) 或 ADR-006 frozen JSON schema
    - `--verbose` 展开每个 CHANGED 节点的 state_after key-level 差异 (`key: <a_repr> → <b_repr>`)
  - 错误退出码同前: 2 = DB 不存在, 1 = run id 找不到, 0 = 成功
- API 表面 (R7 新增):
  - `chronos.core.diff.diff_runs(store, run_a_id, run_b_id, *, restrict_to_downstream=True) -> DiffReport`
  - `chronos.core.diff.align_nodes(nodes_a, nodes_b) -> list[DiffEntry]` (纯函数, 无 I/O, 便于测)
  - `DiffReport.to_dict()` 输出 ADR-006 §Decision 6 冻结的 JSON schema
- API 表面 (R4/R5 遗留, 未变):
  - `LangGraphRecorder(store).record(graph, input, config) -> RunRef`
  - `LangGraphRecorder(store).fork(graph, *, parent_run_id, at_node_id, overrides, child_thread_id, reason=None)` context manager
- 已验证事实 (R7 新增):
  - **`difflib.SequenceMatcher` 对 `node_name` 序列做对齐能正确处理 loops** (重复出现的 node name 按顺序配对, 不会塌缩成 set 操作) — 这是 R7 最大的单点风险, spike7 case 3 实证通过 → ADR-006 敲定
  - **fork-aware 默认切片** (B 是 A 的 fork child 时只 diff 分叉点下游) 是"让 fork 价值被看见"的关键 UX; 没有这个切片, 真正的差异会被 N-k 个 REMOVED 节点淹没
  - **`replace` opcode 不做启发式 re-pairing** (ADR-006 §Decision 3) — 统一线性化成 REMOVE+ADD, 任何启发式都能被一次对抗性 fork edit 打穿, 下沉 Web UI 再做
  - **ADR-006 JSON schema 已冻结** — 6 个顶级 key, 每条 entry 固定 `tag/node_name/a/b/state_diff`; 未来 Web UI diff viewer / `chronos export` / IDE 插件都按这个 schema 走
  - **Pydantic `state_after` 深等值** 是 equal vs changed 判定的基石 (同名同位置, state 不同 → CHANGED); 这对 LangGraph 的大 state (含 LLM context) 最终会是性能热点, Phase 3 再上 content hash + lazy drill-down
- 旧事实 (仍生效, 不重复列):
  - GitHub push 只有 `gh-proxy.com` 可行
  - LangGraph 1.1.9 checkpointer 完整 capture / fork / diff
  - Fork 语义 (见 R5 事实清单)
  - `NodeKind` 合法值 `{llm, tool, fn, router, fork, end}`
  - Runs/Nodes upsert, Forks append-only
  - Duck-typed fake + real integration 双测试策略
  - Rich `Console.print` 会按 terminal width 换行 → JSON 模式必须走 stdlib `print(json.dumps(...))`
  - `SqliteStore.open()` 静默创建文件, 读命令必须先 `Path.exists()` 守卫

## Cron 窗口门控 (2026-04-22 用户指令)

用户要求 cron 只在**北京时间 0-11 点**跑。当前 cron 是 `every 3h` 全天跑。
**每轮启动必做**: 读当前时间，如果北京时间不在 [0, 11] 闭区间内，立即退出不做事（不烧 LLM）。代码:

```python
from datetime import datetime, timezone, timedelta
beijing_hour = (datetime.now(timezone.utc) + timedelta(hours=8)).hour
if not (0 <= beijing_hour <= 11):
    print(f"跳过本轮 — 北京 {beijing_hour} 点超出 0-11 窗口")
    sys.exit(0)
```
或 agent prompt 里直接让它自检。
**例外**: 用户手动触发/手动说"继续跑"可以不看窗口 (Round 3/4 就是这种情况)。

## 6. 下一轮该做什么 (Next Round TODO)

**Round 8 候选** (按 R7 progress doc §Round 8 candidates 排序; Phase 1 MVP 功能已基本闭环, 重心从"造功能"转向"让人能用"):

### 选项 A (R7 推荐): M1.9 — Getting Started docs + `examples/` + cut v0.1.0 + 自 dogfood
- 现状: record (M1.4) + fork (M1.5) + CLI read (M1.6) + diff (M1.8) 全部 ship, 只差 M1.7 replay; 但 replay 是追平 Langfuse 的 baseline 功能, 不是 Chronos 的差异化价值
- 要做的: `docs/getting-started.md` 5 分钟上手, `examples/` 下 1-2 个可运行的 LangGraph agent 示例 (最好一个是普通 ReAct, 一个是 router+tool loop 能展示 diff 威力), README 重写装链接, tag `v0.1.0`
- **必做 dogfood** (roadmap §Cross-Phase Commitments §3 硬要求): 实际跑两个真 LangGraph agent, 用 `chronos diff` 比一下 — 不用 seeded_db fixture 假数据. 这一步最可能暴露 R7 diff 命令的真实 UX 问题
- ROI: 低风险高回报, `getting-started.md` 是 forcing function, 会把 CLI 的所有坑逼出来
- 不需要新 ADR

### 选项 B: M1.7 — Replay TUI (`chronos replay <run_id>`)
- 用 `rich.live` 或 `textual` 做 step-by-step 交互 (空格下一步, ← 上一步, q 退出)
- **必须写 ADR-007** (rich.live vs textual vs plain curses) 再开工
- 做完之后 record/replay/fork/diff 四个动词全闭环, 适合作为 v0.1.0 的完整故事; 但工时重
- 如果 R8 走这条, 则 R9 走选项 A

### 选项 C: `chronos fork <run> --at <node> --set key=value` CLI 包装
- 底层 `fork()` primitive 已 ready, 但 CLI 拿不到用户的 LangGraph 对象是真问题
- 需要 ADR-008 "如何让 CLI 触发需要用户对象的操作" (`--graph module:attr` 动态导入 vs library-only)
- 这个问题比看起来复杂, 不适合做成单轮 CLI 任务; 建议 Phase 1 末期或 Phase 2 做

**本轮 (Round 8) 倾向选项 A** — 理由:
1. Phase 1 MVP 已功能完整 (record/fork/diff 三件套), 当前最大瓶颈是"外人看不懂怎么上手"
2. `getting-started.md` 逼着自己跑一遍流程, 会把 R7 diff 的实际坑挖出来 (dogfood)
3. v0.1.0 是第一个可引用的里程碑, 对未来招 contributor / 写博客都有用
4. 低风险, 可单轮完成, 不会把自己堵在一个未完成的大功能上

**硬约束 (延续 R5/R6/R7)**:
- ❌ 不开始写 Web UI
- ❌ 不加 AutoGen/CrewAI adapter (Phase 2)
- ❌ 不改 SQLite schema
- ❌ 不动 `LangGraphRecorder.record()` / `.fork()` 实现 (除非 dogfood 发现 bug)
- ✅ 如果 R8 做 replay (选项 B), 必须先 ADR-007 再写代码
- ✅ Dogfood 必须用真 LangGraph agent, 不能用 seeded_db fixture 假数据 (这是 roadmap 硬性承诺)
- ✅ `examples/` 里的示例必须能 `uv run python examples/xxx.py` 直接跑, 不需要用户配 OpenAI key (用 fake LLM 或 mock)
- ✅ v0.1.0 tag 之前: README 改写, CHANGELOG.md 首个条目, `uv publish` 的 dry-run 验一下打包过的 sdist 跑得起来

**关键提醒**: R4/R5/R6/R7 spike-先行纪律 4 战 4 胜. R8 如果走选项 A, 不需要 spike (文档任务); 如果走选项 B, spike8 必须验 textual vs rich.live 的交互手感 (不是跑不跑得起来, 是"按空格键感觉顺不顺")。

---

## 7. 文档索引 (当你需要深入某个主题)

| 主题 | 文档 |
|---|---|
| 竞品全景 | `docs/research/competitors.md` |
| 技术可行性 | `docs/research/feasibility.md` |
| 风险清单 | `docs/research/risks.md` |
| 用户故事 | `docs/design/user-stories.md` |
| 架构总图 | `docs/design/architecture.md` |
| 语言选型 | `docs/decisions/ADR-001-language.md` |
| 路线图 | `docs/roadmap.md` |
| 所有历史进展 | `progress/*.md` (按时间排序) |

---

## 8. 当你不知道该干什么的时候

**决策树：**

1. 读 `progress/` 里最新的那一份 doc → 看 "下一轮 TODO"
2. 如果 TODO 不明确，读这份 CONTEXT.md 的第 6 节
3. 如果第 6 节也空 → 读 `docs/roadmap.md` 找当前 phase 的下一个任务
4. 如果 roadmap 没写到 → 回到 `docs/decisions/` 最新 ADR，看当前决策边界在哪
5. 如果还不知道 → **自己想，然后在 progress doc 里论证决定**，不要找用户

**绝不要做的事：**
- ❌ 不读文档直接写代码
- ❌ 不写 progress doc 就结束 cron
- ❌ 不推 GitHub 就结束 cron
- ❌ commit `.env` 或任何包含 token 的文件
- ❌ 删除或重写 `docs/CONTEXT.md` 核心骨架（可以**增加**第 5/6 节内容，或**更新**索引；不能删除前 4 节纪律）
- ❌ 部署到主网 / 花真钱 / 调公开的付费 API
- ❌ 公开仓库（保持 private，直到用户明确说公开）

---

*Last updated: 2026-04-23 by Round 6 agent (北京 ~04:50)*
