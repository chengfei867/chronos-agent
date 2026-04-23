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

**截至 Round 21 结束 (2026-04-23 20:20 CST, 用户交互轮) — v0.1.4 保持; ADR-013 landed; Node.model alias landed; [Unreleased] 攒段**

- Round: **21 完成** (R19 v0.1.4 release → R20 dogfood #3 bigtool + findings → **R21 ADR-013 + Node.model alias + 3 guardrail tests**)
- 最近 progress doc: `progress/2026-04-23-round-21.md` ← **下一轮必读**; R20 在 `progress/2026-04-23-round-20.md`
- 当前阶段: **Phase 1 + 三轮 dogfood + ADR-013 边界明确 + DX polish landed; [Unreleased] 攒 R21 内容等后续 release cut**
- 最新 ADR: **ADR-013 (R21) — fork auto-execution stays frozen, 三轮 dogfood 证据**
- 最新 tag: v0.1.4 (不动)
- Blocked items: 无
- 测试状态: **250/250 pass, 93% coverage** (R20 247 → R21 250, 新增 3 个 Node.model + Usage guardrail 测试)
- CLI 表面: 未变
- **R21 产出 (ADR + 小 API 加法)**:
  - `docs/decisions/ADR-013-fork-auto-execution-stay-frozen.md` (新, Accepted)
  - `src/chronos/core/models.py`: `Usage` 加 cross-ref docstring; `Node.usage` 字段加 inline docstring; `Node.model` property alias (+~30 LOC)
  - `tests/unit/test_models.py`: 3 个新测试 (property 正路径 + null-safety + `Usage.model_name` 不存在 guardrail)
  - `CHANGELOG.md`: `[Unreleased]` 新增 R21 段
  - `progress/2026-04-23-round-21.md`
- **R21 不 bump 版本的理由**: 改动太小 (~30 LOC + 1 ADR), v0.1.4 刚 cut 6 小时, 攒到下一轮有实质内容再 cut v0.1.5
- **ADR-008 boundary 官方冻结** (ADR-013 formalizes): 三轮 dogfood × 三种正交 topology × 0 execute-fork 需求; trigger conditions 明确; 可逆但需要新证据
- **Dogfood topology 三角定型**: R17 centralized / R18 decentralized / R20 single-agent+meta-tool
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
  - **ADR-009 usage extractor 协议是 v0.1.2 对外契约** (ADR-012 扩展不改签名)
  - **Anthropic prompt caching 计账** (R15): cache_creation + cache_read 加到 prompt_tokens
  - **OpenAI reasoning tokens 语义** (R15): reasoning 是 completion 子字段, 不减
  - **Duck typing 原则** (R15): extractor 不 import SDK
  - **CLI 模块形状 (R14 确立)**: subcommand 实现模块暴露 `*_command(console, open_store_fn, ...)`
  - **OneAPI 配方 (R17/R18 确立)**: `model="Claude Opus 4.7"`, 不传 temperature, 响应恒包装饰性 error 字段忽略, UV_INDEX_URL=aliyun
  - **M milestone naming / multi-round bundle**: bug fix 不 bump M; release cut 单独一轮打包多个前轮
  - **Release pattern (R13/R16/R19 三次验证)**: bump version → pyproject → CLI 状态行 → CHANGELOG → 全绿 → commit → tag -a → push main+tag
  - **Dogfood script 陷阱 (R20 确立 / R21 修)**: `model_name` 在 `Node.model_name` 不是 `Node.usage.model_name`; **R21 起推荐 `n.model` 短形式**
  - **Em-dash (U+2014) / U+2212 minus 被 ruff RUF001 禁** (R21 又踩一次 — 肌肉记忆写进来)
  - **Pydantic v2 field-level docstring**: 字段注解行下方 `"""..."""` 即是该字段的 docstring (R21 实际用了, 确认 ruff/mypy 不反对)

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

**Round 22 候选 — R21 把 ADR-013 和 F2 都落了, R22 视野重新打开**

### R22 选项 (按优先级排序, 下一轮挑一个做)

**R22-A (最推荐)**: `chronos fork emit-python` — ADR-013 deferred alt C
- 背景: ADR-013 明确冻结 execute-fork, 但 deferred alt C 是个真正的中间路径: **Chronos 生成一段可粘贴的 Python 代码, 用户粘贴进自己的 graph 调用里就能完成 fork**. 不跨 execute-fork 边界, 但填了 "JSON-only 太裸" 的 DX gap
- 输入: 一个 `ForkPlan` 对象 (已有的 v0.1.1 契约)
- 输出: 一段 Python stdout (或文件), 含 `from chronos import ForkPlan; plan = ForkPlan(...)` + `# paste into your graph.invoke(...) call` 示范
- 新 CLI 动词: `chronos fork emit-python <fork_id>` (加在 fork 子命令下)
- 预期改动: ~50-80 LOC + 5-8 tests; 可选 bump v0.1.5 or 攒
- **用户价值可感知**: 第一个 "让 fork 真的能用起来而不用读文档" 的改进

**R22-B**: Phase 2 spike — AutoGen adapter 一轮试水
- ⚠️ R10 红线: Phase 2 之前不碰 AutoGen. R22 起 Phase 1 MVP 已稳定 + ADR-013 冻结 fork + dogfood 三轮完成, 可以动了
- 目标: 不是完整 AutoGen adapter, 是写 `src/chronos/adapters/autogen.py` 最小 `AutoGenRecorder.record()` context manager + 1 个 minimal example
- 验证 `Recorder` 协议是否真的 framework-agnostic, 暴露哪些 protocol 漏洞
- 时间盒子: 1 轮; 不成就写 lessons, 不硬推
- 成功条件: 能在 AutoGen 2-agent 对话上抓出至少 2 个 node, token count 合理

**R22-C (选做, 低优先)**: R21-C leftover — R17/R18 老 dogfood 脚本用 `n.model` 替换 `u.model_name`
- 改 2 个历史脚本, 演示新 API, ~5 min
- 如果做 R22-A 或 R22-B 时 "顺手" 做了更好; 独立做一轮不划算

### R22 非目标
- ❌ execute-fork 实现 (ADR-013 冻结)
- ❌ 第四轮 dogfood (三轮已够, 除非外部用户要求)
- ❌ v0.1.5 cut 除非 R22-A 或 R22-B 产出够大

### Release strategy for R22+
- `[Unreleased]` 现在有 R21 的 `Node.model` + ADR-013 两段
- R22 如果做 R22-A 产出一个 CLI 动词, 值得 cut v0.1.5
- R22 如果做 R22-B (Phase 2 spike), 通常**不** cut, 留给 Phase 2 M2.1 里再打包
- 继续用 R13/R16/R19 肌肉记忆的 7 步 release pattern

---

### 旧 R21 计划 (已完成, 存档)

- ~~R21-A 写 ADR-013~~ ✅ done (Accepted)
- ~~R21-B 加 Node.model + docstring cross-ref~~ ✅ done (+~30 LOC, 3 tests)
- ~~R21-C 修老脚本~~ → 推到 R22 (可选)

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
