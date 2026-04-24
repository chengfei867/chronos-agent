     1|# CONTEXT.md — 未来 cron agent 的第一站 (Onboarding Entry Point)
     2|
     3|> **⚠️ 如果你是一个新启动的 cron agent，请在做任何事之前完整读完这篇文档。**
     4|> 这篇文档的唯一目的是：让失忆的"未来的你"能在 5 分钟内 100% 对齐到项目的 what / why / how。
     5|> 上下文窗口有限，这里是浓缩精华，详细内容请按本文末尾的索引跳转。
     6|
     7|---
     8|
     9|## 0. 你是谁，现在在干什么？
    10|
    11|你是 **Hermes Agent**，一个 100% AI 自主运行的开发者。
    12|你在开发一个叫 **chronos-agent** 的开源项目。
    13|你不是在跑一次性任务 —— 你是这个项目的**终身维护者**。
    14|人类用户（chengfei867）只在项目起点点了扳机，之后所有决策、代码、文档、发版都由你完成。
    15|每 4 小时 cron 会唤醒你一次，你读这份 CONTEXT.md + 最新的 progress doc 就能接着上轮继续干。
    16|
    17|**核心约束**：
    18|- 💡 你必须**保持方向一致性** —— 除非硬卡点（环境 / 权限 / 付费壁垒）才找用户，否则自主决策
    19|- 🧠 你的记忆靠**文档系统**，不靠大脑 —— 所有决定、所有进展、所有坑都要写到 `docs/` 和 `progress/`
    20|- 📝 每轮 cron 结束前必须写 `progress/YYYY-MM-DD-HHMM.md`，否则下一轮的你会失忆
    21|- 🚀 所有改动必须推到 GitHub（`https://github.com/chengfei867/chronos-agent`）
    22|
    23|---
    24|
    25|## 1. 项目是什么？(What)
    26|
    27|**Chronos Agent — Time-Travel Debugger for Multi-Agent AI Systems.**
    28|
    29|一句话定义：给多 agent 推理过程做的 "pdb + git"。
    30|
    31|### 具体能力
    32|
    33|1. **Record**：透明拦截 agent 的每一步（prompt、tool call、tool result、state 变化），形成可回放的推理树（Reasoning Tree / Run Trace）
    34|2. **Replay**：对任意历史 run，可以从任意节点**一步步回放**，看当时 agent 的思考
    35|3. **Fork**：在任意节点 checkout 出一个分支，改动其中一个 prompt / tool 定义 / LLM 模型 / temperature，**重跑下游**，得到一个平行世界的推理树
    36|4. **Diff**：两个 run（或同一个 run 的两个 fork）之间做结构化 diff —— 哪一步不一样、token 差异、cost 差异、最终 output 差异
    37|
    38|### 为什么这东西有价值
    39|
    40|- 当前多 agent 系统翻车时，debugger 只能看 trace 重新整个跑，**成本高且慢**
    41|- 改 prompt 时没人知道会不会 break 已工作的路径，全靠"祈祷"
    42|- Langfuse / Langsmith / Phoenix 等工具只做 observability（查看），不做 intervention（回放 + fork）
    43|- agent 领域没有 `pdb`，没有 `git rebase -i`，这是 2026 年的基础设施空白
    44|
    45|---
    46|
    47|## 2. 为什么是这个方向？(Why)
    48|
    49|### 2.1 空白度验证（需持续验证，不是拍脑袋）
    50|
    51|已知竞品状态（2026-04-22 snapshot）：
    52|- **Langsmith (LangChain)**：trace viewer，无 fork 能力
    53|- **Langfuse**：开源 trace，主打 observability，无 replay
    54|- **Phoenix (Arize)**：RAG / agent evaluation，无 time-travel
    55|- **AgentOps**：session replay 有，但不能 fork 重跑
    56|- **Helicone**：proxy-based logging，无 agent 语义
    57|- **Braintrust**：eval + experiment，无 reasoning tree intervention
    58|- **Laminar**：OpenTelemetry-based agent trace，有 replay viewer，无 fork
    59|- **LangGraph checkpointer**：框架层可保存 state，但**只限 LangGraph 自家生态**
    60|
    61|→ **真正的 "fork + 重跑 + diff" 在 2026.04 仍是空白**（这需要本项目的 research phase 正式核实）
    62|
    63|### 2.2 作者的独家洞察
    64|
    65|项目作者（你）之前做过一个叫 `invariantsmith` 的智能合约静态分析项目，使用了 Foundry 的 `vm.snapshot() / vm.revert()` 做状态机测试。
    66|**Foundry 对合约状态的 snapshot/revert 和本项目对 agent 状态的 snapshot/fork 在本质上是同构的。**
    67|这个跨界 insight 是项目的起点。
    68|
    69|### 2.3 技术窗口为什么是现在
    70|
    71|- MCP 协议 2024 年底标准化，agent 的 tool call 层有了统一拦截点
    72|- OpenTelemetry GenAI / Agent semconv 2025 年成型，trace 格式有了事实标准
    73|- LangGraph / AutoGen / CrewAI / Swarm 等框架的 checkpoint / state 语义开始收敛
    74|- LLM 推理 determinism 问题（seed + temperature=0）在 2025 年变得更可控
    75|- 2023-2024 做不出来是因为 "trace 格式 + agent state 抽象" 没有共识
    76|
    77|---
    78|
    79|## 3. 项目纪律 (How)
    80|
    81|### 3.1 开发铁律
    82|1. **文档先行** — 每一个决定必须有一份 ADR (`docs/decisions/ADR-xxx.md`)
    83|2. **不盲目冲刺** — 没有 research/design 支撑的 code 不能写
    84|3. **每 4 小时 cron 结束** 必须：
    85|   - 写 `progress/YYYY-MM-DD-HHMM.md`（本轮做了什么、为什么、遇到什么坑、下一轮计划）
    86|   - `git add -A && git commit && git push`
    87|   - 读一眼 `docs/CONTEXT.md`（这份文件）看有没有需要更新的全局信息
    88|4. **大方向漂移允许** —— 研究清楚后如果发现初始方向有问题，可以 pivot，但必须写 ADR 说明为什么 pivot
    89|5. **不问用户** —— 除非硬卡点（环境 / 权限 / 钱），自己拍板
    90|
    91|### 3.2 Git / GitHub 流程
    92|- 直连 GitHub 超时 —— **push 唯一可用镜像是 `gh-proxy.com`**（2026-04-22 实测）
    93|  - `gh.llkk.cc` / `gh.ddlc.top` 只能 clone/fetch/下 tarball，**不能 push**（llkk 403，ddlc 域名解析错）
    94|  - push URL 格式：`https://chengfei867:<TOKEN>@gh-proxy.com/github.com/chengfei867/chronos-agent.git`
    95|- fetch 走 `gh-proxy.com` 或 `gh.llkk.cc` 均可
    96|- 认证 token 在 `/workspace/.hermes/.env`，**永远不要 commit .env**
    97|- commit message 末尾加 `Co-authored-by: Hermes Agent <agent@hermes.ai>`
    98|- 第一阶段直接在 main 写（单人项目无需 PR），**研发到 v0.1-alpha 后**引入 PR 流程
    99|
   100|### 3.3 LLM 使用
   101|- base_url: `https://oneapi-comate.baidu-int.com`
   102|- model: `"Claude Opus 4.7"`
   103|- key: 从 `/workspace/.hermes/.env` 读 `ANTHROPIC_AUTH_TOKEN` 或 `ANTHROPIC_API_KEY`
   104|- **不要调用其它任何付费 LLM API**
   105|
   106|### 3.4 语言选择
   107|语言选型还在调研（见 `docs/decisions/ADR-001-language.md`，尚未撰写）。
   108|初步倾向：TypeScript（生态匹配 LangGraph/Vercel AI SDK）或 Python（生态匹配 AutoGen/CrewAI/大多数 agent 框架）。
   109|最终选型必须在第一阶段完成。**不要在没做 ADR 之前就开始写代码**。
   110|
   111|### 3.5 Cron 元信息
   112|- 节奏：每 4 小时一次
   113|- 交付：(1) GitHub push (2) 简短战报到 origin QQ 会话
   114|- 每轮最长：根据复杂度自适应，但 progress doc + 推送必须在 cron 结束前完成
   115|- 如果卡死：在 progress doc 里明确写 `## BLOCKED` 段，下一轮用户可能会看到
   116|
   117|---
   118|
   119|## 4. 目录结构
   120|
   121|```
   122|chronos-agent/
   123|├── README.md                      ← 对外介绍 (双语, 100% AI-generated 声明)
   124|├── docs/
   125|│   ├── CONTEXT.md                 ← 你在读的这份 (onboarding 入口)
   126|│   ├── research/                  ← 调研产出
   127|│   │   ├── competitors.md         ← 全球竞品深度调研
   128|│   │   ├── feasibility.md         ← 技术可行性调研
   129|│   │   └── risks.md               ← 风险清单
   130|│   ├── design/                    ← 设计产出
   131|│   │   ├── user-stories.md        ← 用户故事 / 场景
   132|│   │   ├── architecture.md        ← 架构文档
   133|│   │   └── diagrams/              ← Mermaid / excalidraw 图
   134|│   ├── decisions/                 ← ADR (Architecture Decision Records)
   135|│   │   ├── ADR-000-template.md
   136|│   │   ├── ADR-001-language.md    ← 语言选型
   137|│   │   ├── ADR-002-trace-format.md
   138|│   │   └── ...
   139|│   └── roadmap.md                 ← v0.1/v0.2/v0.3... 里程碑
   140|├── progress/                      ← 每轮 cron 的总结日志
   141|│   ├── 2026-04-22-round-1.md      ← 第一轮 (调研启动)
   142|│   └── ...
   143|└── (code/src 目录待 ADR-001 决定语言后创建)
   144|```
   145|
   146|---
   147|
## 5. 当前状态 (Current State)

**截至 Round 33 结束 (2026-04-24 CST 上午 user-driven) — AutoGen adapter (record-only) 首 commit 上线, ADR-017 sync-wrap 策略拍板**

- Round: **33 完成** (AutoGen adapter record-only + ADR-017)
- 最近 progress doc: `progress/2026-04-24-round-33.md` ← **下一轮必读**
- **战略定位锁死 (R33 用户确认)**: 目标是 **GitHub 爆款开源项目**, 不是 SaaS 产品. 底层能力 + DX + 文档到位, 不做多用户/托管. 这个定位直接驱动了 ADR-017 选 Path A (sync wrap) 而非 Path B (async Protocol 家族) — DX > 架构优雅.
- 当前阶段: **Phase 2 in-flight** — v0.2.0a0 released (R30); R31 (canonical protocols) + R32 (module-level instances) + R33 (AutoGen adapter) 都在 `[Unreleased]`. 3 个 adapter 都已有 module-level `AdapterProtocol` instance.
- 最新 ADR: **ADR-017 (R33)** — AutoGen sync-wrap 策略, 明确拒绝 async Protocol 家族
- 最新 research doc: `docs/research/multi-framework-risks.md` (R27 + R29 verdict) — R-4 async 风险已被 ADR-017 化解
- 最新 tag: **v0.2.0a0** (R30 cut); `[Unreleased]` 现在叠了 R31 + R32 + R33 三段
- Blocked items: 无
- 测试状态: **346/346 pass** (+10 new tests in `test_adapter_autogen.py`; mypy strict clean on 24 src files; ruff + format clean)
- CLI 表面: 未变 (R33 纯增量, 新 import `from chronos.adapters import autogen_adapter, AutoGenRecorder`)
- **R33 产出 (本轮)**:
  - `docs/decisions/ADR-017-autogen-adapter-sync-wrap.md` (~9.6 KB) — 决策 sync wrap 策略, 3-min spike 证明 `asyncio.run(team.run(...))` 返回完整 `TaskResult.messages` 足够建 Node 树; 四条否决 Path B 的理由以 DX 为首; rollback plan 明确 v0.3 可升级 `AsyncRecorderProtocol` 作 superset
  - `src/chronos/adapters/autogen/__init__.py` — `_AutoGenAdapter` class + `autogen_adapter = _AutoGenAdapter()` singleton. `name="autogen"`, `version_constraint=">=0.7,<0.8"`. `build_recorder()` 对 `usage_extractor` 非 None 抛 `AdapterError` (AutoGen 读 `models_usage` 不走 ADR-015 callback 桥); 接受 `adapter_name` via `**adapter_specific`; 未知 kwarg 抛 `AdapterError` (沿用 R32 Linear 模式)
  - `src/chronos/adapters/autogen/recorder.py` (~380 LOC) — `AutoGenRecorder` 实现 `RecorderProtocol`. `record()` sync CM yield 一个加挂 `submit_result` 方法的 `RunRef`; 用户 `asyncio.run(team.run(...))` 后调 `ref.submit_result(result)` (主路径) 或靠 `runtime.messages` fallback (副路径); CM exit 时 walk `TaskResult.messages` 建 Node, 每个 Node 的 `state_after = {"messages": [...cumulative...]}`. `fork()` 抛 `AdapterError("...See ADR-017 §Decision")` 结构性满足 Protocol 但不实现.
  - Message → NodeKind 映射: `TextMessage(source=user)` → `FN`, `TextMessage(source=assistant)` → `LLM`, `ToolCall*` → `TOOL`, `HandoffMessage` → `ROUTER`, `StopMessage` → `END`. Kind map merge-over-default, 用户只覆盖想要改的.
  - `tests/unit/test_adapter_autogen.py` (+10 tests) — duck-typed `_StubMessage`/`_StubTaskResult`/`_StubTeam`, **不 import autogen_agentchat**. 覆盖: submit_result / fallback / usage / 异常 / fork NotImpl / Protocol 一致性 / factory channel 校验
  - `src/chronos/adapters/__init__.py` 扩展暴露 `AutoGenRecorder` + `autogen_adapter`
  - `pyproject.toml` `[project.optional-dependencies].autogen` 新增 `autogen-agentchat>=0.7,<0.8` + `autogen-ext`
  - `docs/roadmap.md` Phase 2 milestones 新增 `[x] AutoGen adapter (record-only, ADR-017...)`
- **R33 关键 bug 修复 (新旧事实)**: `SqliteStore.put_run()` 用 `INSERT OR REPLACE`, SQLite 实现是 "DELETE-then-INSERT"; `nodes.run_id ON DELETE CASCADE` 意味着**同一事务里 `put_run()` 第二次会 cascade 删掉所有 Node 行**. 首次 impl 按 LangGraph 风格 write-RUNNING → insert-nodes → write-COMPLETED 直接零 Node. 修复: 事务外算好 final_state + 序列化消息列表, 事务内 put_run 恰好一次为 COMPLETED, 再 insert nodes. **教训**: 未来 adapter 永远不要同一事务里 put_run 两次; 如需中途更新 status, 加一个 `update_run_status()` 不 cascade 的 store 方法.
- **R33 战略原则确立 (新旧事实)**: 遇到"框架 API 和 Chronos Protocol 不匹配"的岔口, **先花 3 分钟 spike 验证假设是否真硬** 再决定是否动 Protocol. 本轮 spike 证明 async-first 的"硬"只是 API 表面不是架构, `asyncio.run()` 一行能 bridge, 避免了引入 `AsyncRecorderProtocol` 家族的 2x ADR/invariant 成本.
- **R32 产出 (上一轮, 回顾)**: module-level `langgraph_adapter` / `linear_adapter` singletons + 21 tests
- **R31 产出 (上上轮, 回顾)**: canonical `protocols.py` + 22 tests
- **R30 bundle 回顾 (仍有效)**: v0.2.0a0 release cut
- **R29 bundle 回顾 (仍有效)**: dual adapter dogfood
- **R28 bundle 回顾 (仍有效)**: linear reference adapter
- **R27 bundle 回顾 (仍有效)**: multi-framework risks doc
- **R26 bundle 回顾 (仍有效)**: ADR-016 adapter interface
- **R25 bundle 回顾 (仍有效)**: ADR-015 extractor contract v2
- **R24 bundle 回顾 (仍有效)**: ADR-014 Phase 2 entry checklist
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
  - **Extractor contract v2 (ADR-015) 是 v0.1.2+ 对外契约**
  - **Adapter interface (ADR-016) 是 v0.2.0 对外契约** (R26 决策, R31 canonical `protocols.py`, R32 module-level instances, R33 AutoGen 实现)
  - **AutoGen sync-wrap (ADR-017) 是 AutoGen adapter 的永久架构原则** (R33); 未来 Async superset 只能作为严格超集, 不可破坏 sync Protocol
  - **Multi-framework risks (R27 research doc) 是 v0.2.0 前必读 Phase 2 gotchas 清单** (R-4 async 已被 ADR-017 化解)
  - **Anthropic prompt caching 计账** (R15, ADR-015 Layer 5): cache_creation + cache_read 加到 prompt_tokens
  - **OpenAI reasoning tokens 语义** (R15, ADR-015 Layer 5): reasoning 是 completion 子字段, 不减
  - **Duck typing 原则** (R15, ADR-015 Layer 5): extractor 不 import SDK
  - **CLI 模块形状 (R14 确立)**: subcommand 实现模块暴露 `*_command(console, open_store_fn, ...)`
  - **OneAPI 配方 (R17/R18 确立)**: `model="Claude Opus 4.7"`, 不传 temperature, 响应恒包装饰性 error 字段忽略, UV_INDEX_URL=aliyun
  - **M milestone naming / multi-round bundle**: bug fix 不 bump M; release cut 单独一轮打包多个前轮
  - **Release pattern (R13/R16/R19/R22/R23/R30 六次验证 — skill `chronos-release-pattern`)**
  - **Dogfood script 陷阱**: `model_name` 在 `Node.model_name`; **R21 起推荐 `n.model` 短形式**
  - **Em-dash (U+2014) / U+2212 minus 被 ruff RUF001 禁** (仅 py 源码, md 文档 OK)
  - **Pydantic v2 field-level docstring**: 字段注解行下方 `"""..."""` 即是 docstring
  - **代码生成类测试必须 `compile()` + `exec()`** (R22 教训)
  - **ForkRef 字段**: `child_run_id`, `fork_id`, `node_ids` — 仅在 CM **exit** 后填
  - **SqliteStore 公开 API**: `SqliteStore.open(path)` classmethod 用作 CM
  - **LangGraph fork 语义 (R23-A 确立)**: `graph.invoke(None, {thread_id})` 续跑要求持久化且跨 run 共享的 checkpointer
  - **测试环境 color 污染 (R24 确立)**: `FORCE_COLOR` 由 `tests/conftest.py` autouse fixture 清掉
  - **ADR consolidation 模式 (R25 确立)**: consolidation ADR + predecessor 头面包屑
  - **Roadmap drift 自检 (R26 确立)**: 每轮收工前对一眼 `docs/roadmap.md`
  - **Research doc > ADR (R27 确立)**: 活内容用 `docs/research/*.md`
  - **Usage 字段边界 (R30 确立)**: `core.models.Usage` 只有 3 个 token 字段; `model_name` / `cost_usd_cents` 在 `Node` 上
  - **Release cut step 5 价值 (R30 确立)**: mypy 是最便宜的救命网
  - **Module re-export + mypy strict (R31 确立)**: 当模块 A 从 `protocols.py` import `X` 并被模块 B 再次 re-export 时, mypy strict 要求 A 模块自己加 `__all__` 显式列出 `X`
  - **AdapterProtocol build_recorder() 不适用 kwarg 处理 (R32 确立)**: 非活通道必须 `AdapterError` + 指路, 不能静默忽略
  - **SQLite `INSERT OR REPLACE` + `ON DELETE CASCADE` 陷阱 (R33 确立)**: `put_run()` 第二次会 cascade 删掉所有 Node. 同事务内 `put_run()` 只能 1 次. 如需 mid-flight status 更新, 加非 cascade 的 `update_run_status()`.
  - **假设硬度先 spike 再决策 (R33 确立)**: 遇到"框架 API 和 Chronos Protocol 不匹配"岔口, 3 分钟 minimal spike 验证硬度后再决定是否动 Protocol. 本轮用这套路避免了引入 `AsyncRecorderProtocol` 家族.

## 6. 下一轮该做什么 (Next Round TODO)

**Round 34 候选 — OSS 爆款定位下, Web UI demo 链是最高价值**

战略视角: 用户 R33 明确"GitHub 爆款 OSS 项目, 底层能力好 + DX 好即可". 5 分钟装完能看到自己 agent 的 reasoning tree = 最强安利话术. 三个 adapter 已经齐了, 现在缺的是"看得见"的这条链.

### R34-A (强推): Local HTTP API — `chronos.api.server`

- 前置: R33 ✅ (3 个 adapter 已 live, store 层已稳)
- 预估: 1 轮
- 产出:
  - `src/chronos/api/server.py` — FastAPI app. 端点最小集: `GET /runs` / `GET /runs/{id}` / `GET /runs/{id}/nodes` / `GET /runs/{id}/tree` (reasoning tree JSON, ReactFlow-friendly shape)
  - `uv add --optional web fastapi uvicorn` (optional dep)
  - 单元测试: `httpx.AsyncClient` + `TestClient`, 覆盖所有端点 happy + 404
  - **不做**: auth / CORS / pagination / streaming — 本地工具不需要
- 价值: Web UI 的必要前提; `chronos web` 命令的后端
- 风险: 低 (纯读 SqliteStore, 已知 API)

### R34-B (并行候选): `chronos web` 命令 + ReactFlow viewer 占位

- 前置: 不严格要求 R34-A, 可用 fixture data 先搭前端壳
- 预估: 1-2 轮
- 产出:
  - `src/chronos/cli/web.py` — `chronos web` subcommand, launch uvicorn + 打开浏览器
  - `src/chronos/api/static/` — 最小 React + ReactFlow SPA, 读 `/runs/{id}/tree` 画 reasoning tree
- 价值: **这就是 README 里那张 GIF 的主角**; OSS 爆款安利点
- 风险: 中 (前端涉及 bundler, 可能需要 `uv add --optional web ...` + vite)

### R34-C (可延): AutoGen integration dogfood — 真 Team.run() 跑通

- 预估: 0.5 轮
- 产出: `tests/integration/test_autogen_real.py` 标 `@pytest.mark.slow`, 用 OneAPI 跑一个 2-agent group chat, 断 Node 树形态
- 价值: 验证 R33 stub 测试 match 真相; 补 dogfood triple R3 criterion 的 AutoGen 半边 (但因 fork 没实现, 这个三元组还是不完整, 只能算 "record triple")
- 风险: 低; 如果失败说明 stub 偏离真相, 需要回去改 recorder

### R34 非目标 (继承)

- ❌ execute-fork 实现 (ADR-013 冻结未解除)
- ❌ AutoGen fork (ADR-017 §Decision 明确 Phase 3 候选)
- ❌ 多用户 / auth / 托管 — **用户 R33 明确战略红线**
- ❌ 破坏性改动 ADR-015 / ADR-016 / ADR-017 合同

### Release strategy

- `[Unreleased]` 现在叠了 R31 + R32 + R33 三个 Added/Changed/Tests 段
- 下一个 release 建议: R34-A 落完 → cut v0.2.0b0 (Web API 是 beta 自然主题), 或 R34-A+B 一起 cut v0.2.0b0
- 按 `chronos-release-pattern` skill 走 7 步

**推荐**: R34-A (Local HTTP API). 是 Web UI demo 链的后端基石, 1 轮能出活, 风险最低.

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

*Last updated: 2026-04-24 by Round 32 agent (北京上午 cron, module-level AdapterProtocol instances + CONTEXT.md 清理老 line-number 污染)*
