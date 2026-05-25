# R120 验收清单 (User-Mandated Hard Deadline)

> **用户授权**: 在 R120 (距 R106 还有 14 轮 ≈ 3.5 天) 项目必须达到"完全可用"。R120 通过验收后, 用户取消 cron。
> **路线选择**: B 路线 (激进 v1.0 候选) — 不仅 bug-clean, 还要对外可发布。
> **写入时间**: 2026-05-25 (R106 close-out 后, R107 启动前)
> **当前状态**: Phase 5 Arc D slice 4 已完成 (R106), Phase 5 收口 + Phase 6 polish 阶段。

---

## 阶段化路线 R107 → R120 (14 轮预算)

### Phase 5 收口 (R107) — 1 轮

- **R107**: v0.9.0 GA cut (release engineering, 用 `chronos-release-pattern` skill)
  - CHANGELOG roll [Unreleased] → [0.9.0]
  - version bump 0.8.0 → 0.9.0 (pyproject.toml)
  - tag v0.9.0 + GitHub Release object
  - 不引入新功能, 纯发版

### Phase 6 启动 — Polish & Ship (R108-R120) — 13 轮

**新 Phase 6 charter**: "v1.0 Release Candidate — 完全可用的 time-travel debugger"
**核心目标**: 让一个新用户在 5 分钟内能完成 record→replay→fork 全流程, 且每一步有清晰指引。

#### Track 1: CLI 体验 polish (R108-R110, 3 轮)

- **R108 — CLI help/error 文案重写**
  - 每个 verb 的 `--help` 都要有 example 段 (如 `chronos replay --help` 给出真实命令)
  - error message 改成 actionable (`Run not found: 'abc'. Hint: list runs with 'chronos runs list'`)
  - 退出码契约文档化到 `docs/cli-reference.md`
  - 验收: `chronos --help` 看起来不是开发者写给开发者的, 而是给新用户

- **R109 — `chronos quickstart` 新 verb**
  - `chronos quickstart` 一键: 创建 demo SQLite + 录入 3 条 mock run + 打开 web UI 在 replay 页 + 终端打印"Now try: `chronos runs list`"
  - 5 分钟 onboarding 的 CLI 入口
  - 必须真能跑通 (用 mock adapter, 不依赖外部 API key)

- **R110 — `chronos doctor` 诊断**
  - 检查环境: Python 版本/依赖装好/SQLite 可读/前端 bundle 存在
  - 用户卡住时第一反应运行的命令
  - 输出 actionable 修复建议

#### Track 2: 前端 P0 问题清扫 (R111-R114, 4 轮)

- **R111 — UX dogfood 全站走查**
  - 用 `dogfood` skill 跑一遍 Landing → RunList → Replay → ForkTree → Diff
  - 列出所有"不顺畅"的点 (loading 缺失/error 没处理/空状态丑/键盘快捷键冲突)
  - 排出 P0/P1/P2

- **R112-R113 — 修 P0**
  - 前端任何"点了没反应"/"loading 转圈不出来"/"error 显示原始 stack" 都是 P0
  - 必须保证: 任何用户操作都有视觉反馈 (loading/success/error)
  - 空状态都有 "no runs yet, try chronos quickstart" 这种引导

- **R114 — 首屏 Onboarding Tour**
  - 第一次访问 Landing 页弹出 tour (用 react-joyride 或类似)
  - 4-5 步教学: "这是 Run/Node/Fork/Replay/Diff", 每步指向一个真实元素
  - 跳过按钮 + LocalStorage 记忆 "已看过"

#### Track 3: 文档与 demo (R115-R117, 3 轮)

- **R115 — README 重写**
  - 当前 README 是开发者视角, 改成用户视角
  - 顶部 30 秒 demo GIF (用 vhs 录, 见 `media/` skill 思路)
  - 5 分钟 quickstart 段落 (对接 R109 的 `chronos quickstart`)
  - 中英双语 (用户在 invariantsmith 项目就要求过这个)

- **R116 — 文档站搭建**
  - 用 mkdocs-material 或 vitepress 把 `docs/` 渲染成站点
  - GitHub Pages 部署
  - 至少包含: getting-started / cli-reference / concepts (Run/Node/Fork/Replay) / FAQ

- **R117 — Demo run 集合**
  - `examples/` 目录: 3-5 个真实 run 的 SQLite 文件 (langgraph 一个/anthropic_agents 一个/multi-fork 一个)
  - 配 README 说每个 demo 演示什么场景
  - `chronos quickstart --demo <name>` 可以一键加载

#### Track 4: v1.0-rc 发布 (R118-R120, 3 轮)

- **R118 — End-to-end 验收 dogfood**
  - 全流程跑一遍 (新 venv 装 → quickstart → 用 web UI 完整体验 → 阅读文档站)
  - 列出所有遗留问题, 当轮内能修就修
  - 不能修的列入 "post-1.0" backlog

- **R119 — 公开仓库 + v1.0.0-rc1 发版**
  - **⚠️ 公开前必须先用户确认** (硬约束: 公开仓库需用户点头)
  - GitHub 仓库 visibility: private → public (经用户授权后)
  - 发 v1.0.0-rc1 tag + Release Notes
  - 准备 Show HN / Reddit r/MachineLearning 文案 (但不发, 等用户决定)

- **R120 — 最终验收 + 战报**
  - 自检 R120 验收清单 (见下文)
  - 写一份 `progress/2026-XX-XX-round-120-FINAL.md` 完整汇报
  - 给用户发"R120 验收候选"战报, 等用户最终拍板

---

## R120 硬验收清单 (Agent 自检表)

### 必过项 (任一不过 = 验收失败, 继续干)

- [ ] **CLI 完整性**: `chronos quickstart` / `chronos doctor` 已实装并能跑通
- [ ] **CLI 友好度**: 9 个原 verb + 2 个新 verb 全部 `--help` 含 example, error 含 hint
- [ ] **前端流畅度**: P0 issue 全清, 5 个核心页面 (Landing/RunList/Replay/ForkTree/Diff) 任一操作有视觉反馈
- [ ] **新用户路径**: 新 venv 装包 → `chronos quickstart` → web UI 完成 record/replay/fork 一遍, 全程不需读源码
- [ ] **首屏 Tour**: Landing 页有 onboarding tour, 跳过/重看都行
- [ ] **README**: 中英双语, 顶部有 demo GIF, 5 分钟 quickstart 段落
- [ ] **文档站**: GitHub Pages 上线, getting-started + cli-reference + concepts + FAQ 四章俱全
- [ ] **Demo 集合**: `examples/` 下至少 3 个真实 demo run, `--demo <name>` 能加载
- [ ] **测试**: 全套测试绿 (≥664 现有 + Phase 6 新增), spike 系列绿
- [ ] **Adapter 零回归**: 流再延伸至 R52→R120 = 68 轮 (不破坏现有 langgraph/anthropic_agents adapter)
- [ ] **Git 状态**: 所有 R107-R120 改动已 push 到 origin/main, CHANGELOG 完整

### 加分项 (有更好, 没有不算失败)

- [ ] v1.0.0-rc1 tag 已打 (R119 完成)
- [ ] 公开仓库已切换 (需用户确认)
- [ ] Show HN 文案已起草 (放 `docs/launch/` 等用户拍板)
- [ ] AGPL/MIT license 已选定并加文件

### Agent 自检流程 (R120 当轮必做)

```bash
# 自检脚本 (写入 scripts/r120_acceptance_check.sh)
1. uv run pytest --no-cov -q  # 全套绿
2. uv run python tests/spikes/spike19_golden_trace_invariants.py  # spike 绿
3. ls examples/*.db | wc -l  # ≥3
4. test -f frontend/dist/index.html  # 前端构好
5. curl -s http://localhost:8000/api/runs  # 后端跑得起来 (chronos web 启动后)
6. 浏览器跑 dogfood 全站 (用 browser_navigate + browser_vision)
7. 检查 README.md 有 ## 中文 段落
8. 检查 docs/site/ 或 GH Pages URL 可访问
```

---

## Cron Agent 行为约束 (R107-R120 期间)

### 优先级倒序 (强约束)

1. **不能跳过本验收线** — 即使做的兴起, R120 也必须停下做自检
2. **不能加新 Phase 6 之外的方向** (如新 adapter/SaaS/cloud) — 这些是 post-1.0 backlog
3. **每轮必读 `docs/CONTEXT.md` §5 R120 验收线** — 确认还在 Phase 6 polish 轨道上
4. **R120 自检后**:
   - 全过 → 给用户发战报 "✅ R120 验收候选, 请拍板", 等用户回复
   - 有未过项 → 列出未过项, 申请 "R121-R125 buffer 5 轮", 继续干
   - 硬卡点 (如公开仓库需用户点头) → 列出阻塞, 但其余先做

### 仍然生效的老约束

- ❌ 不部署主网/不花真钱/不 commit .env/不公开仓库 (除非用户点头)
- ❌ 换技术栈先写 ADR
- ✅ spike/代码必须带测试
- ✅ 方向漂移要在 progress doc 里论证
- ✅ 每轮必 push 到 GitHub
- ✅ 每轮发战报 (即便 QQ 401, output 文件夹也会留底)
