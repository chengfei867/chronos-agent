# Forking safely: three patterns for side-effecting tools

**Audience:** you have a LangGraph (or other framework) agent whose tools
call real APIs, write to real databases, or otherwise talk to the
outside world. You want to use Chronos to fork and replay runs without
sending duplicate emails, re-charging the same credit card, or posting
the same tweet five times.

**TL;DR:**

| Where is the side effect, relative to the fork point? | Do you need to do anything? |
|--------------------------------------------------------|------------------------------|
| **Before** the fork point (upstream) | Nothing — the checkpointer skips upstream replay. See [§Background](#background). |
| **At or after** the fork point (downstream) | Yes — pick one of the [three patterns](#three-patterns) below. |

Chronos itself does **not** sandbox fork execution (see
[ADR-019](../decisions/ADR-019-chronos-does-not-sandbox.md)). Your agent
code owns the runtime; these patterns let you keep that ownership cheap.

---

## Background

When you call `recorder.fork(graph, parent_run_id=..., at_node_id=N,
overrides=...)`, LangGraph resumes from the checkpoint at node `N`. The
checkpointer guarantees that nodes *before* `N` are **not** re-executed
— we verified this empirically in `tests/spikes/spike8_fork_sideeffect.py`:

- Fork **after** a side-effecting node → 0 replay calls. The side effect
  stays in the past.
- Fork **before** a side-effecting node → 1 fresh call. The new branch
  executes it with your overrides.

The second case is where you sometimes want isolation. The patterns
below are three idiomatic ways to get it, ordered from cheapest to
most-structural.

---

## Three patterns

### Pattern 1 — Mock the transport (5-line fixture)

**Use when:** you want to fork an LLM-heavy plan or an HTTP-heavy tool
node, and you don't care what the external API "actually" returns — you
just want the graph to finish deterministically.

```python
# test_fork_with_mock.py
import httpx, respx
from chronos.adapters.langgraph import LangGraphRecorder
from chronos.store.sqlite import SqliteStore

@respx.mock
def test_fork_with_mocked_tool():
    respx.post("https://api.example.com/").mock(
        return_value=httpx.Response(200, json={"status": "mocked"})
    )
    with SqliteStore.open("chronos.db") as store:
        rec = LangGraphRecorder(store=store)
        with rec.fork(
            compiled_graph,
            parent_run_id=parent_run_id,
            at_node_id=fork_node_id,
            overrides={"plan": "alternate strategy"},
            child_thread_id="child-1",
        ):
            compiled_graph.invoke(None, {"configurable": {"thread_id": "child-1"}})
```

Same shape for `openai-python`, `anthropic`, LangChain's `FakeListLLM`,
etc. Point your tool's HTTP client at a mock, fork, invoke, done.

**Cost:** 5 lines of fixture.
**Coverage:** everything that talks over HTTP. Fails open for tools that
write to local disk / DB / message queues — see Pattern 2.

### Pattern 2 — Envvar kill-switch

**Use when:** your tools span multiple transports (HTTP + DB + files),
or the tool itself has "don't actually send" semantics baked in.

```python
# your_tools.py
import os

def send_notification(user_id: str, body: str) -> dict:
    if os.environ.get("CHRONOS_DRY_RUN") == "1":
        return {"status": "dry-run", "user_id": user_id, "preview": body[:80]}
    return _real_send(user_id, body)
```

Then in your fork script:

```python
os.environ["CHRONOS_DRY_RUN"] = "1"
try:
    with rec.fork(...) as fork_ref:
        compiled_graph.invoke(None, cfg_child)
finally:
    os.environ.pop("CHRONOS_DRY_RUN", None)
```

**Cost:** one `if` per destructive tool + three lines per fork
invocation.
**Coverage:** any side effect whose code you control.
**Bonus:** works in production too — set `CHRONOS_DRY_RUN=1` in CI to
get a smoke run with full traceability but no real destructive calls.

### Pattern 3 — Pure / effectful tool split

**Use when:** you're designing new tools and want side-effect-safety to
be *structural*, not *configurational*.

Split each tool into `(planner, actuator)`:

```python
# Instead of one tool:
def send_email(recipient: str, subject: str, body: str) -> dict: ...

# Ship two:
def plan_email(recipient: str, subject: str, body: str) -> dict:
    """Return what *would* be sent. Pure — no side effect."""
    return {"recipient": recipient, "subject": subject, "body": body,
            "estimated_chars": len(body)}

def send_email(plan: dict) -> dict:
    """Actually send. Only called after human/graph approval."""
    return _smtp.send(**plan)
```

LangGraph node that currently calls `send_email(...)` now calls
`plan_email(...)`, writes the plan into state, and only advances to a
`send` node on an explicit approval edge. Fork before `send` → replays
`plan_email` cheap; fork after `send` → doesn't replay it at all.

**Cost:** architectural. ~2× the node count for tools that need this
split; zero runtime overhead.
**Coverage:** complete. This is the pattern that makes time-travel
debugging *pleasant* rather than *cautious*.

---

## Picking between them

| You have … | Use … |
|-------------|-------|
| An existing agent, want to fork-debug tomorrow | Pattern 1 (mock transport) |
| Multiple tool transports + production parity concern | Pattern 2 (envvar) |
| Greenfield tool design + time-travel is a product feature | Pattern 3 (split) |

You can mix them: Pattern 3 in new code, Pattern 2 for the messy
legacy, Pattern 1 in your test fixtures.

---

## What Chronos will do for you (Phase 3)

Chronos itself stays out of your runtime ([ADR-019][adr19]). Phase 3
will ship:

- **`nodes.effects` metadata** — the adapter tags each node with the
  side-effect classes it touches (`network`, `fs`, `db`, `llm`). (PH3-02)
- **ForkPlan warning badge** — the Web UI renders a message like
  *"forking here will re-execute 2 network-effectful nodes"* before
  you hit Run. (PH3-02)

Until those ship, this guide is the contract. The patterns work today
against v0.2.1.

[adr19]: ../decisions/ADR-019-chronos-does-not-sandbox.md

---

# 中文版 — 安全地 fork: 给带副作用的工具选个模式

**读者:** 你有个 LangGraph (或别的框架) agent, 工具会调真 API、写真数据
库、或者跟外界通信. 你想用 Chronos 做 fork / 时光倒流, 不想重复发邮件、
不想重复扣款、不想把同一条推文发五遍.

**一句话总结:**

| 副作用在 fork 点的哪一侧? | 你要不要做点啥? |
|---------------------------|------------------|
| **Fork 点之前** (上游) | 不用 — checkpointer 自己会跳过上游重放 |
| **Fork 点之后** (下游) | 要 — 在下面 [三种模式](#三种模式) 里挑一个 |

Chronos **不沙箱**你的 fork 执行 ([ADR-019]). Agent runtime 归你, 下面
这些模式让这份"所有权"保持便宜.

[ADR-019]: ../decisions/ADR-019-chronos-does-not-sandbox.md

## 为啥上游不用管

`recorder.fork(...)` 让 LangGraph 从 checkpoint 续跑. checkpointer 保
证 fork 点**之前**的节点 **不**重新执行 — `tests/spikes/spike8_fork_sideeffect.py`
实测:

- Fork **之后** 的 side-effect 节点 → 0 次重放. 副作用留在过去.
- Fork **之前** 的 side-effect 节点 → 1 次 fresh 跑. 新分支用你的
  overrides 执行它.

下面的模式专治第二种情况.

## 三种模式

### 模式 1 — Mock 掉底层 transport (5 行 fixture)

**适用:** 你想 fork 一个 LLM-heavy 的 plan 或 HTTP-heavy 的工具节点,
不关心外部 API 真正返回啥 — 只想让 graph 跑完而且可复现.

代码见上面 English 版的 Pattern 1 — `respx.mock` 拦截 `httpx`, 或者
`FakeListLLM` 替换掉真 LLM. 一个 fixture 跨多个 fork 复用.

**成本:** 5 行.
**覆盖:** 所有走 HTTP 的东西. 写本地磁盘 / 数据库 / 消息队列 的不 cover,
选模式 2.

### 模式 2 — 环境变量杀开关

**适用:** 工具跨多种 transport (HTTP + DB + 文件), 或者工具自身就有
"don't actually send" 语义.

给每个破坏性工具加一段:

```python
if os.environ.get("CHRONOS_DRY_RUN") == "1":
    return {"status": "dry-run", ...}
```

Fork 脚本里 `os.environ["CHRONOS_DRY_RUN"] = "1"` 包起来即可.

**成本:** 每个破坏性工具 1 个 `if` + fork 调用前后 3 行 env 管理.
**覆盖:** 你能改代码的所有副作用.
**彩蛋:** 生产环境也能用 — 在 CI 里打开这个 envvar, 拿完整 Chronos 录制但
没真实破坏性副作用的冒烟测试.

### 模式 3 — 纯工具 / 有副作用工具拆分

**适用:** 你在设计新工具, 希望 side-effect-safety 是**结构性的**而不
是**配置性的**.

把每个工具拆成 `(planner, actuator)` 两半:

- `plan_X(...)` — 纯函数, 返回"本来会发生啥". 无副作用.
- `do_X(plan)` — 接一个 plan dict, 真正触发副作用.

LangGraph 里原来调 `send_email` 的节点现在调 `plan_email`, plan 写进
state, 只有在显式 approve edge 上才走到 `send` 节点. Fork 在 `send`
之前 → 重放 `plan_email` 便宜; fork 在 `send` 之后 → 完全不重放.

**成本:** 架构性. 需要做 side-effect split 的工具节点数 ×2; 零运行时
开销.
**覆盖:** 完整. 这是让时光倒流调试变成**愉快**而不是**小心翼翼**的模式.

## 怎么选

| 你有的 … | 用 … |
|----------|------|
| 已有 agent, 明天就要 fork 调试 | 模式 1 (mock transport) |
| 多种 transport + 关心生产一致性 | 模式 2 (envvar) |
| 新做工具 + 时光倒流是产品卖点 | 模式 3 (split) |

可以混用: 新代码用模式 3, 遗留代码用模式 2, 测试 fixture 用模式 1.

## Phase 3 Chronos 会给你加的

Chronos 自身不进你 runtime ([ADR-019]). Phase 3 会加:

- **`nodes.effects` 元数据** — adapter 给每个节点打上副作用标签
  (`network` / `fs` / `db` / `llm`). (PH3-02)
- **ForkPlan 警告角标** — Web UI 在你按 Run 之前显示
  *"此 fork 将重新执行 2 个涉及网络的节点"*. (PH3-02)

在那之前, 这份 guide 就是契约. v0.2.1 就能用.
