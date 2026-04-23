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

**截至 Round 15 结束 (2026-04-23 北京下午 16:48 起, 用户交互轮)**

- Round: **15 完成** (R11 M1.10 fork CLI + v0.1.1 tag → R12 M1.11 usage extractor → R13 cut v0.1.2 tag → R14 CLI 文件拆分 → **R15 Anthropic/OpenAI native usage extractors**)
- 最近 progress doc: `progress/2026-04-23-round-15.md` ← **下一轮的你必读**; R14 在 `progress/2026-04-23-round-14.md`
- 当前阶段: **Phase 1 MVP + 四动词 CLI 闭环 + token/cost 可视化 (三提取器全家桶)**
- 最新 ADR: `ADR-010-native-usage-extractors.md` (Accepted, R15) — 新增 anthropic / openai 两个 convenience extractor, 不改 ADR-009 协议
- 最新 tag: **v0.1.2** (R13 cut; R15 纯 additive feature, 未 bump)
- Blocked items: 无
- 测试状态: **236/236 pass, 94% coverage, ruff + mypy clean** (+20 tests vs R14: 8 anthropic + 7 openai + 3 composition; `langgraph_usage.py` 100% cov)
- CLI 表面 (v0.1.2 最终态, R15 无变): 见 R13 清单
- **Adapter API** (R15 新增):
  - `chronos.adapters.langgraph_usage.anthropic_usage_extractor` — 读 `response_metadata["usage"]`, 折叠 cache tokens 到 prompt
  - `chronos.adapters.langgraph_usage.openai_usage_extractor` — 读 `response_metadata["token_usage"]`, 捕获 reasoning tokens (o1/o3)
  - 两者都实现现有 `UsageExtractor` Protocol, 不改协议
- **Schema 字段** / **Examples** / **CLI**: 与 R14 完全一致
- **新验证事实 (R15)**:
  - **Anthropic prompt caching 计账**: `cache_creation_input_tokens` + `cache_read_input_tokens` 必须 **加到** `prompt_tokens` 里 (Anthropic API 把它们和 `input_tokens` 分开报; 手写 extractor 的头号坑)。成本差异 (+25% / −90%) 留给用户 pricing table, Chronos 只记 token 数
  - **OpenAI reasoning tokens**: `completion_tokens_details.reasoning_tokens` 是 `completion_tokens` 的 **子字段** (API 已经把 reasoning 折进 completion), 所以不能再从 completion 里减。我们把 reasoning 作为 sub-detail 并列, 保留 `prompt+completion==total` 不变量
  - **Duck typing 原则**: 不 import `anthropic` / `openai` SDK (dev venv 里根本没装), 按字段名读 dict 就行 — 用户不用装这些包也能用 extractor
  - **Cross-provider 组合**: `lambda ctx: anthropic(ctx) or openai(ctx) or aimessage(ctx)` — 三行 short-circuit, 文档和 3 个测试验证过
- 旧事实 (仍生效, 不重复):
  - GitHub push 只有 `gh-proxy.com`
  - LangGraph 1.1.9 record/fork/diff 全链路 OK
  - `NodeKind` 合法值 `{llm, tool, fn, router, fork, end}`
  - Runs/Nodes upsert, Forks append-only
  - Duck + real 双测试策略
  - CLI 状态行 / `pyproject.toml::project.version` 每次 version bump 要同步
  - JSON 模式走 stdlib `print(json.dumps(...))` 不走 rich Console
  - `SqliteStore.open()` 静默建文件, 读命令守 `Path.exists()`
  - **progress doc 每轮必写**
  - **`ForkPlan` schema 是 v0.1.1 对外契约** — 字段增删要 bump `chronos_fork_plan_version` + 写 ADR
  - **ADR-009 usage extractor 协议是 v0.1.2 对外契约** — `UsageExtractor` 签名 / `UsageContext` / `UsageResult` 字段 / 失败容忍语义都冻结, 改动要新 ADR
  - **CLI 模块形状 (R14 确立)**: `cli/__init__.py` 只管 typer apps + thin wrappers, 每个 subcommand 实现模块暴露 `*_command(console, open_store_fn, ...)`. 新命令照抄

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

**Round 16 候选** (R15 ship native Anthropic/OpenAI usage extractors + ADR-010):

### R13 实际产出 (2026-04-23 北京下午 16:08 起, 用户交互轮)
- ✅ `src/chronos/__init__.py::__version__` `0.1.1` → `0.1.2`
- ✅ `pyproject.toml::project.version` `0.1.1` → `0.1.2`
- ✅ `cli/__init__.py::info` 状态行刷新为 "Phase 1 M1.11 — usage extractor hook, v0.1.2"
- ✅ `CHANGELOG.md` `[Unreleased]` → `[0.1.2] — 2026-04-23 (Round 12 + Round 13)`, 新加 theme 句 + R13 子段
- ✅ `git tag -a v0.1.2` + push origin via gh-proxy.com
- ✅ 验证全绿: ruff / format / mypy / pytest 216/216 / dogfood 18/18 / `chronos info` 报 0.1.2

### R14 实际产出 (2026-04-23 北京中午 ~12:00 起, 用户交互轮) — 纯 refactor
- ✅ `cli/__init__.py` **848 → 348 行 (-59%)**, 按命令组拆分
- ✅ 新建 `cli/_common.py` (129) / `cli/_usage.py` (109) — 共享 helpers
- ✅ 新建 `cli/runs.py` (167) / `cli/forks.py` (87) / `cli/diff.py` (217) — 统一 `*_command(...)` + DI `console` / `open_store_fn` 形状
- ✅ `cli/replay.py` / `cli/fork.py` 不动 — R11/之前已是这个形状, R14 只把剩下的对齐
- ✅ 验证全绿: ruff / format / mypy / pytest **216/216** / dogfood **18/18** / **零 test 修改** (行为等价最好证据)
- ✅ 版本不动 (pure refactor, v0.1.2 tag 稳定; 无新 ADR)

### R15 实际产出 (2026-04-23 北京下午 16:48 起, 用户交互轮) — 推荐选项 A 落地
- ✅ `src/chronos/adapters/langgraph_usage.py` 新增 2 个 extractor + 1 个内部 helper (+140 LOC)
  - `anthropic_usage_extractor` — 读 `response_metadata["usage"]`, 折叠 `cache_creation_input_tokens` + `cache_read_input_tokens` 到 `prompt_tokens`
  - `openai_usage_extractor` — 读 `response_metadata["token_usage"]`, 捕获 `completion_tokens_details.reasoning_tokens`
  - `_latest_message_with_response_metadata_key(ctx, key)` — 两者共享的消息回溯 helper
  - 两个新 extractor 加入 `__all__`
- ✅ `tests/unit/test_usage_extractor.py` +21 tests (216 → 236): 8 anthropic + 7 openai + 3 composition (doc-tested `or`-chain 模式)
- ✅ `docs/decisions/ADR-010-native-usage-extractors.md` — 字段映射表 + 3 个拒绝的 alternatives
- ✅ `docs/getting-started.md` §4b 重写: 三提取器全家桶 + `combined` 组合示例
- ✅ `docs/cli-reference.md` token-usage 段重写: extractor 对比表
- ✅ 全绿: ruff / format / mypy / pytest **236/236 94% cov** / dogfood **18/18**; `langgraph_usage.py` 100% cov
- ✅ 版本不动 (additive feature, v0.1.2 稳定; 留给 R16 可能的 v0.1.3 release cut)

### 选项 R16-A (推荐): v0.1.3 release cut
- 干净的 release 收尾: bump `__version__` / `pyproject.toml::project.version` → 0.1.3
- `CHANGELOG.md` `[Unreleased]` → `[0.1.3] — 2026-04-23 (Round 15)`, theme 句强调 "three-extractor family + Anthropic prompt caching fidelity"
- `cli/__init__.py::info` 状态行更新 (M1.11 → M1.12 或保持 M1.11 extended, 思考一下)
- `git tag -a v0.1.3` + push
- 规模: 与 R13 相同的 release 流程, 1 轮能 ship

### 选项 R16-B: fork execution engine — 让 `chronos fork run` 真正跑起来
- ⚠️ ADR-008 现在只到 "plan + consume in user code" 就停了; 自动执行是 Phase 1.5 → Phase 2 之间的桥
- 要新 ADR (ADR-011) 定义 "what is a safe automated fork execution", 需要 sandbox / timeout / budget 三件套
- **不建议 cron 轮自启** — 要改 ADR-008 frozen 决策, 必须用户点头

### 选项 R16-C: LangSmith tracer callback extractor
- LangChain 的第三条 usage-accounting 路径 (另两条: `usage_metadata` / `response_metadata`)
- 作用域比 R15 更窄 (单 provider), 测试矩阵约等量
- 低风险但价值也低 (大多数用户已经被 R15 三提取器覆盖), 除非用户有特定 LangSmith 场景, 不是优先项

### 选项 R16-D: AutoGen adapter (Phase 2 正式启动)
- ⚠️ **仍需用户点头**才能做 — R10 试过被抓回, 硬红线
- **必须新 ADR** (ADR-011) AutoGen 状态模型 → Chronos NodeKind 映射

### 选项 R16-E: Web UI skeleton
- 大承诺, 一轮起不了步; **不建议 cron 轮自启**

**R16 倾向**: **选项 A** (v0.1.3 release cut). 和 R13 同构的短轮; 把 R15 的 native extractors 正式打包进 tag 里. 选项 D 的 Phase 2 仍等用户显式授权.

**硬约束 (延续, R10-R15 再次强调)**:
- ❌ 不开始写 Web UI (除非用户点头)
- ❌ **不加 AutoGen/CrewAI adapter** — R10 试过被抓回, 硬红线, 除非用户**显式**说启动 Phase 2
- ❌ 不改 SQLite schema
- ❌ 不动 v0.1.1 frozen 的 API 签名 (record/replay/fork/diff/fork plan CLI 命令 + `ForkPlan` schema v1)
- ❌ **不改 ADR-009 `UsageExtractor` Protocol** — R15 只是新增实现, 协议本身和 v0.1.2 冻结的一致 (`UsageExtractor` 签名、`UsageContext` / `UsageResult` 字段、失败容忍语义)
- ❌ **不动 R14 确立的 CLI 模块形状** (除非补充模式): subcommand 实现模块应该暴露 `*_command(...)` 并接受 DI; 新命令应该照抄这个模式, 别搞新的
- ✅ 任何新功能 → 新 ADR (下一个编号 **ADR-011**; ADR-010 已用于 R15 native extractors)
- ✅ spike / ADR 先行纪律 8 战 8 胜 (R12 ADR-009 + R15 ADR-010 加分), 继续
- ✅ **progress doc 每轮末必写 + commit + push**
- ✅ **动 deps / pyproject.toml 前先读 CONTEXT.md 第 3 节和本节硬约束**
- ✅ 断言时间用 `TZ='Asia/Shanghai' date` 或 `curl -sI https://www.baidu.com | grep -i '^date:'`, 别信 session 时间
- ✅ cron 实际节奏: **every 180m (3h)**; **白天用户手动交互, 晚上交给 cron**
- ✅ **`ForkPlan` schema 是 v0.1.1 对外契约** — 字段增删要 bump `chronos_fork_plan_version` + 写 ADR
- ✅ **version bump 检查单** (R13 新增): 改 `__version__` 时 grep `v0.1.<prev>` / `M1.<prev>` 确保 CLI 状态行 / 文档 / test fixture 里没有旧版本残留; `pyproject.toml::project.version` 必须同步

---

*Last updated by Round 15 agent (2026-04-23 北京下午 16:48 起, native Anthropic/OpenAI usage extractors + ADR-010)*


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

*Last updated: 2026-04-23 by Round 12 agent (北京下午, 用户交互轮, M1.11 usage extractor hook ship, 未 tag 留 R13 cut v0.1.2)*
