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

**截至 Round 26 结束 (2026-04-23 CST 中午, 用户交互轮) — ADR-016 (Adapter interface) 落地 + roadmap.md 大修 (对齐 R1-R25 实际); ADR-014 R1 契约半成品绿灯 (实现半需 R28+)**

- Round: **26 完成** (documentation round — ADR + roadmap refresh, 零代码改动)
- 最近 progress doc: `progress/2026-04-23-round-26.md` ← **下一轮必读**
- 当前阶段: **Phase 1 ✅ closed on paper + v0.1.6 cut + ADR-014 (Phase 2 entry) 状态: R1 ✅ contract (ADR-016) / ❌ impl, R2 ✅ (ADR-015), R3 ❌ (还要 multi-adapter dogfood), R4 ❌ (risks doc)**
- 最新 ADR: **ADR-016 (R26)** — Adapter interface (3 Protocols: RecorderProtocol / AdapterProtocol / NodeIdentityResolver)
- 最新 tag: **v0.1.6** (未变; R26 无 version bump, documentation round)
- Blocked items: 无
- 测试状态: **264/264 pass, 93% coverage**; `FORCE_COLOR=1` 下也 264/264 pass
- CLI 表面: 同 v0.1.6, 未变
- **R26 产出**:
  - `docs/decisions/ADR-016-adapter-interface.md` (~15 KB, Accepted): 3 Protocols + 2 dataclass 复用 + 5 个 rejected alternatives. `RecorderProtocol` 描述 record/fork CM 生命周期 5 条 invariant (含原子性/幂等性/AdapterError 唯一性); `AdapterProtocol` 描述模块级插件形状 (`build_recorder` + `name` + `version_constraint` + `**adapter_specific`); `NodeIdentityResolver` 为 Phase 2 adapter 预留 node_name 派生钩子. 不改代码, **契约半满足 ADR-014 R1**
  - **roadmap.md 大修**: M1.1/M1.2/M1.3/M1.7/M1.8/M1.9 checkbox 全部对齐 actual (之前 18 轮没刷, 反映的是 R7 时的视角); Phase 1 加 "actual 25+ rounds, 技术债重偿" 复盘说明; Phase 2 用 ADR-014 四条 criteria 替换模糊的 "AutoGen adapter (ADR-005 on adapter interface)" bullet (ADR-005 编号早已被 fork semantics 占用, 是 stale reference); footer 加 "drift 检测到立即刷" 规则 (吃一堑长一智)
  - (待跟进) CHANGELOG `[Unreleased]` 加 `### Added` ADR-016 + `### Changed` roadmap alignment
  - `progress/2026-04-23-round-26.md`
- **R26 为什么同时做 ADR-016 + roadmap 大修**: 用户的"每次干完活看一眼 roadmap"指令触发 reality check — 发现 roadmap.md 的 checkbox 状态停留在 R7 视角 (Phase 1 未完成但已 v0.1.6; M1.4 还写 "usage deferred to M2" 但 ADR-009/010/011/012/015 已落; Phase 2 "ADR-005 adapter interface" 实际该是 ADR-016). drift 已成 ADR-014 警告的那种病症, 必须随 ADR-016 一起修
- **ADR-014 四条必须 criteria 当前状态** (R26 后): **R1 ⚠️ 契约 ✅ / 实现 ❌** (ADR-016 定契约 R26, 实现需 ≥1 non-LangGraph adapter — 目标 R28-R29), **R2 ✅** (ADR-015), **R3 ❌** (三次 dogfood 都是 canonical, 需 adapter 双 CI), **R4 ❌** (risks doc, 目标 R27). **→ R27 (R4) → R28-R29 (R1 impl + R3) → Phase 2 R30 开**
- **R25 bundle 回顾 (仍有效)**: ADR-015 (extractor contract v2) + 四面包屑
- **R24 bundle 回顾 (仍有效)**: ADR-014 (Phase 2 entry checklist) + FORCE_COLOR conftest 修复
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
  - **`ForkPlan` schema 是 v0.1.1 对外契约**
  - **Extractor contract v2 (ADR-015) 是 v0.1.2+ 对外契约** (ADR-009/010/011/012 是历史决策 context)
  - **Adapter interface (ADR-016) 是 v0.2.0 对外契约** (R26; Phase 2 adapter 作者必读)
  - **Anthropic prompt caching 计账** (R15, ADR-015 Layer 5): cache_creation + cache_read 加到 prompt_tokens
  - **OpenAI reasoning tokens 语义** (R15, ADR-015 Layer 5): reasoning 是 completion 子字段, 不减
  - **Duck typing 原则** (R15, ADR-015 Layer 5): extractor 不 import SDK
  - **CLI 模块形状 (R14 确立)**: subcommand 实现模块暴露 `*_command(console, open_store_fn, ...)`
  - **OneAPI 配方 (R17/R18 确立)**: `model="Claude Opus 4.7"`, 不传 temperature, 响应恒包装饰性 error 字段忽略, UV_INDEX_URL=aliyun
  - **M milestone naming / multi-round bundle**: bug fix 不 bump M; release cut 单独一轮打包多个前轮
  - **Release pattern (R13/R16/R19/R22/R23 五次验证 — 已成 skill `chronos-release-pattern`)**: bump version → pyproject → CLI 状态行 → CHANGELOG → 全绿 → commit → tag -a → push main+tag
  - **Dogfood script 陷阱**: `model_name` 在 `Node.model_name`; **R21 起推荐 `n.model` 短形式**
  - **Em-dash (U+2014) / U+2212 minus 被 ruff RUF001 禁** (仅 py 源码, md 文档 OK)
  - **Pydantic v2 field-level docstring**: 字段注解行下方 `"""..."""` 即是 docstring
  - **代码生成类测试必须 `compile()` + `exec()`** (R22 教训, R23-A 实战确认): 只 compile 会漏 field-name typo / lifecycle ordering / placeholder 默认值
  - **ForkRef 字段**: `child_run_id`, `fork_id`, `node_ids` — 仅在 CM **exit** 后填
  - **SqliteStore 公开 API**: `SqliteStore.open(path)` classmethod 用作 CM
  - **LangGraph fork 语义 (R23-A 确立)**: `graph.invoke(None, {thread_id})` 续跑要求持久化且跨 run 共享的 checkpointer (`SqliteSaver.from_conn_string(...)`), 不是 per-factory-call 新 `InMemorySaver`
  - **测试环境 color 污染 (R24 确立)**: shell `FORCE_COLOR=1` 会让 rich 的 ANSI 输出打断 `CliRunner` stdout-assert; `tests/conftest.py` autouse fixture 同时清 env + rebind 两个模块级 `console`
  - **ADR consolidation 模式 (R25 确立)**: 当多个 ADR 通过 evolution 定义一个概念时, 写一个新 consolidation ADR + 在 predecessor 头部加 "Consolidated into: ADR-X" 面包屑, 保留历史决策 context 同时提供单一 source-of-truth
  - **Roadmap drift 自检 (R26 确立)**: 每轮收工前对一眼 `docs/roadmap.md`, 发现 checkbox 状态落后实际 (>5 轮未刷) 就立即刷. ADR-014 的"Phase 2 前必修"警告针对的就是这种 doc/reality divergence

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

**Round 27 候选 — R26 关了 R1 契约半, 下一个最有价值的是 R4 (risks doc), 把 Phase 2 entry 推进到 contract/doc 全齐; R1 impl + R3 dogfood 留给 R28-R29 合并做**

### R27 候选 (按 ADR-014 非绑定优先级排序, 下一轮挑一个做)

**R27 = ADR-014 criterion R4 (最推荐)**: 写 `docs/research/multi-framework-risks.md`
- 前置: R26 ✅ (ADR-016 定了 adapter 表面, 知道框架间差异在哪)
- 输入: ADR-016 的 "What actually varies across frameworks" 表 (LangGraph vs AutoGen vs CrewAI 的 6 轴) + ADR-015 Layer 4/5 的 portability matrix + 过去三次 dogfood 发现的 bug pattern
- 输出: `docs/research/multi-framework-risks.md` (~8-12 KB, research doc not ADR — ADR-014 R4 原文 "written risks doc with mitigations") 包含:
  - **R-1**: 事件模型不一致 (LangGraph 快照 vs AutoGen 消息 vs CrewAI 任务) — 抽象 leak 点在 `NodeIdentityResolver`
  - **R-2**: Fork 语义不可通用 (LangGraph `update_state(as_node=)` 依赖 checkpointer; AutoGen 无 checkpointer 概念) — mitigation: 每个 adapter 自定 seed 策略, ADR-016 `fork()` 只要求"从 parent state_after + overrides 续跑", 不限手段
  - **R-3**: Usage 计量缺口 (LangGraph callbacks 全, AutoGen `ChatResult.usage` 偶缺, CrewAI 需 per-task 挂钩) — mitigation: ADR-015 Layer 1 允许 `UsageResult=None`, Layer 4 处理 multi-call 缺口
  - **R-4**: 异步 vs 同步 (AutoGen async-first, LangGraph sync 主流) — mitigation: R27 决定是否 ADR-017 拓展 `AsyncRecorderProtocol`
  - **R-5**: 确定性回放 (LangGraph checkpointer 决定性 ≠ AutoGen agent seed 决定性) — Phase 3 问题, R27 只 flag
  - **R-6**: 侧效 tool 策略 (Phase 3 ADR-006 范畴, R27 只 flag)
- 每个 R-x 必须有: 3-sentence 描述 + mitigation + "哪个 ADR/Phase 负责解决"
- 预期: 1 轮纯研究 doc, 无代码, ~8-12 KB

**R28-R29 候选 = ADR-014 criterion R1 impl + R3 dogfood 合并做**: Phase-2 reference adapter + CI double-dogfood
- 前置: R27 ✅ (risks doc) 完成, 知道坑在哪再动手
- 输入: ADR-016 (契约) + 一个**最小可能**的 non-LangGraph "adapter" — top pick: **纯 Python linear-pipeline adapter** (没外依赖, 内存状态, 3-5 node). 理由: AutoGen 引入新 uv 依赖 (ADR-014 红线), linear-pipeline 零依赖也能证 `RecorderProtocol` 可被 non-LangGraph 实现填, 且把 CI 双 adapter dogfood 打通
- 输出: (R28) `src/chronos/adapters/linear/` 实现 `RecorderProtocol`, 20+ 测试; (R29) dogfood 脚本 `progress/dogfood-r29-double-adapter.md` 展示 record → fork plan emit → fork plan exec 在 LangGraph 和 linear 两个 adapter 上都绿, CI 跑这个脚本
- 合并做的理由: R1 impl 没 R3 dogfood 就不是真的 satisfied (ADR-014 明确 R1 "behind a feature flag + tested"); 分两轮做省 context 切换

**R30 候选 = Phase 2 正式开**: CONTEXT.md §4 refresh + 贴 Phase 2 red lines + AutoGen adapter 第一个 commit
- 前置: R27 + R28 + R29 全 ✅
- CONTEXT.md §4 重写 Phase 2 red lines (Web UI 不得 mutate 已录 run; 第三个 adapter 必须通过 ADR-016 interface; AutoGen 引入作 optional extras dependency)

**R27-prime (若 R27 中途发现 ADR-016 有 gap)**: 修 ADR-016
- 写 risks doc 时可能发现某个 risk 在 ADR-016 已覆盖但描述不清 (e.g., async 这条). 回头修 ADR-016 而不是硬顶

### R26 非目标 (继承并扩展)

- ❌ execute-fork 实现 (ADR-013 冻结, 未解除)
- ❌ `uv add autogen-agentchat` (ADR-014 R1 impl/R3/R4 未满足, Phase 2 未开)
- ❌ Web UI 任何代码
- ❌ v0.1.7 cut 在 R29 产出前 — 想把 R24+R25+R26+R27+R28+R29 bundle 成 v0.2.0-alpha (真 Phase 2 entry release)

### Release strategy

- `[Unreleased]` R24 (ADR-014 + conftest) + R25 (ADR-015 + 面包屑) 已积; R26 即将加 `### Added` ADR-016 + `### Changed` roadmap.md
- 下一个 cut 建议: R29 完成后 (Phase 2 reference adapter + CI 双 dogfood 都绿), bundle 成 **v0.2.0-alpha.1** — 标志 Phase 2 开. 到时再从 `[Unreleased]` 抽出 R24-R29 所有内容
- 按 `chronos-release-pattern` skill 走 7 步

---

### 旧 R26 计划 (已完成, 存档)

- ✅ 读 `docs/roadmap.md` 整份 (195 行) + 扫 `LangGraphRecorder` 公开表面
- ✅ 落笔 ADR-016 adapter interface (15 KB, Accepted, 3 Protocols + 5 rejected alternatives)
- ✅ roadmap.md 大修: M1.1-M1.9 checkbox 对齐实际 + Phase 2 用 ADR-014 criteria 替换模糊 bullet + footer 加 drift 自检规则
- ✅ CONTEXT.md §5/§6 + CHANGELOG [Unreleased]
- ✅ progress doc: `progress/2026-04-23-round-26.md`
- ✅ commit + push

---

### 旧 R25 计划 (已完成, 存档)

- ✅ 读 ADR-009/010/011/012 + 当前 extractor 代码 + dogfood findings
- ✅ 落笔 ADR-015 五层契约 (17 KB, Accepted)
- ✅ 四个 predecessor ADR 加 "Consolidated into" 面包屑
- ✅ CONTEXT.md §5/§6 + CHANGELOG [Unreleased]
- ✅ progress doc: `progress/2026-04-23-round-25.md`
- ✅ commit + push

---

### 旧 R24 计划 (已完成, 存档)

- ✅ ADR-014 Phase 2 entry criteria (Accepted)
- ✅ tests/conftest.py FORCE_COLOR fixture (两个 module-level console binding)
- ✅ CHANGELOG [Unreleased] + progress doc + commit + push (5a8e844)

---

### 旧 R23-A 计划 (已完成, 存档)

- ✅ 生成 stub, 发现 3 个 R22 bug
- ✅ 修 bug + 加 3 个 regression 测试 (exec-based)
- ✅ E2E 跑通: child run `16ca0fa5...` + fork `f6b36f40...` 入库
- ✅ DX 发现: checkpointer 陷阱 (交 R23-C 决定)
- ✅ progress doc: `progress/2026-04-23-round-23a.md`

---



### 旧 R22 计划 (已完成, 存档)

- ~~R22-A `chronos fork plan --emit python`~~ ✅ done (ForkPlan.to_python + CLI `--emit`, 10 tests, v0.1.5 cut)
- ~~R22-C R21 leftover (老脚本 `n.model`)~~ → 推到 R23-A 顺手做

### 旧 R21 计划 (已完成, 存档)

- ~~R21-A 写 ADR-013~~ ✅ done (Accepted)
- ~~R21-B 加 Node.model + docstring cross-ref~~ ✅ done (+~30 LOC, 3 tests)
- ~~R21-C 修老脚本~~ → 推到 R22 (可选) → 再推到 R23

---

### 更早的 R17 候选 (历史存档, 下面保留作参考)

---

**Round 17 候选** (R16 cut v0.1.3 — R14 refactor + R15 ADR-010 extractors 打包):

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
- ✅ 版本不动 (additive feature, v0.1.2 稳定; 留给 R16 cut v0.1.3)

### R16 实际产出 (2026-04-23 北京下午 17:28 起, 用户交互轮) — release cut
- ✅ `src/chronos/__init__.py::__version__` `0.1.2` → `0.1.3`
- ✅ `pyproject.toml::project.version` `0.1.2` → `0.1.3`
- ✅ `cli/__init__.py::info` 状态行 → "Phase 1 M1.11 — usage extractor hook + native Anthropic/OpenAI adapters, v0.1.3"
- ✅ `CHANGELOG.md` `[Unreleased]` → `[0.1.3] — 2026-04-23 (Round 14 + Round 15 + Round 16)`, theme "Three-extractor family + Anthropic prompt caching fidelity", 三个 sub-section (R14 refactor / R15 extractors / R16 release cut)
- ✅ `git tag -a v0.1.3` + push origin via gh-proxy.com
- ✅ 验证全绿: ruff / format / mypy / pytest 236/236 / dogfood 18/18 / `chronos info` 报 0.1.3
- ✅ M1.11 milestone 保留 (R15 是 M1.11 能力的直接扩展, 不 bump M1.12)
- ✅ 零代码逻辑改动 (纯 release packaging)

### 选项 R17-A: Fork execution engine (M2.1) — 让 `chronos fork run` 真正跑起来
- ⚠️ ADR-008 现在只到 "plan + consume in user code" 就停了; 自动执行是 Phase 1.5 → Phase 2 之间的桥
- 要新 ADR (ADR-011) 定义 "what is a safe automated fork execution", 需要 sandbox / timeout / budget 三件套
- **需要用户显式 sign-off** — 改 ADR-008 frozen 决策
- 价值最高 (项目最大卖点 beyond "better logger"), 但风险和 scope 也最大

### 选项 R17-B: LangSmith tracer callback extractor
- LangChain 的第三条 usage-accounting 路径 (另两条: `usage_metadata` / `response_metadata`, R12/R15 已覆盖)
- 作用域比 R15 更窄 (单 provider), 测试矩阵约等量
- 低风险低戏剧性的 additive feature, 1 轮可完成
- **Fallback 选项** — R17-A 用户不点头时的后备

### 选项 R17-C: AutoGen adapter (Phase 2 正式启动)
- ⚠️ **仍需用户点头**才能做 — R10 试过被抓回, 硬红线
- **必须新 ADR** (ADR-011+) AutoGen 状态模型 → Chronos NodeKind 映射

### 选项 R17-D: Web UI skeleton
- 大承诺, 一轮起不了步; **不建议 cron 轮自启**

### 选项 R17-E: 更多 tech debt 清理
- `replay.py` 391 行 / `fork.py` 367 行, 内部 helpers 还可以进一步抽 (但没到必须切的程度)

**R17 倾向**: **选项 A (if user signs off) / 选项 B (fallback)**.
- A 解锁真正的 Phase 2 进度, 是项目最大价值点, 但需要用户显式授权 fork automated execution
- B 是零戏剧性的 1 轮 ship, 补全 LangChain 三条路径的最后一条

### R17 实际产出 (2026-04-23 下午, 用户交互轮) — 真实世界 dogfood + 3 个真 bug
**走了上面都没列的第 6 条路: 选项 E = 用 Chronos 真跑一个开源 LangGraph 多 agent 项目.** 动机: "没有用户的产品谈完整性是自嗨"; 如果 dogfood 暴露出 fork-execute 的真实需求, 那就是 ADR-008 "real demand" gate 被满足; 如果没暴露, ADR-008 边界就 stay frozen — 两种结局都是证据.
- ✅ 打分选中 `langgraph-supervisor-py` (multi-agent pattern / 1566 stars / 54 open issues / 官方 semi-deprecated)
- ✅ 搭通 OneAPI + Claude Opus 4.7 (关键: 不传 `temperature`, model name 用 "Claude Opus 4.7" 带空格)
- ✅ 写 `dogfood_baseline.py` 让 supervisor 跑 FAANG headcount 查询
- ✅ **发现 Bug #1 (真 bug)**: `_coerce_state` 浅 copy, pydantic `HumanMessage` 爆 `json.dumps`. 修: 递归 `_jsonable` helper
- ✅ **发现 Bug #2 (文档缺陷)**: Chronos 静默要求 checkpointer, 文档未说, 用户见到 LangGraph 原生错误. 延迟到下轮改 onboarding
- ✅ **发现 Bug #3 (Bug #1 fix 引入的回归)**: 所有 extractor 用 `getattr(dict, "usage_metadata")` 永远拿 None → 所有 token 都是 0. 修: `_msg_field` dual-shape helper
- ✅ 6 个 regression test 全补上 (242/242 pass, 93% → 94% coverage)
- ✅ ADR-011 state-serialization-boundary 写完 (第一个由 dogfood 驱动的 ADR)
- ✅ `docs/case-studies/langgraph-supervisor.md` 第一个 case study (7.4KB, 完整故事)
- ✅ Dogfood 最终 trace: supervisor(604+107) → research_expert(1970+220) → supervisor(1049+218), per-node attribution 在真实 workload 上工作
- ⏸ 选项 A (fork-execute) **刻意不做** — R17 没有产生任何需要 auto-execute 的证据, ADR-008 边界 stay frozen
- 版本不动 (bug fix, 等 R18 一起 cut v0.1.4)
- **R17 核心教训 (写进项目 DNA)**: **236 绿测试和 3 个 showstopper bug 可以共存; 单元测试不能替代 dogfood.** R18 再次验证 — 247 绿测试里藏着一个~50% token undercount bug, 只有在真实 swarm 图上才触发

### R18 实际产出 (2026-04-23 下午晚些, 用户交互轮) — 第二次 dogfood: langgraph-swarm-py

**选定 R18-A**: `langgraph-swarm-py` (1472★ > `langgraph-reflection` 182★ 已 archive). 决策理由和执行见 `progress/2026-04-23-round-18.md`

**关键产出**:
1. **ADR-012 Multi-LLM-per-node usage accumulation** — 三 extractor 从 "last wins" 改为 "diff + sum all new AIMessages"; `UsageContext.pre_values` 自 R15 暴露后终于被用上
2. **Silent bug fix**: Bob 节点真实 token `2291+213`, 修前 `1222+99` — 漏 46% prompt / 53% completion. R17 supervisor 重跑也有 ~10% 隐性 undercount, 现在全部准确
3. **docs/case-studies/langgraph-swarm.md** — 公开的 Chronos on swarm 案例
4. **247 tests pass** (+5 ADR-012 regression)
5. **ADR-008 evidence**: R17 + R18 两轮 dogfood = 0 execute-fork 需求. 边界继续 frozen

### R19 选项 (面向未来的你)
- **R19-A (推荐)**: Cut v0.1.4 release (R17+R18 bundle, 主打"silent token bug 修复"). 按 R13/R16 已成熟的 release pattern: bump `__version__`→bump `pyproject.toml::version`→改 CLI 状态行→CHANGELOG `[Unreleased]`→`[0.1.4]`→tag→push. 1 轮搞定
- **R19-B**: 第三个 dogfood target — `langgraph-bigtool` (tool selection pattern) 或 Tavily-research-agent 组合. 继续积累 ADR-008 证据 + 多样化 graph topology
- **R19-C**: 把 R17 Finding #2 (checkpointer silent requirement) 和 R18 Finding #3 (`state_before` 缺失) 写进 `docs/getting-started.md` + 补 Recipes 文档. 0.5 轮
- **R19-D**: Package & publish to PyPI — v0.1.4 cut 后邀请真外部用户 (跳出 self-dogfood). 风险: 外部用户可能要求破坏性改动; 收益: 真反馈

**强烈推荐顺序**: A (cut v0.1.4) → 下一轮再考虑 B/C/D. Release 堆积不是好事, R17+R18 已经有两轮 unreleased fix

**硬约束 (延续)**:
- ❌ 不开始写 Web UI (除非用户点头)
- ❌ **不加 AutoGen/CrewAI adapter** — R10 试过被抓回, 硬红线, 除非用户**显式**说启动 Phase 2
- ❌ 不改 SQLite schema (R18 Finding #3 `state_before` 故意不加)
- ❌ 不动 v0.1.1 frozen 的 API 签名 (record/replay/fork/diff/fork plan CLI 命令 + `ForkPlan` schema v1)
- ❌ **不改 ADR-009 `UsageExtractor` Protocol 签名** — ADR-012 只扩展内部累加语义, 签名/返回类型/失败容忍都不动
- ❌ **不动 R14 确立的 CLI 模块形状**: subcommand 实现模块暴露 `*_command(...)` 并接受 DI; 新命令照抄
- ✅ 任何新功能 → 新 ADR (下一个编号 **ADR-013** — R18 已用掉 ADR-012)
- ✅ spike / ADR 先行纪律 9 战 9 胜 (R18 ADR-012 继续加分), 继续
- ✅ **progress doc 每轮末必写 + commit + push**
- ✅ 断言时间用 `TZ='Asia/Shanghai' date`, 别信 session 时间
- ✅ cron 实际节奏: **every 180m (3h)**; 白天用户手动交互, 晚上交给 cron
- ✅ **version bump 检查单**: 改 `__version__` 时 grep 旧 `v0.1.<prev>` / `M1.<prev>` 确保 live 文件无残留; `pyproject.toml::project.version` + CLI 状态行必须同步
- ✅ **M milestone naming**: 同一能力的 bug fix / 扩展继续沿用原 M 编号

---

*Last updated by Round 18 agent (2026-04-23 北京下午 19:30 起, 第二次 dogfood + ADR-012)*


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
