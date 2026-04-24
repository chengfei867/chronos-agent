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

**截至 Round 34-B 结束 (2026-04-24 CST 中午, user-driven) — `chronos web` 一键启动 + 深色落地页, Web UI demo 链的前端上半段就位**

- Round: **34-B 完成** (`chronos web` CLI + `/` landing page). R34-A 后端 + R34-B CLI 合起来构成了 "5 分钟 quickstart" 故事链里**除浏览器可视化之外**的全部部件.
- 最近 progress doc: `progress/2026-04-24-round-34.md` (R34-A + R34-B 两段, 371 行) ← **下一轮必读**
- **战略定位 (R33 用户锁死, 持续有效)**: **GitHub 爆款开源项目**, 不是 SaaS. R34-B 的每个决策(depth-friendly 单命令 on-ramp, 深色落地页 palette 对齐 README, 裸装不崩 `chronos --help`)都是在服务这条线.
- 当前阶段: **Phase 2 in-flight** — v0.2.0a0 released (R30); `[Unreleased]` 叠了 R31 + R32 + R33 + R34-A + **R34-B** 五段, 够打 v0.2.0b0 了
- 最新 ADR: **ADR-017 (R33)** — AutoGen sync-wrap 策略 (R34-A/B 无新 ADR, 设计决策进 `web.py` module docstring + progress doc)
- 最新 research doc: `docs/research/multi-framework-risks.md` (R27 + R29)
- 最新 tag: **v0.2.0a0** (R30 cut); 下一 release 候选: R34-A + R34-B (+ 可能 R34-C) 一起打 **v0.2.0b0**
- Blocked items: 无
- 测试状态: **371/371 pass** (+8 new tests in `test_cli_web.py`; mypy strict clean on 26 src files; ruff + format clean)
- CLI 表面: **+1 subcommand (`chronos web`)**, 信息架构跟其他 subcommand 完全对齐 (`--db / $CHRONOS_DB / ./chronos.db` 三级回退, DI seams 一致)
- **R34-B 产出 (本轮)**:
  - `src/chronos/cli/web.py` (~180 LOC) — `web_command(host, port, db, no_browser, open_store_fn, console, run_server_fn=None, open_browser_fn=None)`. `_default_run_server` / `_default_open_browser` module-level wrappers 作为 DI 默认值 (测试注 spy 不装 mock lib). Lazy `import uvicorn` 在 `_default_run_server` 内, 裸装 `chronos --help` 不炸. `threading.Timer(1.0, ...)` daemon 延迟开浏览器 (uvicorn 无 after-startup hook). `webbrowser.open()` 返 `False` 时打提示不炸. Store 生命周期 `open → build_app → run_server → close()` 用 `finally` + `contextlib.suppress(Exception)` 包.
  - `src/chronos/api/server.py` — `@app.get("/", include_in_schema=False)` + `_INDEX_HTML` module constant (~60 行 dark-theme HTML, palette 对齐 README `#0d1117`, 链出 6 个端点 + `/docs` + `/redoc` + CLI equivalents; 零外部 asset, 零 JS build step).
  - `src/chronos/cli/__init__.py` — `@app.command("web")` wrapper + docstring command surface + `info` 命令列表同步加 `web`.
  - `src/chronos/cli/_common.py` — `_resolve_db_path` 仍是私有名 (下划线前缀), `web.py` 直接 import 使用.
  - `tests/unit/test_cli_web.py` (+8 tests) — `TestWebCommand` direct-call + spy DI; `TestWebCLI` CliRunner + `monkeypatch.setattr` on module-level defaults. 覆盖 default/custom host&port, browser-open timing (sleep 1.2s 等 Timer), `--no-browser` 短路, `webbrowser.open` 返 `False` 的 graceful 路径, 缺 DB → `typer.Exit`, `--help` 不需要 `[web]` extra (pin lazy-import 设计).
  - **Live smoke**: `chronos web --db /tmp/smoke.db --port 18766 --no-browser` 起 bg process → `/healthz` → `{"status":"ok","schema_version":"0.1.0"}`, `/` → 200/2525 bytes, `/runs` → `{"runs":[],"count":0}`.
  - `README.md` 英+中 quickstart 各加 `uv pip install 'chronos-agent[web]' && chronos web --db ...` 第三步.
  - `docs/cli-reference.md` 加完整 `chronos web` section (flag 表 + endpoint 表 + landing page 描述 + SSH port-forward recipe for 远程).
  - `docs/roadmap.md` 勾 `[x] chronos web command launches local server + opens browser` 并注明实现细节.
  - `CHANGELOG.md` `[Unreleased]` 下加 R34-B Added/Design/Tests 三段.
- **R34-B 关键设计决策**:
  - **DI seams via optional `run_server_fn` / `open_browser_fn`** — 不引 `unittest.mock`, 跟其他 CLI 模块 (`open_store_fn`, `console`) 同款 pattern. 测试二分: 直调 (spy 注参) + CliRunner (`monkeypatch.setattr` 改 module-level defaults).
  - **Lazy uvicorn import 在 `_default_run_server` 里**, 不在模块顶部. 裸装用户 `chronos --help` 和每个非 web 子命令都能跑; 只有 `chronos web` 被调才检查 `[web]` extra, 缺了给友好提示而不是 ImportError 栈.
  - **不支持 `reload=True`** — uvicorn reloader spawn subprocess re-import 模块路径, closure-bound store 会丢. `chronos web` 是 inspection tool, 不是 `server.py` 的 dev server. 要 reload 的用户直接 `uvicorn your_module:create_app --factory` 自己包 —— `build_app(store)` 是 public API.
  - **Timer(1.0) 延迟开浏览器** — uvicorn 公开 API 没有 caller-side "after startup" hook (不继承 `Server` 的话). 1 秒在 loopback bind 的经验值是够的, 测试 sleep 1.2s 等 Timer 触发再 assert spy.
  - **Banner 自己 resolve path, 不读 `store._path`** — `SqliteStore` 没 `_path` 属性, 我们用 `_resolve_db_path(db)` 自己算一遍, banner 才能真诚显示 `$CHRONOS_DB` 或默认 cwd 回退路径.
- **R34-B 教训 (新事实)**:
  - **Watch-pattern 通知可能迟到**: background process 已 kill 后, `watch_patterns` 匹配的通知仍会异步到达. 规则: 看到 "Uvicorn running on ..." 类通知时先 `ss -tlnp` 确认端口是否真绑, 别条件反射去 kill.
  - **Typer cosmetic quirk**: docstring 里带 `[web]` 这种方括号子段落会被 `--help` 输出 strip 掉 (典型 Typer rich-markup 处理). 无功能影响, 但写 CLI help 时避免在命令 surface 列表里放带 `[...]` 的词.
- **R34-A 产出 (上一段, 回顾)**: Local HTTP API, 6 endpoints, neutral tree shape, 17 tests
- **R33 产出 (上一轮, 回顾)**: AutoGen adapter record-only + ADR-017 sync-wrap
- **R32 产出 (上上轮, 回顾)**: module-level `langgraph_adapter` / `linear_adapter` singletons
- **R31 产出 (回顾)**: canonical `protocols.py`
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
  - **Adapter interface (ADR-016) 是 v0.2.0 对外契约** (R26 决策, R31 canonical, R32 module-level instances, R33 AutoGen 实现, **R34-A/B 无侵犯**)
  - **AutoGen sync-wrap (ADR-017) 是 AutoGen adapter 永久架构原则** (R33)
  - **Multi-framework risks (R27 research doc) 仍是 Phase 2 必读 gotchas**
  - **Anthropic prompt caching 计账** (R15, ADR-015 Layer 5)
  - **OpenAI reasoning tokens 语义** (R15, ADR-015 Layer 5)
  - **Duck typing 原则** (R15, ADR-015 Layer 5)
  - **CLI 模块形状 (R14 确立)**: subcommand 实现模块暴露 `*_command(console, open_store_fn, ...)` (R34-B `web_command` 完全沿用)
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
  - **SQLite `check_same_thread=False` 安全条件 (R34-A 确立)**: 单连接 + autocommit + 显式 `transaction()` CM + 只 FastAPI 读才开
  - **API shape 框架中立原则 (R34-A 确立)**: contract 端点 shape 不 bake-in 任何前端框架, 前端 transform
  - **Post-compaction diff 自检 (R34-A 确立)**: context compaction 重启后 CHANGELOG/progress/code 可能脱钩, 先 `git diff` 看代码真相
  - **CLI 模块 DI seam 模式 (R34-B 强化)**: 副作用函数 (`run_server`, `open_browser`) 走 optional kwarg + module-level default wrapper, 测试直注 spy
  - **Lazy optional-extra import (R34-B 确立)**: `uv pip install pkg` (无 extra) 后 `pkg --help` 必须不炸. 重型 optional 依赖 (uvicorn/fastapi) import 延迟到真被调的命令内
  - **uvicorn browser-open timing (R34-B 确立)**: `threading.Timer(1.0, ...)` daemon 替代不存在的 after-startup hook; 1s loopback 经验足够
  - **Watch-pattern 通知异步 (R34-B 教训)**: 看到 "Uvicorn running" 类通知先查端口是否真绑

## 6. 下一轮该做什么 (Next Round TODO)

**Round 34-C 候选 — ReactFlow 前端 MVP 吃 `/runs/{id}/tree`, 让 README GIF 有主角**

战略视角: R33 OSS 爆款定位 → R34-A 后端 + R34-B CLI + 深色落地页已经把 "pip install → chronos web → 浏览器打开" 这条链打通. 现在缺的是落地页上除 `/docs` 之外**真正的可视化** —— ReactFlow 吃 `/tree` 渲染推理树, 这才是 README GIF 里让人第一眼 "wow" 的画面.

### R34-C (强推): ReactFlow 前端 MVP

- 前置: R34-A ✅ + R34-B ✅ (API + CLI + 落地页 deps 都就绪)
- 目标: 能在 `/app` (或 `/viewer`) 渲染一个 run 的 reasoning tree, 节点可点开看 content/state_after, fork 边虚线标记, 叶 run 无 node 时渲 "unresolved branch"
- 实现路径三选一, 各有利弊:
  - **Path A: 同仓 `frontend/` 子目录 + Vite + 预构建 `dist/` 进 git** — 最简单, 但静态产物入 git 不干净; Python 包再把 `dist/` `package_data` 进去
  - **Path B: 同仓 `frontend/` + GitHub Actions build on release + artifact 下发** — 干净, 但 CI/CD 要 setup, 而且本地开发需要先 `npm run build`
  - **Path C: 完全 CDN-hosted SPA** (GitHub Pages 挂 `chronos-viewer`, 落地页点链接跳出去, 带 `?api=http://localhost:8765` 参数) — 最 decouple, 但跨域 + 两个仓库两套 issue tracker
- 决策倾向: **Path A 先** (最快到 GIF), Path C 作为长期目标
- 技术栈: Vite + React 18 + TypeScript + ReactFlow 12 + Zustand (state) + 原生 fetch (不引 react-query 第一版)
- 覆盖范围 (MVP 红线内):
  - 登录页/run 列表 ← fetch `/runs`, 点一个跳 tree 页
  - Tree 页 ← fetch `/runs/{id}/tree`, ReactFlow 画 DAG, 分 `sequential` 实线 / `fork` 虚线
  - Node 详情抽屉 ← 点 node 右滑抽屉, 展 `content_preview` / `usage` / `extracted` / `error`
  - Fork 边 hover tooltip 展 `edited_fields`
- 非目标 (砍掉不做):
  - 用户登录 / 权限 / 多用户 (OSS, 不做 SaaS)
  - 编辑功能 (只读 viewer)
  - Replay 触发按钮 (CLI 已经 replay, web 端不急)
  - 实时 WebSocket (每次刷新一整棵树就够)

### R34-D (可延): README GIF / demo 录制

- 用 `vhs` 或 `asciinema + agg` 录 CLI 段 (recorder 建库 → 列 run → 起 web)
- 浏览器段用 OS 自带录屏或 `peek`, 同分辨率
- `ffmpeg` 拼接 + 压帧, 目标 ≤ 3MB
- 放 `assets/demo.gif`, README 头部引用
- 这轮是否要做 **取决于 R34-C 做到哪一步** —— 如果 R34-C 出最小可视化即可出 GIF, 就顺手录

### R34 非目标 (继承 R33 红线)

- ❌ 多用户 / auth / 托管
- ❌ 数据库 migration 框架 (用 schema_version + 手动 migration scripts 就够)
- ❌ gRPC / GraphQL (REST 够用)
- ❌ 多 SQLite 后端 (Postgres/Turso 先不做)

### Release strategy (R34 结束后)

- R34-A + R34-B + R34-C 凑齐 Web UI 完整链 → cut **v0.2.0b0** (beta, 主题 = Web UI)
- 或者 R34-B 结束当下就 cut 一个 **v0.2.0a1** (alpha 小修, 主题 = Local HTTP API + CLI), 把 R34-C 留到 v0.2.0b0. **倾向后者** —— 灰色 beta 门槛低, 用户早点拿到 `chronos web`, 把 "ReactFlow 还没做" 这件事藏在 beta 之前, 避免显得"没做完就发".
- 后续 v0.2.0 stable = ReactFlow + dogfood + GIF + 改一轮 README 再发

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
