# Sprint 4 交接记录

日期：2026-07-31

## 🎯 恢复任务时先看这里

几天后继续任务时，建议先阅读：

1. `AGENTS.md`
2. `docs/00-project-context.md`
3. `docs/superpowers/plans/2026-07-31-controlled-exploration.md`
4. 本文档

当前最后一个已保存提交：

```text
8dfd8c5 feat: wire snapshot href navigation candidates
```

## ✅ 当前已实现到哪里

Sprint 4 已完成受控探索的模型与编排基础：

- URL/Origin 风险门禁。
- 只读动作门禁。
- 任务状态机。
- 最小审计事件。
- 页面状态指纹与状态去重。
- 指定模块入口配置。
- 有界探索队列。
- 可注入 `SnapshotCollectorPort` 的有界 `ExplorationRunner`。
- 复用 Sprint 1 `SnapshotCollector` 的 `SnapshotCollectorAdapter`。
- Snapshot 1.1 保存经过 URL 脱敏的 anchor `href` 导航元数据。
- 从 Snapshot 确定性提取去重后的只读链接导航候选。
- Runner 默认接入 Snapshot href 候选提取器。
- Runner 遇到重复页面状态时停止继续展开候选。

这些能力已提交到本地 Git。

## ⚠️ 明确仍未实现

不要把下面内容描述成已完成：

- 真实浏览器多页面端到端验收。
- 人机协同登录运行时。
- 认证 URL / 选择器验证器。
- 登录后安全检查点。
- 本地登录集成测试站点。
- 真实外部网站探索。
- 业务动作点击、提交、删除、审批、支付、发布。
- 多身份权限探索。
- LLM 推断生成与 Agent。
- 数据库、Redis、Worker、Docker Compose。
- 截图和网络正文采集。
- 测试案例生成和 Playwright 自动化代码生成。
- 周期巡检与增量 Diff。

## 🔐 安全边界

- 当前阶段只允许受控、只读、预算内探索。
- 不访问外部网站作为自动化验收对象。
- 不提交账号、Cookie、Token、验证码、截图、抓包、探索输出或业务数据。
- `href` 必须作为 URL 元数据脱敏保存，不应塞进普通 `attributes`。
- 如果未来加入人工登录，登录态默认不进版本控制。

## 🧪 已通过的关键验证

最近一轮通过的验证包括：

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests\exploration
.\.venv\Scripts\python.exe -m pytest -q backend\tests\snapshot\test_models.py backend\tests\snapshot\test_collector.py backend\tests\snapshot\test_browser.py::test_browser_collects_same_frame_anchor_href_as_navigation_metadata backend\tests\snapshot\test_browser.py::test_browser_collects_anchor_href_as_navigation_metadata
cd backend
..\.venv\Scripts\python.exe -m ruff check --no-cache .
..\.venv\Scripts\python.exe -m mypy --cache-dir ..\.mypy_cache_codex src\ai_ui_explorer
git diff --check
```

## 🔜 下一步建议

下一步应完成 Sprint 4 第三阶段最后一块：

> 使用本地 fixture 做真实浏览器多页面端到端验收。

建议目标：

- 构造一个本地多页面 fixture。
- 从模块入口 URL 开始运行 `ExplorationRunner`。
- 通过 `SnapshotCollectorAdapter` 调用真实 `SnapshotCollector`。
- 从入口页 Snapshot 自动提取 `href` 候选。
- 经 `NavigationPolicy`、`ActionGate`、预算和状态去重控制后访问下一页。
- 验证不访问外部网站、不执行业务动作、不泄露敏感错误信息。

建议先写失败测试，再实现最小代码。

## 💡 恢复时的第一条操作建议

几天后恢复时，先执行：

```powershell
git status --short --untracked-files=all
git log --oneline -5
.\.venv\Scripts\python.exe -m pytest -q backend\tests\exploration
```

如果工作区干净且测试通过，就从“本地 fixture 真实浏览器多页面端到端验收”继续。
