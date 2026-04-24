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

**截至 Round 34-A 结束 (2026-04-24 CST 中午, user-driven) — Local HTTP API 上线, Web UI demo 链的后端基石就位**

- Round: **34-A 完成** (Local HTTP API — 6 个 FastAPI 端点 over SqliteStore, neutral reasoning-tree shape)
- 最近 progress doc: `progress/2026-04-24-round-34.md` ← **下一轮必读**
- **战略定位 (R33 用户锁死, 本轮继续)**: **GitHub 爆款开源项目**, 不是 SaaS. 底层能力 + DX + 文档到位即可, 不做多用户 / 托管. R34-A 的端点设计全部遵循此红线 (no auth, no CORS, no pagination beyond `limit`, no streaming).
- 当前阶段: **Phase 2 in-flight** — v0.2.0a0 released (R30); `[Unreleased]` 叠了 R31 + R32 + R33 + **R34-A** 四段
- 最新 ADR: **ADR-017 (R33)** — AutoGen sync-wrap 策略 (R34-A 无新 ADR, 设计决策写进 `server.py` 模块 docstring + progress doc)
- 最新 research doc: `docs/research/multi-framework-risks.md` (R27 + R29)
- 最新 tag: **v0.2.0a0** (R30 cut); 下一 release 候选: R34-A+R34-B 一起打 **v0.2.0b0** (Web API 是 beta 的自然主题)
- Blocked items: 无
- 测试状态: **363/363 pass** (+17 new tests in `test_api_server.py`; mypy strict clean on 26 src files; ruff + format clean)
- CLI 表面: 未变 (R34-A 纯后端; `chronos web` 命令是 R34-B 的事); 新 import `from chronos.api import build_app`
- **R34-A 产出 (本轮)**:
  - `src/chronos/api/server.py` (~230 LOC) — `build_app(store: SqliteStore) -> FastAPI` 工厂. 6 个端点: `GET /healthz` (status + schema_version); `GET /runs?limit=N` (1 ≤ limit ≤ 1000, 否则 422); `GET /runs/{id}` (run + 有序 nodes, 404 if missing); `GET /runs/{id}/nodes` (仅 nodes, 404-strict on run); `GET /runs/{id}/forks` (本 run 作为 parent 的所有 forks, 叶子 run 返 200+count=0 不 404); `GET /runs/{id}/tree` (**contract endpoint** — neutral reasoning-tree shape). 响应统一用 `pydantic.model_dump(mode="json")` 自动处理 datetime/StrEnum.
  - `src/chronos/api/__init__.py` — re-export `build_app`
  - `src/chronos/store/sqlite.py` 两改: (1) 新方法 `get_forks_for_parent(parent_run_id) -> list[Fork]` 镜像 `get_fork_for_child`; (2) `SqliteStore.open()` 在 `sqlite3.connect()` 加 `check_same_thread=False` (Python 层 guard; SQLite 引擎 serialized-thread-safe, 我们单连接 autocommit + 显式 `transaction()` CM, 安全). 新加 10 行 inline comment 说明 rationale.
  - `tests/unit/test_api_server.py` (+17 tests) — 真 temp-file `SqliteStore` 播种 two-run fork 场景 (parent 3 nodes → fork → child 2 nodes), 全部 6 个端点 × happy/404 轴覆盖, 无 mock. `build_app` factory isolation 单测 (两 app 两 store 不串).
  - `pyproject.toml`: `[project.optional-dependencies].web` = `fastapi>=0.110`, `uvicorn[standard]>=0.30`, `httpx>=0.27`. mypy override 为 `fastapi.* / starlette.* / uvicorn.* / httpx.*` 全部 `ignore_missing_imports=true` (web extra 非必装).
  - `CHANGELOG.md` / `docs/roadmap.md` — R34-A 段 + roadmap 勾 `[x] Local HTTP API`
- **R34-A 关键设计决策**:
  - **Neutral tree shape, not ReactFlow-specific** — `/tree` 返 `{run_id, nodes, edges, child_runs}`, edges 两种 kind (`sequential` 同 run parent-child, `fork` 跨 run), 子 run 无 node 时 `to: null` 让前端画 "unresolved branch". ReactFlow/Mermaid/D3/Cytoscape 都能消费.
  - **Sync handlers + `check_same_thread=False`** > `async def` handlers. 前者是 FastAPI+SQLite idiom (thread pool 吞 blocking I/O 不阻 loop); 后者会把 sqlite 读阻塞在 event loop 上.
  - **`build_app(store)` factory, no module-level `app`** — 每次新实例, 防 "全局 app + 全局 state" 反模式. 测试 `test_build_app_binds_distinct_stores` 显式断两 app 不串.
- **R34-A 教训 (新旧事实)**:
  - **Post-compaction CHANGELOG drift 必自检**: 上一窗口合并/重启时已经在 CHANGELOG 写了 R34-A entries 描述 4 endpoints + ReactFlow shape + `async def` + `ASGITransport`; 本窗口实现的是 6 endpoints + neutral shape + sync `def` + `TestClient` + `check_same_thread=False`. 不对齐就 commit = 文档和代码两张脸. **规则**: 每次从 context compaction 恢复后先 `git diff` 对比代码事实, 不是 summary 事实.
  - **SQLite `check_same_thread` 只有 FastAPI 读到 store 那一刻才暴露**. 纯 `build_app()` 构造 + route 列表 check 都过, 第一个真读 store 的 endpoint 测试才 raise. 规则: 至少有一个端到端 endpoint-hits-store 测试再宣布 harness 可用.
- **R33 产出 (上一轮, 回顾)**: AutoGen adapter record-only + ADR-017 sync-wrap
- **R32 产出 (上上轮, 回顾)**: module-level `langgraph_adapter` / `linear_adapter` singletons
- **R31 产出 (上上上轮, 回顾)**: canonical `protocols.py`
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
  - **Adapter interface (ADR-016) 是 v0.2.0 对外契约** (R26 决策, R31 canonical `protocols.py`, R32 module-level instances, R33 AutoGen 实现, **R34-A 无侵犯**)
  - **AutoGen sync-wrap (ADR-017) 是 AutoGen adapter 永久架构原则** (R33)
  - **Multi-framework risks (R27 research doc) 仍是 Phase 2 必读 gotchas**
  - **Anthropic prompt caching 计账** (R15, ADR-015 Layer 5)
  - **OpenAI reasoning tokens 语义** (R15, ADR-015 Layer 5)
  - **Duck typing 原则** (R15, ADR-015 Layer 5)
  - **CLI 模块形状 (R14 确立)**: subcommand 实现模块暴露 `*_command(console, open_store_fn, ...)`
  - **OneAPI 配方 (R17/R18 确立)**: `model="Claude Opus 4.7"`, 不传 temperature, UV_INDEX_URL=aliyun
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
  - **Usage 字段边界 (R30 确立)**: `core.models.Usage` 只有 3 个 token 字段
  - **Release cut step 5 价值 (R30 确立)**: mypy 是最便宜的救命网
  - **Module re-export + mypy strict (R31 确立)**: A 模块 import + B re-export 时 A 要 `__all__` 显式列出
  - **AdapterProtocol build_recorder() 不适用 kwarg (R32 确立)**: 非活通道必须 `AdapterError` + 指路
  - **SQLite `INSERT OR REPLACE` + `ON DELETE CASCADE` 陷阱 (R33 确立)**: `put_run()` 第二次会 cascade 删 nodes
  - **假设硬度先 spike 再决策 (R33 确立)**: 3 分钟 minimal spike 后再决定是否动 Protocol
  - **SQLite `check_same_thread=False` 安全条件 (R34-A 确立)**: 单连接 + autocommit + 显式 `transaction()` CM + 只 FastAPI 读才开; SQLite 引擎自身 serialized-thread-safe, Python 层 guard 是 belt-and-suspenders
  - **API shape 框架中立原则 (R34-A 确立)**: `/tree` 等 contract 端点 shape 不 bake-in 任何前端框架 (ReactFlow/Mermaid/D3...), 让前端做 transform. 否则一张 JPEG 锁死一个 viewer.
  - **Post-compaction diff 自检 (R34-A 确立)**: context compaction 重启后, CHANGELOG / progress doc / code 的 "plan" 和 "reality" 可能脱钩. 每次先 `git diff` 看代码真相再 commit.

## 6. 下一轮该做什么 (Next Round TODO)

**Round 34-B 候选 — `chronos web` 命令 + Web UI demo 链的最后一公里**

战略视角: R33 用户定调 OSS 爆款定位. R34-A 后端已出活, "看得见 reasoning tree" 这条链只差两步: (1) `chronos web` 一键启动, (2) ReactFlow 前端吃 `/runs/{id}/tree`. 5 分钟 `pip install chronos-agent[web] && chronos agent-run ... && chronos web` 看到树 = README GIF 的主角 = 星星引擎.

### R34-B (强推): `chronos web` CLI 命令

- 前置: R34-A ✅ (build_app 已稳; pyproject web extra 已加)
- 预估: 0.5-1 轮
- 产出:
  - `src/chronos/cli/web.py` — Typer subcommand `chronos web [--db PATH] [--port N] [--no-browser] [--host HOST]`. 打开 `SqliteStore`, `build_app(store)`, 调 `uvicorn.run()`. 可选 `webbrowser.open()`.
  - CLI 集成点: `src/chronos/cli/__init__.py` 注册新子命令, 更新 help
  - 单元测试: `tests/unit/test_cli_web.py` — mock `uvicorn.Server` (不真 bind 端口, 测 arg wiring + DB 打开正确 + 不存在 DB 友好报错)
  - `README.md` quickstart 段落加 `chronos web` 示例
- 价值: **"5-min quickstart" 的最后一步**; 不需要前端也能用 curl + HTTPie 看树
- 风险: 低 (uvicorn API 稳定; CLI pattern 已有 6 个先例)
- 潜在坑: port 冲突 (默认 8127 或类似小众端口避让); Windows `webbrowser.open` 行为差异 (暂不管, Linux/mac 优先)

### R34-C (强推, R34-B 后): ReactFlow 前端 MVP

- 前置: R34-A ✅ + R34-B ✅
- 预估: 2-3 轮 (前端工作量大)
- 产出:
  - `frontend/` 新目录 (或独立 repo chronos-web?); Vite + React + TypeScript + ReactFlow
  - 最小功能: run list sidebar + 选 run 后中间画 reasoning tree + 点 node 看 state_after JSON
  - build 产物 inline 进 `src/chronos/api/static/` (pyproject `[tool.hatch.build.targets.wheel].force-include` 带上)
  - `server.py` mount `StaticFiles(directory="static")` on `/`
  - E2E 手测: 跑 LangGraph adapter 出 run → `chronos web` → 浏览器看树
- 价值: **README GIF 主角**
- 风险: 中 (前端 toolchain 在沙箱环境里可能不顺; 可能需要独立 repo 手动 build 后 vendor 产物进 chronos); 数据量大时 ReactFlow 性能 (暂不管, 后期再优)
- **开工前必讨论**: 前端要不要放同仓? 放同仓包袱大, 独立仓口碑营销分散; 倾向同仓 vendor 构建产物.

### R34-D (可延): AutoGen real-world dogfood

- 预估: 0.5 轮
- 产出: `tests/integration/test_autogen_real.py` 标 `@pytest.mark.slow`, OneAPI 跑真 2-agent group chat, 断 Node 树形态
- 价值: 补 "record triple" criterion 的 AutoGen 半边

### R34 非目标 (继承)

- ❌ execute-fork 实现 (ADR-013 冻结未解除)
- ❌ AutoGen fork (ADR-017 §Decision 明确 Phase 3 候选)
- ❌ 多用户 / auth / 托管 — **用户 R33 明确战略红线**
- ❌ 破坏性改动 ADR-015 / ADR-016 / ADR-017 合同
- ❌ 给 Local HTTP API 加 CORS / WebSocket / 写端点 — **R34-A 明确战略范围红线**

### Release strategy

- `[Unreleased]` 现叠 R31 + R32 + R33 + R34-A 四段
- 下一 release: **R34-A + R34-B + R34-C 一起 cut v0.2.0b0** ("Web UI beta" 是自然 milestone). R34-D 不 block.
- 按 `chronos-release-pattern` skill 走 7 步

**推荐**: 直接干 R34-B. 0.5-1 轮出活, 把 "后端装好了但没 CLI 启动方式" 的尴尬 gap 补掉, 之后再启动 R34-C 前端。如果用户想要 "一次性把能见的都见到", 也可以 R34-B + R34-C 并行规划但 B 先 ship.

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
