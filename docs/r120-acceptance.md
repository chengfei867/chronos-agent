# R122 验收清单 (User-Mandated Hard Deadline)

> **历史**: 2026-05-25 R106 close-out 时立 R120 为终点 (B 路线 v1.0 RC); 2026-05-26 R109 close-out 时, 用户在 dogfood 评估后追加 ADR-029 Cost Visibility + ADR-030 Evaluation/Scoring 两轮, **终点延后 2 轮 → R122**。
> **用户授权**: 在 R122 项目必须达到"完全可用"且具备业界对标的核心能力 (Cost Tracking + Evaluation 都点亮)。R122 通过验收后, 用户取消 cron。
> **路线选择**: B 路线 + C 加餐 = 激进 v1.0 RC + 业界对标的两个差异化补刀。
> **写入时间**: 2026-05-25 初版 / 2026-05-26 R109 后修订
> **当前状态 (R109 末)**: Phase 6 RC kickoff 已发, CLI Polish slice 1+2 (R108/R109) 完成, quickstart + help 重写已落地。

---

## 阶段化路线 R107 → R122 (16 轮预算, R109 已完成)

### Phase 5 收口 (R107) — 1 轮 ✅ 已完成

- **R107**: v0.9.0 GA cut (release engineering, 用 `chronos-release-pattern` skill) ✅
  - CHANGELOG roll [Unreleased] → [0.9.0]
  - version bump 0.8.0 → 0.9.0 (pyproject.toml)
  - tag v0.9.0 + GitHub Release object
  - 不引入新功能, 纯发版

### Phase 6 启动 — Polish & Ship (R108-R122) — 15 轮

**新 Phase 6 charter**: "v1.0 Release Candidate — 完全可用的 time-travel debugger + 业界对标的 Cost & Evaluation 能力"
**核心目标**: 让一个新用户在 5 分钟内能完成 record→replay→fork 全流程, 看到 token/cost, 能对 fork 打分对比, 每一步有清晰指引。

#### Track 1: CLI 体验 polish (R108-R110, 3 轮)

- **R108 — CLI help/error 文案重写** ✅ 已完成
  - 每个 verb 的 `--help` 都要有 example 段
  - error message 改成 actionable
  - 退出码契约文档化到 `docs/cli-reference.md`

- **R109 — `chronos quickstart` 新 verb** ✅ 已完成
  - `chronos quickstart` 一键: 创建 demo SQLite + builtin-minimal demo + `--demo <name>` 加载
  - 5 分钟 onboarding 的 CLI 入口
  - E2E smoke test 通过

- **R110 — `chronos doctor` 诊断**
  - 检查环境: Python 版本/依赖装好/SQLite 可读/前端 bundle 存在
  - 用户卡住时第一反应运行的命令
  - 输出 actionable 修复建议

#### Track 1.5: Cost Visibility (R111, 1 轮) — ADR-029 新增

- **R111 — Cost & Token Tracking visibility uplift** (ADR-029)
  - `chronos runs list` 默认显示 tokens / cost ¢ 列 (当任一 run 有 usage 时), `--no-usage` opt-out
  - `builtin-minimal` quickstart demo 给 LLM 节点填合理的 usage 数据 (prompt=120, completion=80, cost=8 cents) + 一行 metadata.note 说明是 illustrative
  - 前端 `RunList` 页加 Tokens / Cost (USD) 两列 (空时隐藏)
  - 后端 runs-list endpoint 返回 `usage_summary` per run
  - README 加 "💰 Cost & Token Tracking" feature 行 + 截图
  - `docs/getting-started.md` 加 "what you'll see" 段提及 token 列
  - 测试: 2 unit + 1 spike (`spike20_quickstart_demo_has_usage.py`)

#### Track 2: 前端 P0 问题清扫 (R112-R114, 3 轮, 原 R111-R114 压缩 1 轮)

- **R112 — UX dogfood 全站走查**
  - 用 `dogfood` skill 跑一遍 Landing → RunList → Replay → ForkTree → Diff
  - 列出所有"不顺畅"的点 (loading 缺失/error 没处理/空状态丑/键盘快捷键冲突)
  - 排出 P0/P1/P2

- **R113 — 修 P0 (上半)**
  - 前端任何"点了没反应"/"loading 转圈不出来"/"error 显示原始 stack" 都是 P0
  - 必须保证: 任何用户操作都有视觉反馈 (loading/success/error)
  - 空状态都有 "no runs yet, try chronos quickstart" 这种引导

- **R114 — 修 P0 (下半) + 首屏 Onboarding Tour**
  - 剩余 P0 收尾
  - 第一次访问 Landing 页弹出 tour (用 react-joyride 或类似)
  - 4-5 步教学: "这是 Run/Node/Fork/Replay/Diff", 每步指向一个真实元素
  - 跳过按钮 + LocalStorage 记忆

#### Track 2.5: Evaluation & Scoring (R115, 1 轮) — ADR-030 新增

- **R115 — Evaluator hook + 存储 + CLI/前端 surfacing** (ADR-030)
  - 新表 `evaluations` (additive migration), 新 `Evaluation` Pydantic 类
  - 注册式 evaluator API: `chronos.eval.register("name", fn)`
  - 2 个 built-in evaluators: `output_length_chars` + `final_state_key_present` (LLM-judge 是 v1.1+)
  - 新 CLI: `chronos eval run <run_id> --evaluator <name>`, `chronos eval list <run_id>`
  - `chronos compare --eval <name>` 加分数列, 倒序排
  - 前端 `TreeView` 节点带 score badge, `RunList` 加 sortable Score 列
  - API: `GET/POST /runs/{id}/evaluations`
  - 测试: migration + 4 unit + spike21
  - 文档: README 加 "🎯 Evaluation" 行, docs/evaluators.md 新页

#### Track 3: 文档与 demo (R116-R118, 3 轮, 原 R115-R117)

- **R116 — README 重写**
  - 当前 README 是开发者视角, 改成用户视角
  - 顶部 30 秒 demo GIF (用 vhs 录, 见 `media/` skill 思路)
  - 5 分钟 quickstart 段落 (对接 R109 的 `chronos quickstart`)
  - 中英双语 (用户在 invariantsmith 项目就要求过这个)
  - 必须包含 Cost Tracking + Evaluation 两个新 feature 行 (R111/R115 产出)

- **R117 — 文档站搭建**
  - 用 mkdocs-material 或 vitepress 把 `docs/` 渲染成站点
  - GitHub Pages 部署
  - 至少包含: getting-started / cli-reference / concepts (Run/Node/Fork/Replay) / evaluators / cost-tracking / FAQ

- **R118 — Demo run 集合**
  - `examples/` 目录: 3-5 个真实 run 的 SQLite 文件 (langgraph 一个/anthropic_agents 一个/multi-fork 一个)
  - 配 README 说每个 demo 演示什么场景
  - `chronos quickstart --demo <name>` 可以一键加载所有
  - 每个 demo 至少跑过一次 evaluator (展示 R115 能力)

#### Track 4: v1.0-rc 发布 (R119-R122, 4 轮, 原 R118-R120 加 1 轮 buffer)

- **R119 — End-to-end 验收 dogfood**
  - 全流程跑一遍 (新 venv 装 → quickstart → 用 web UI 完整体验 → 阅读文档站 → 跑 evaluator → 看 cost)
  - 列出所有遗留问题, 当轮内能修就修
  - 不能修的列入 "post-1.0" backlog

- **R120 — 公开仓库 + v1.0.0-rc1 发版**
  - **⚠️ 公开前必须先用户确认** (硬约束: 公开仓库需用户点头)
  - GitHub 仓库 visibility: private → public (经用户授权后)
  - 发 v1.0.0-rc1 tag + Release Notes (突出 Cost Tracking + Evaluation 两个差异化卖点)
  - 准备 Show HN / Reddit r/MachineLearning 文案 (但不发, 等用户决定)

- **R121 — RC 修补轮 (buffer)**
  - 验收前最后 1 轮 buffer: 修任何 R119 dogfood 暴露但 R120 release 后才显眼的问题
  - 如果 R119/R120 都干净, R121 用作"加强 demo / 改 README 第一段 / 多录一段视频" 的提升轮
  - 不引入新方向

- **R122 — 最终验收 + 战报**
  - 自检 R122 验收清单 (见下文)
  - 写一份 `progress/2026-XX-XX-round-122-FINAL.md` 完整汇报
  - 给用户发"R122 验收候选"战报, 等用户最终拍板

---

## R122 硬验收清单 (Agent 自检表)

### 必过项 (任一不过 = 验收失败, 继续干)

- [ ] **CLI 完整性**: `chronos quickstart` / `chronos doctor` / `chronos eval` 全部实装并能跑通
- [ ] **CLI 友好度**: 所有 verb (原 9 个 + quickstart + doctor + eval) 全部 `--help` 含 example, error 含 hint
- [ ] **Cost 可见性 (ADR-029)**: `chronos runs list` 默认看到 token + cost 列, builtin-minimal demo 有 usage 数据, 前端 RunList 也显示
- [ ] **Evaluation (ADR-030)**: `chronos eval run --evaluator output_length_chars <run_id>` 能跑出分数, `chronos compare --eval` 能排序, 前端 RunList 有 Score 列
- [ ] **前端流畅度**: P0 issue 全清, 5 个核心页面 (Landing/RunList/Replay/ForkTree/Diff) 任一操作有视觉反馈
- [ ] **新用户路径**: 新 venv 装包 → `chronos quickstart` → web UI 完成 record/replay/fork → 看到 token/cost → 跑一次 evaluator, 全程不需读源码
- [ ] **首屏 Tour**: Landing 页有 onboarding tour, 跳过/重看都行
- [ ] **README**: 中英双语, 顶部有 demo GIF, 5 分钟 quickstart 段落, 含 Cost Tracking + Evaluation 两个 feature 行
- [ ] **文档站**: GitHub Pages 上线, getting-started + cli-reference + concepts + evaluators + cost-tracking + FAQ
- [ ] **Demo 集合**: `examples/` 下至少 3 个真实 demo run, `--demo <name>` 能加载, 每个有 evaluator 跑过
- [ ] **测试**: 全套测试绿 (≥684 现有 + R110-R122 新增, 估计 ≥710), spike 系列绿 (含 spike20/21)
- [ ] **Adapter 零回归**: 流再延伸至 R52→R122 = 70 轮 (不破坏现有 4 个 first-class adapter)
- [ ] **Git 状态**: 所有 R107-R122 改动已 push 到 origin/main, CHANGELOG 完整

### 加分项 (有更好, 没有不算失败)

- [ ] v1.0.0-rc1 tag 已打 (R120 完成)
- [ ] 公开仓库已切换 (需用户确认)
- [ ] Show HN 文案已起草 (放 `docs/launch/` 等用户拍板)
- [ ] AGPL/MIT license 已选定并加文件

### Agent 自检流程 (R122 当轮必做)

```bash
# 自检脚本 (写入 scripts/r122_acceptance_check.sh)
1. uv run pytest --no-cov -q  # 全套绿
2. uv run python tests/spikes/spike19_golden_trace_invariants.py  # spike 绿
3. uv run python tests/spikes/spike20_quickstart_demo_has_usage.py  # ADR-029 spike
4. uv run python tests/spikes/spike21_eval_compare_pipeline.py  # ADR-030 spike
5. ls examples/*.db | wc -l  # ≥3
6. test -f frontend/dist/index.html  # 前端构好
7. curl -s http://localhost:8000/api/runs  # 后端跑得起来
8. 浏览器跑 dogfood 全站 (用 browser_navigate + browser_vision)
9. chronos runs list  # 看到 token + cost 列默认显示
10. chronos eval run <demo_run_id> --evaluator output_length_chars  # eval 能跑
11. 检查 README.md 有 ## 中文 段落 + Cost + Evaluation feature 行
12. 检查 docs/site/ 或 GH Pages URL 可访问
```

---

## Cron Agent 行为约束 (R107-R122 期间)

### 优先级倒序 (强约束)

1. **不能跳过本验收线** — 即使做的兴起, R122 也必须停下做自检
2. **不能加 ADR-029/030 之外的新方向** (如新 adapter/SaaS/cloud) — 这些是 post-1.0 backlog
3. **每轮必读 `docs/CONTEXT.md` §5 R122 验收线** — 确认还在 Phase 6 polish + ADR-029/030 轨道上
4. **R122 自检后**:
   - 全过 → 给用户发战报 "✅ R122 验收候选, 请拍板", 等用户回复
   - 有未过项 → 列出未过项, 申请 "R123-R127 buffer 5 轮", 继续干
   - 硬卡点 (如公开仓库需用户点头) → 列出阻塞, 但其余先做

### 仍然生效的老约束

- ❌ 不部署主网/不花真钱/不 commit .env/不公开仓库 (除非用户点头)
- ❌ 换技术栈先写 ADR
- ✅ spike/代码必须带测试
- ✅ 方向漂移要在 progress doc 里论证
- ✅ 每轮必 push 到 GitHub
- ✅ 每轮发战报 (即便 QQ 401, output 文件夹也会留底)
