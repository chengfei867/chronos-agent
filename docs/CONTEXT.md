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

**截至 Round 38 结束 (2026-04-24 CST) — v0.2.0 cut/pushed, Web UI 从 beta 转正**

- Round: **38 完成** (cut `v0.2.0` bundling R36-D + R37.5 + R38). Release skill 第 8 次 clean 跑通.
- 最近 progress doc: `progress/2026-04-24-round-38.md` (Tree view polish + release cut)
- **战略定位 (R33 锁死, 持续有效)**: **GitHub 爆款开源项目**, 不是 SaaS. v0.2.0 是 Web UI 主题完备的第一个正式版 — `uv pip install chronos-agent[web]==0.2.0 && chronos web` 直接看到一个组件库级打磨的推理树 viewer.
- 当前阶段: **Phase 2 in-flight, v0.2.0 stable released** — Web UI 三轮打磨 (R36-D AntD+i18n+Tour, R37.5 多 run family tree + real-LLM smoke, R38 Legend + edge selection + ConceptTip) 形成 **"非技术读者也能看懂的时光机 viewer"** 完整叙事.
- 最新 ADR: ADR-017 (R33, AutoGen sync-wrap). R36-D/R37.5/R38 无新 ADR.
- 最新 research doc: `docs/research/multi-framework-risks.md` (R27 + R29)
- 最新 tag: **v0.2.0** (R38 cut); 下一 release 候选: v0.3.0 (Phase 3 entry, fork 可靠性 + 沙箱) 或 v0.2.1 patch
- Blocked items: 无
- 测试状态: **380/2skip pass**, 93% coverage, mypy strict clean on 26 src files, ruff + format clean
- CLI 表面: `chronos runs list/show, forks show, diff, replay, fork plan, web` (7 个 subcommand), info 命令 status line 同步到 v0.2.0
- URL 表面: `/healthz`, `/runs`, `/runs/{id}`, `/runs/{id}/nodes`, `/runs/{id}/forks`, `/runs/{id}/tree` (w/ `?include_descendants=true`), `/app/*`, `/`, `/docs`, `/redoc`
- 仓库可见性: **PUBLIC** since R34-C 尾部 (用户 grant, R10/R18/R19 私仓边界已 cleared)
- **R38 产出 (本轮)**:
  - `frontend/src/components/Legend.tsx` 新建 (~200 LOC) — 节点 kind + status + edge kind 视觉词典
  - `frontend/src/pages/TreeView.tsx`: `selectedEdgeId` state + `onEdgeClick` + `SelectedEdgePanel` 浮卡 + `<Background variant={Dots}>` 点阵底 + Step/Framework/Cost ConceptTip 包裹
  - `frontend/src/layout.ts`: edges 现在带 `data.kind`, selection 不再靠 ID 前缀字符串解析
  - `frontend/src/components/ConceptTip.tsx`: `ConceptKey` union +step +framework +timeline
  - `frontend/src/i18n/{zh,en}.ts`: `legend.*`, `tree.edge{Type,From,SelectedHint}`, `concepts.{step,framework,timeline}` 新键
  - `frontend/src/styles.css`: (初稿有 dash-flow keyframe 但被用户反馈 "违和" 后删掉, 保持 solid)
  - PR #2 squash merged → `cc5c579` on main
  - Release cut: `__version__` 0.2.0b0 → 0.2.0, `pyproject.toml::version` 同步, CLI status line "ReactFlow UI" → "ReactFlow UI polished" + v0.2.0
- **R38 关键事实**:
  - **Vision 仲裁规则 (本轮确立)**: `browser_vision` 对同一 UI 反复打分波动大 (7.5→6.5→5.5), 与 `vision_analyze` on-disk 截图打分 (8-8.5) 冲突. 新规则: 视觉争议时**不再和 vision 辩解**, 直接把截图 + 3-4 个焦点问题发用户让他判决. R38 polish 循环从估计 7 次降到 1 次.
  - **用户 UI polish 真实优先级 (本轮修正 R36-D 的"组件库级精致度"印象)**: 功能正常 + 交互流畅 > 视觉惊艳. 原话 "只要不是 bug、能力上确实、交互上逻辑有问题其实都还好". 过亮/过粗/dash-flow 动画等 "精致" 元素反而被反感.
  - **三处 version 必须同步** (老坑复习): `src/chronos/__init__.py::__version__` / `pyproject.toml::project.version` / `src/chronos/cli/__init__.py::info` status line 末尾 v 号.
  - **CSS `!important` + keyframe 在 ReactFlow 上的坑**: `.chr-edge-selected .react-flow__edge-path { stroke-dasharray: 8 6 !important; animation: ...; }` 与 fork edge 本身的 dashed 样式 clash, 表现是 fork 边不再读作 fork. 解决: 选中态只加色 + glow, 不动 dash.
- **R37.5 回顾**: `?include_descendants=true` DFS merged tree + 多 run super-lanes 布局 + `@pytest.mark.live` real-LLM smoke (progress/2026-04-24-round-37-5.md)
- **R36-D 回顾**: AntD 6 + Framer Motion + react-i18next + AntD Tour + Lucide icons full UI rewrite (progress/2026-04-24-round-36-d.md)
- **R35-A 回顾**: v0.2.0b0 release cut (Web UI beta)
- **R34-C 回顾**: ReactFlow viewer MVP + `/app` mount
- **R34-B 回顾**: `chronos web` CLI + landing page
- **R34-A 回顾**: Local HTTP API 6 endpoints
- **R33 回顾**: AutoGen adapter + ADR-017 sync-wrap
- **R32 回顾**: module-level adapter singletons
- **R31 回顾**: canonical `protocols.py`
- 旧事实 (仍生效, 不重复):
  - GitHub push 只有 `gh-proxy.com`
  - LangGraph 1.1.9 record/fork/diff 全链路 OK
  - `NodeKind` 合法值 `{llm, tool, fn, router, fork, end}`
  - Runs/Nodes upsert, Forks append-only
  - Duck + real 双测试策略
  - CLI 状态行 / `pyproject.toml::project.version` / `__version__` 每次 bump 要同步 (**R35-A + R38 验证**)
  - JSON 模式走 stdlib `print(json.dumps(...))` 不走 rich Console
  - `SqliteStore.open()` 静默建文件, 读命令守 `Path.exists()`
  - **progress doc 每轮必写**
  - **`ForkPlan` schema 是 v0.1.1 对外契约**
  - **Extractor contract v2 (ADR-015) 是 v0.1.2+ 对外契约**
  - **Adapter interface (ADR-016) 是 v0.2.0 对外契约** (R26/R31/R32/R33, **v0.2.0b0 首 ship, v0.2.0 stable 固化**)
  - **AutoGen sync-wrap (ADR-017) 是 AutoGen adapter 永久架构原则**
  - **Multi-framework risks (R27 research doc) 仍是 Phase 2 必读 gotchas**
  - **Anthropic prompt caching 计账** (R15, ADR-015 Layer 5)
  - **OpenAI reasoning tokens 语义** (R15, ADR-015 Layer 5)
  - **Duck typing 原则** (R15, ADR-015 Layer 5)
  - **CLI 模块形状 (R14)**: `*_command(console, open_store_fn, ...)`
  - **OneAPI 配方 (R17/R18)**: `model="Claude Opus 4.7"`, 不传 temperature, UV_INDEX_URL=aliyun
  - **M milestone naming / multi-round bundle**: bug fix 不 bump M; release cut 单独一轮打包多轮 (**v0.2.0 = R36-D + R37.5 + R38 三段**)
  - **Release pattern (R13/R16/R19/R22/R23/R30/R35-A/R38 八次验证 — skill `chronos-release-pattern`)**
  - **Dogfood script 陷阱**: `n.model` 短形式
  - **Em-dash (U+2014) / U+2212 minus 被 ruff RUF001 禁** (仅 py 源码, md 文档 OK)
  - **Pydantic v2 field-level docstring**: 字段注解行下方 `"""..."""` 即是 docstring
  - **代码生成类测试必须 `compile()` + `exec()`** (R22)
  - **ForkRef 字段**: `child_run_id`, `fork_id`, `node_ids` — 仅在 CM **exit** 后填
  - **SqliteStore 公开 API**: `SqliteStore.open(path)` classmethod 用作 CM
  - **LangGraph fork 语义 (R23-A)**: `graph.invoke(None, {thread_id})` 续跑要求持久化且跨 run 共享的 checkpointer
  - **测试环境 color 污染 (R24)**: `FORCE_COLOR` 由 autouse fixture 清掉
  - **ADR consolidation 模式 (R25)**: consolidation ADR + predecessor 头面包屑
  - **Roadmap drift 自检 (R26)**: 每轮收工前对一眼 `docs/roadmap.md`
  - **Research doc > ADR (R27)**: 活内容用 `docs/research/*.md`
  - **Usage 字段边界 (R30)**: `core.models.Usage` 只有 3 个 token 字段
  - **Release cut step 5 价值 (R30)**: mypy 是最便宜的救命网
  - **Module re-export + mypy strict (R31)**: A import + B re-export 时 A 要 `__all__` 显式列出
  - **AdapterProtocol build_recorder() 不适用 kwarg (R32)**: 非活通道必须 `AdapterError` + 指路
  - **SQLite `INSERT OR REPLACE` + `ON DELETE CASCADE` 陷阱 (R33)**: `put_run()` 第二次会 cascade 删 nodes
  - **假设硬度先 spike 再决策 (R33)**: 3 分钟 spike 后再决定是否动 Protocol
  - **SQLite `check_same_thread=False` 安全条件 (R34-A)**: 单连接 + autocommit + 显式 `transaction()` CM + 只 FastAPI 读才开
  - **API shape 框架中立原则 (R34-A)**: contract 端点 shape 不 bake-in 任何前端框架
  - **Post-compaction diff 自检 (R34-A)**: compaction 重启后先 `git diff` 看代码真相
  - **CLI 模块 DI seam 模式 (R34-B)**: 副作用函数走 optional kwarg + module-level default wrapper
  - **Lazy optional-extra import (R34-B)**: `pkg --help` 必须不炸, 重依赖 import 延迟
  - **uvicorn browser-open timing (R34-B)**: `threading.Timer(1.0, ...)` daemon
  - **npm install devDep 跳过陷阱 (R34-C)**: 首次 `npm install` 可能只装 prod
  - **`.gitignore` 白名单必须 EOF (R34-C)**: last-match-wins
  - **Fixture + monkeypatch 时序 (R34-C)**: 顶层 fixture 已构造后 monkeypatch env 需建 FRESH client
  - **`@xyflow/react` v12 替代 `reactflow` v11 (R34-C)**
  - **AntD v6 `App` context message/notification static 方法坑 (R36-D)**: 见 skill `antd-v6-app-pitfalls`
  - **Browser visual review 必须, 不可选 (R37.5)**: 接口绿 ≠ 用户看到的对. R37.5-C3 抓到 `stroke: none` bug 活在 main 多轮就是 API 绿但 CSS 变量没解析
  - **i18next 复数 key (R37.5)**: `foo_one` / `foo_other` 走 ICU plural, zh 无复数规则单形式
  - **ReactFlow v12 `useViewport` hook (R37.5)**: 写 Pan/zoom 跟随的背景 overlay 用它
  - **Vision 仲裁规则 (R38)**: `browser_vision` 反复波动时, 截图 + 焦点问题 → 用户判决, 不辩解
  - **UI polish 真实优先级 (R38)**: 功能 + 流畅 > 视觉惊艳. 过亮/过粗/dash 动画反被反感
  - **ReactFlow `.chr-edge-selected` + CSS keyframe dash-flow 与 fork dashed 冲突 (R38)**: 选中态只用色 + glow, 别动 stroke-dasharray

## 6. 下一轮该做什么 (Next Round TODO)

**Round 39 候选 — v0.2.0 stable 已 release, Phase 2 Web UI 主题基本完备**

战略视角: v0.2.0 把 Web UI 从 "能用的 MVP" 推到 "组件库级打磨的成品". 下一步两个方向:
- **深化体验**: diff viewer (当初 R36-A 计划没做就被 polish 压下去了) 把时光机叙事第三个动词 "分叉" 可视化
- **Phase 3 前哨**: fork 可靠性 + side-effect 沙箱 (roadmap §Phase 3)

### R39-A (首选): Diff viewer (当初 R36-A 欠账)

- 前置: v0.2.0 ✅
- 目标: `#/runs/<a>/diff/<b>` 双 tree 并排 + node-level `cost_usd_cents` / `usage` / `extracted` / `state_after` diff 高亮
- 后端: `GET /runs/compare?a=X&b=Y` 返 `{tree_a, tree_b, node_alignment}` (alignment 按 `node_name` or `kind+step_index`)
- 前端: 复用 TreeView layout, 新页面双 ReactFlow 侧边对比, NodeDetails 切 diff 模式红绿高亮
- 工期估: 1 轮 (R34-C + R36-D + R37.5 + R38 打的地基全能复用)
- 叙事: 把 README 的 "record / browse / fork" 三动词补齐 "compare" 第四动词, 这是时光机用户真问的问题 "换个 prompt 结果差多少"

### R39-B (可延): GitHub release page + README 截图

- v0.2.0 tag 已 push 但 GitHub Release page 没建. REST API `POST /repos/chengfei867/chronos-agent/releases` body 从 CHANGELOG 搬
- README 头部加 2-3 张 TreeView + multi-run family tree + Legend 截图 (不做 GIF — 截图成本低, GIF 录制链条容易挂)
- vhs / asciinema 录 CLI demo 放 README 尾部

### R39-C (可延): `chronos compare` CLI subcommand

- 光有 Web viewer 的 diff 不够, CLI 用户也要. 新 subcommand `chronos compare <run_a> <run_b>` print 表格 diff
- 前置: R39-A 后端 `GET /runs/compare` 先落地 (CLI 直接调 store 层, 不经 HTTP)

### R39 非目标 (继承 R33 红线)

- ❌ 多用户 / auth / 托管
- ❌ 数据库 migration 框架
- ❌ gRPC / GraphQL
- ❌ 多 SQLite 后端 (Postgres/Turso)
- ❌ WebSocket 实时推送
- ❌ PyPI publish (R36-C 搁置原因 "发了就有 support 负担" 仍有效, 等真有用户问再说)

### Release strategy (R39 后)

- R39-A diff viewer + R39-B release page + R39-C CLI compare + 一轮 dogfood = **v0.2.1 patch** (Phase 2 收尾)
- Phase 3 开 v0.3.0 = fork 可靠性 + side-effect 沙箱 (roadmap §Phase 3)

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
