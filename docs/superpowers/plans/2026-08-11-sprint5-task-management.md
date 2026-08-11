# Sprint 5：任务管理 API 与最小操作界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将受控探索包装为本地可创建、可观察、可取消、可人工确认登录的内存任务 API 与最小 Vue 界面。

**Architecture:** 后端以加锁的进程内任务注册表保存私有运行时句柄和脱敏公共视图。服务在后台线程编排既有 NavigationPolicy、HumanLoginSession 和 ExplorationRunner；路由只映射经过白名单的请求/响应模型。前端轮询任务详情并只显示状态、审计与摘要，不处理登录凭据。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、Playwright sync API、pytest、Vue 3、TypeScript、Element Plus、Vitest。

## Global Constraints

- 仅单进程内存任务；服务重启后不恢复任务、结果或登录态。
- 禁止持久化或响应 Cookie、Token、密码、验证码、`storage_state`、截图、网络正文或浏览器对象。
- 仅本地 HTTP fixture 验收；不得访问外站、绕过访问控制或自动填写登录表单。
- 所有探索继续受现有 URL/Origin、动作门禁、预算、同任务绑定和终态清理控制。
- API 错误仅返回固定安全码/消息；不得回显 URL 查询参数、选择器或浏览器异常文本。
- 每项先写失败测试、确认 RED，再最小实现、验证并独立提交。

---

### Task 1：任务公共模型与内存注册表

**Files:**
- Create: `backend/src/ai_ui_explorer/task_management/models.py`
- Create: `backend/src/ai_ui_explorer/task_management/registry.py`
- Create: `backend/src/ai_ui_explorer/task_management/__init__.py`
- Create: `backend/tests/task_management/test_registry.py`

**Interfaces:**
- Produces `TaskSummary`, `TaskEventView`, `TaskResultSummary`, `ManagedTask`, `ExplorationTaskRegistry`。
- `ExplorationTaskRegistry.create(entry) -> ManagedTask`、`get(task_id) -> ManagedTask | None`、`remove_runtime(task_id) -> None`。

- [x] **Step 1: 写失败测试**

```python
def test_registry_exposes_only_safe_task_view() -> None:
    registry = ExplorationTaskRegistry()
    task = registry.create(make_managed_task())
    view = registry.get(task.task_id).summary()
    assert view.task_id == task.task_id
    assert "cookie" not in view.model_dump_json().lower()

def test_registry_returns_none_for_unknown_task() -> None:
    assert ExplorationTaskRegistry().get("missing") is None
```

- [x] **Step 2: 运行 RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\task_management\test_registry.py`

Expected: 因模块缺失而失败。

- [x] **Step 3: 最小实现**

实现冻结的公共视图，只含 task id、状态、阶段、时间、审计白名单和页面/元素/链接计数。`ManagedTask` 用锁保护私有运行时字段；`summary()` 永不序列化 runtime、thread、browser 或 collector。

- [x] **Step 4: 验证**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\task_management\test_registry.py`

Expected: PASS。

- [x] **Step 5: 提交**

```powershell
git add backend/src/ai_ui_explorer/task_management backend/tests/task_management/test_registry.py
git commit -m "feat: add in-memory exploration task registry"
```

### Task 2：后台任务服务与受控运行时编排

**Files:**
- Create: `backend/src/ai_ui_explorer/task_management/service.py`
- Create: `backend/tests/task_management/test_service.py`
- Modify: `backend/src/ai_ui_explorer/task_management/models.py`

**Interfaces:**
- Produces `CreateExplorationTaskCommand`、`ExplorationTaskService.create()`、`confirm_login()`、`cancel()`、`result()`。
- Consumes Task 1 registry、`ExplorationRunner`、`HumanLoginSession`。

- [x] **Step 1: 写失败测试**

```python
def test_login_task_pauses_until_explicit_confirmation() -> None:
    service = make_service_with_local_runtime()
    task = service.create(make_login_command())
    assert service.get(task.task_id).state == "paused_for_human"
    assert service.confirm_login(task.task_id).state in {"paused_for_human", "collecting"}

def test_cancel_closes_runtime_and_returns_cancelled() -> None:
    service = make_service_with_local_runtime()
    task = service.create(make_command())
    assert service.cancel(task.task_id).state == "cancelled"
```

- [x] **Step 2: 运行 RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\task_management\test_service.py`

Expected: 因 service 缺失而失败。

- [x] **Step 3: 最小实现**

服务只接受显式 Origin、模块入口、预算和可选认证计划。在线程中运行 Runner；登录任务只在确认接口通过既有检查点验证后继续。所有异常进入固定失败状态，终态删除私有运行时引用；不写文件或数据库。

- [x] **Step 4: 验证**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\task_management\test_service.py tests\exploration\test_login_runtime.py`

Expected: PASS。

- [x] **Step 5: 提交**

```powershell
git add backend/src/ai_ui_explorer/task_management backend/tests/task_management/test_service.py
git commit -m "feat: orchestrate managed exploration tasks"
```

### Task 3：FastAPI 任务路由与安全错误面

**Files:**
- Create: `backend/src/ai_ui_explorer/api/routes/exploration_tasks.py`
- Modify: `backend/src/ai_ui_explorer/api/router.py`
- Modify: `backend/src/ai_ui_explorer/main.py`
- Create: `backend/tests/api/test_exploration_tasks.py`

**Interfaces:**
- Implements `POST/GET /api/v1/exploration-tasks`、`GET events/result`、`POST confirm-login/cancel`。

- [x] **Step 1: 写失败测试**

```python
def test_create_and_read_task_returns_safe_schema(client: TestClient) -> None:
    created = client.post("/api/v1/exploration-tasks", json=valid_payload())
    assert created.status_code == 202
    assert "cookie" not in created.text.lower()
    assert client.get(f"/api/v1/exploration-tasks/{created.json()['task_id']}").status_code == 200

def test_unknown_task_uses_fixed_error(client: TestClient) -> None:
    response = client.get("/api/v1/exploration-tasks/missing")
    assert response.json()["error"]["code"] == "task_not_found"
```

- [x] **Step 2: 运行 RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\api\test_exploration_tasks.py`

Expected: 404 或路由缺失。

- [x] **Step 3: 最小实现**

使用 Pydantic 请求/响应模型，应用生命周期创建单一 service。所有写接口只接受 POST，扩展 CORS 方法白名单为实际所需的 GET/POST。未知任务、非法状态和验证失败映射固定安全响应。

- [x] **Step 4: 验证**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\api\test_exploration_tasks.py tests\test_health.py`

Expected: PASS。

- [x] **Step 5: 提交**

```powershell
git add backend/src/ai_ui_explorer/api backend/src/ai_ui_explorer/main.py backend/tests/api/test_exploration_tasks.py
git commit -m "feat: expose exploration task api"
```

### Task 4：Vue 任务页与 API 客户端

**Files:**
- Create: `frontend/src/api/explorationTasks.ts`
- Create: `frontend/src/components/ExplorationTaskForm.vue`
- Create: `frontend/src/components/ExplorationTaskDetail.vue`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/ExplorationTaskForm.spec.ts`
- Create: `frontend/tests/ExplorationTaskDetail.spec.ts`

**Interfaces:**
- Produces任务创建表单、状态详情、确认/取消操作和 2 秒轮询；只消费 Task 3 的安全 API schema。

- [x] **Step 1: 写失败组件测试**

```ts
it('only reveals login fields when manual login is selected', async () => {
  const wrapper = mount(ExplorationTaskForm)
  expect(wrapper.text()).not.toContain('认证检查点')
  await wrapper.get('[data-test="manual-login"]').setValue(true)
  expect(wrapper.text()).toContain('认证检查点')
})

it('shows confirm only while paused for human', () => {
  const wrapper = mount(ExplorationTaskDetail, { props: { task: pausedTask } })
  expect(wrapper.get('[data-test="confirm-login"]').exists()).toBe(true)
})
```

- [x] **Step 2: 运行 RED**

Run: `pnpm test -- ExplorationTaskForm ExplorationTaskDetail`

Expected: 测试文件或组件缺失。

- [x] **Step 3: 最小实现**

表单仅允许显式 Origin/预算/可选认证配置；详情只显示状态、审计、摘要、确认和取消。API 客户端不发送或缓存凭据，轮询在组件卸载或终态停止。

- [x] **Step 4: 验证**

Run: `pnpm test -- ExplorationTaskForm ExplorationTaskDetail`

Run: `pnpm lint`

Run: `pnpm typecheck`

Expected: PASS。

- [x] **Step 5: 提交**

```powershell
git add frontend/src frontend/tests
git commit -m "feat: add exploration task management ui"
```

### Task 5：本地端到端验收、文档与质量门

**Files:**
- Modify: `backend/tests/api/test_exploration_tasks.py`
- Modify: `docs/00-project-context.md`
- Modify: `docs/02-architecture.md`
- Modify: `docs/07-roadmap.md`
- Modify: `docs/superpowers/plans/2026-08-11-sprint5-task-management.md`

- [x] **Step 1: 写本地 API 到浏览器探索 E2E 失败测试**

测试使用 `login_site` fixture：创建登录任务、等待暂停、仅由测试私有辅助模拟人工点击、调用 confirm API、轮询终态、断言结果摘要和 Browser Context 已关闭。

- [x] **Step 2: 运行 RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\api\test_exploration_tasks.py::test_local_login_task_completes_after_confirmation`

Expected: Task 3 API 未完成前失败。

- [x] **Step 3: 完成最小验收与文档状态更新**

文档只声明本地、内存、进程内、无凭据持久化的任务管理已实现；明确数据库、恢复、Worker、外站与自动登录仍未实现。

- [x] **Step 4: 运行质量门**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\task_management tests\api tests\exploration tests\snapshot\test_browser.py`

Run: `..\.venv\Scripts\python.exe -m ruff check --no-cache .`

Run: `..\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml --cache-dir ..\.mypy_cache_sprint5 src\ai_ui_explorer`

Run: `git diff --check`

Run: `pnpm test && pnpm lint && pnpm typecheck && pnpm build`

Expected: 每项退出码 0；确认 pytest Python 子进程真实退出。

- [ ] **Step 5: 提交**

```powershell
git add backend/tests docs
git commit -m "test: verify managed exploration tasks"
```

## 自检

- 设计中的 API、内存边界、人工确认、错误面与前端范围均由 Task 1–5 覆盖。
- 没有数据库、Worker、真实外站、凭据存储或截图/网络正文任务。
- 后续任务引用的服务、模型和路由都由前序任务定义。
