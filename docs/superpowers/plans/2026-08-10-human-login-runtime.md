# 人机协同登录运行时 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在只保存内存态的可见 Playwright 浏览器中支持人工登录，并在显式认证检查通过后恢复受控只读探索。

**Architecture:** 认证计划与验证结果独立于浏览器实现。任务级浏览器会话持有唯一 Browser Context；认证运行时只允许暂停、人工确认、验证、取得绑定 Context 的 Collector 和关闭。现有 `ExplorationTask` 提供状态机，现有 `NavigationPolicy` 决定认证与目标 Origin 的允许范围。

**Tech Stack:** Python 3.12、Pydantic、Playwright sync API、pytest、Ruff、mypy。

## Global Constraints

- 登录 Context、Cookie、Token、验证码和浏览器存储状态只存在于当前进程内存；禁止调用 `storage_state()`。
- 认证 URL、登录后 URL 前缀和 CSS 检查点必须由 `AuthenticationPlan` 显式提供，禁止页面推断。
- 只允许 `NavigationPolicy` 的认证 Origin 进入人工登录；认证完成后必须回到目标 Origin。
- 验证失败只能回到 `paused_for_human`，不得写入已认证状态或检查点。
- Collector 恢复后仍由既有 `NavigationPolicy`、`ActionGate`、预算和状态去重控制。
- 测试只能使用本地 HTTP fixture；不提交任何真实账号、Cookie、Token 或截图。

---

## 文件结构

- Create: `backend/src/ai_ui_explorer/exploration/authentication.py` — 认证计划、验证结果与安全错误模型。
- Create: `backend/src/ai_ui_explorer/exploration/login_runtime.py` — 人机协同运行时的状态编排和终态清理。
- Create: `backend/tests/exploration/test_authentication.py` — 认证计划的 Origin、URL 前缀、选择器配置测试。
- Create: `backend/tests/exploration/test_login_runtime.py` — 人工确认、认证失败、关闭等纯运行时测试。
- Modify: `backend/src/ai_ui_explorer/snapshot/browser.py` — 抽取可复用的 Context/Page 观察路径，并增加内存态会话采集接口。
- Modify: `backend/src/ai_ui_explorer/exploration/collector_adapter.py` — 增加绑定会话的 Collector Port。
- Modify: `backend/tests/snapshot/conftest.py` — 提供独立的本地登录 fixture URL。
- Create: `backend/tests/fixtures/login_site/login.html` — 本地模拟登录页。
- Create: `backend/tests/fixtures/login_site/dashboard.html` — 仅登录后可访问的本地页和检查点。
- Modify: `backend/src/ai_ui_explorer/exploration/__init__.py` — 仅导出公开认证与运行时类型。
- Create: `backend/tests/exploration/test_login_browser.py` — 真实 Chromium 的同 Context 登录后采集验收。
- Modify: `docs/00-project-context.md`、`docs/02-architecture.md`、`docs/07-roadmap.md`、`docs/superpowers/plans/2026-07-31-controlled-exploration.md` — 只在功能和验收实际完成后更新状态。

## Task 1: 认证计划与验证模型

**Files:**
- Create: `backend/src/ai_ui_explorer/exploration/authentication.py`
- Create: `backend/tests/exploration/test_authentication.py`
- Modify: `backend/src/ai_ui_explorer/exploration/__init__.py`

**Interfaces:**
- Consumes: `NavigationPolicy`, `DeepFrozenModel`。
- Produces: `AuthenticationPlan`, `AuthenticationVerification`, `AuthenticationError`。

- [ ] **Step 1: 写失败测试，覆盖认证入口和检查点边界。**

```python
def test_plan_rejects_authentication_url_outside_authentication_origins() -> None:
    plan = AuthenticationPlan(
        authentication_url="https://outside.example.test/login",
        post_login_url_prefix="https://app.example.test/dashboard",
        checkpoint_css_selector="#signed-in-marker",
    )
    policy = NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    with pytest.raises(AuthenticationError, match="Authentication plan denied"):
        plan.validate(policy)


def test_plan_rejects_post_login_prefix_outside_target_origin() -> None:
    plan = AuthenticationPlan(
        authentication_url="https://sso.example.test/login",
        post_login_url_prefix="https://sso.example.test/complete",
        checkpoint_css_selector="#signed-in-marker",
    )
    policy = NavigationPolicy(
        allowed_origins=["https://app.example.test"],
        authentication_origins=["https://sso.example.test"],
    )

    with pytest.raises(AuthenticationError, match="Authentication plan denied"):
        plan.validate(policy)
```

- [ ] **Step 2: 运行测试，确认因模型缺失失败。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration\test_authentication.py`

Expected: import error for `AuthenticationPlan`。

- [ ] **Step 3: 实现最小模型与验证。**

```python
class AuthenticationPlan(DeepFrozenModel):
    authentication_url: str = Field(min_length=1, max_length=2_048)
    post_login_url_prefix: str = Field(min_length=1, max_length=2_048)
    checkpoint_css_selector: str = Field(min_length=1, max_length=512)

    def validate(self, policy: NavigationPolicy) -> None:
        if not policy.evaluate(self.authentication_url, authentication_handoff=True).allowed:
            raise AuthenticationError("Authentication plan denied.")
        if not policy.evaluate(self.post_login_url_prefix).allowed:
            raise AuthenticationError("Authentication plan denied.")
```

`AuthenticationVerification` 只含 `authenticated: bool`、`reason_code: str`、`checkpoint_id: str | None`；错误信息固定且不得回显 URL 或选择器。

- [ ] **Step 4: 运行认证模型测试与静态检查。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration\test_authentication.py`

Run: `..\.venv\Scripts\python.exe -m ruff check --no-cache src\ai_ui_explorer\exploration tests\exploration\test_authentication.py`

Expected: 全部通过。

- [ ] **Step 5: 提交认证模型。**

```powershell
git add backend/src/ai_ui_explorer/exploration/authentication.py backend/src/ai_ui_explorer/exploration/__init__.py backend/tests/exploration/test_authentication.py
git commit -m "feat: add authentication plan validation"
```

## Task 2: 任务级内存浏览器会话与绑定采集

**Files:**
- Modify: `backend/src/ai_ui_explorer/snapshot/browser.py`
- Modify: `backend/src/ai_ui_explorer/exploration/collector_adapter.py`
- Modify: `backend/tests/snapshot/conftest.py`
- Create: `backend/tests/fixtures/login_site/login.html`
- Create: `backend/tests/fixtures/login_site/dashboard.html`
- Create: `backend/tests/exploration/test_login_browser.py`

**Interfaces:**
- Consumes: `SnapshotLimits`、`RawPageObservation`、`SnapshotCollector`。
- Produces: `PlaywrightBrowserSession.open(headless: bool)`, `goto(url: str)`, `current_url`, `has_css(selector: str)`, `collect(url: str, limits: SnapshotLimits)`, `close()`；以及 `SessionSnapshotCollectorAdapter.collect(url: str)`。

- [ ] **Step 1: 写失败测试，要求同一 Context 保留登录 Cookie。**

```python
def test_session_collector_observes_login_only_dashboard(login_site: LoginSite) -> None:
    session = PlaywrightBrowserSession.open(headless=True)
    try:
        session.goto(login_site.login_url)
        session.page.locator("#fixture-login").click()
        snapshot = SessionSnapshotCollectorAdapter(
            session=session,
            limits=SnapshotLimits(),
        ).collect(login_site.dashboard_url)
    finally:
        session.close()

    assert snapshot.source.final_url == login_site.dashboard_url
    assert any(element.attributes.get("id") == "signed-in-marker" for frame in snapshot.frames for element in frame.elements)
```

- [ ] **Step 2: 运行测试，确认因会话接口缺失失败。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration\test_login_browser.py::test_session_collector_observes_login_only_dashboard`

Expected: import error for `PlaywrightBrowserSession` 或 `SessionSnapshotCollectorAdapter`。

- [ ] **Step 3: 抽取页面观察并实现内存会话。**

将 `PlaywrightBrowserSource.collect` 中从 `page.goto` 到构造 `RawPageObservation` 的代码抽为只接收既有 `Page` 的私有函数，例如 `_collect_page_observation(page, url, limits, deadline)`。现有 source 继续通过 `_managed_page` 调用它，保持 Sprint 1 行为不变。

`PlaywrightBrowserSession` 使用 `sync_playwright()`、`chromium.launch()`、单一 `browser.new_context()` 和单一 Page；注册与现有 source 相同的 observation/scroll selector。`collect` 必须复用该 Page 并调用同一个私有观察函数。`close` 必须按 Page、Context、Browser、Playwright 顺序幂等关闭，且类中不得出现 `storage_state`。

`SessionSnapshotCollectorAdapter` 以 `session + limits` 安全构造并默认自行创建
`SnapshotCollector(source=session)`；显式注入 Collector 时必须拒绝 source 与 session 身份不一致。
`HumanLoginSession` 也必须验证 Collector 与 Browser Session 绑定同一对象。异常面与
`SnapshotCollectorAdapter` 保持一致：对 `CollectionFailedError` 仅抛出固定的
`"Controlled exploration snapshot collection failed."`。

- [ ] **Step 4: 运行真实浏览器回归。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration\test_login_browser.py tests\snapshot\test_browser.py`

Expected: 本地 fixture 浏览器测试通过；`repr(snapshot)`、日志和测试输出不含 fixture 登录 Cookie 或密码文本。

- [ ] **Step 5: 提交会话采集。**

```powershell
git add backend/src/ai_ui_explorer/snapshot/browser.py backend/src/ai_ui_explorer/exploration/collector_adapter.py backend/tests/exploration/test_login_browser.py backend/tests/snapshot/conftest.py backend/tests/fixtures/login_site
git commit -m "feat: add in-memory browser session collector"
```

## Task 3: 人机协同认证运行时

**Files:**
- Create: `backend/src/ai_ui_explorer/exploration/login_runtime.py`
- Create: `backend/tests/exploration/test_login_runtime.py`
- Modify: `backend/src/ai_ui_explorer/exploration/__init__.py`

**Interfaces:**
- Consumes: `ExplorationTask`, `AuthenticationPlan`, `PlaywrightBrowserSession`, `SessionSnapshotCollectorAdapter`。
- Produces: `HumanLoginSession.start()`, `confirm_and_verify() -> AuthenticationVerification`, `collector_port() -> SnapshotCollectorPort`, `close()`。

- [ ] **Step 1: 写失败测试，覆盖确认门、失败回退与终态销毁。**

```python
def test_collector_is_unavailable_before_manual_confirmation() -> None:
    runtime = make_runtime(checkpoint_present=True)
    runtime.start()

    with pytest.raises(HumanLoginRuntimeError, match="Authentication is not verified"):
        runtime.collector_port()


def test_failed_verification_returns_to_pause_without_checkpoint() -> None:
    runtime = make_runtime(checkpoint_present=False)
    runtime.start()

    result = runtime.confirm_and_verify()

    assert result.authenticated is False
    assert runtime.task.state is ExplorationTaskState.PAUSED_FOR_HUMAN
    assert runtime.task.checkpoint_id is None
```

- [ ] **Step 2: 运行测试，确认因运行时缺失失败。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration\test_login_runtime.py`

Expected: import error for `HumanLoginSession`。

- [ ] **Step 3: 实现最小状态编排。**

```python
def start(self) -> None:
    self._plan.validate(self._policy)
    self._task.start_collection()
    self._browser.goto(self._plan.authentication_url)
    self._task.pause_for_human(reason_code="authentication_required")

def confirm_and_verify(self) -> AuthenticationVerification:
    self._task.confirm_human_ready()
    verified = (
        self._browser.current_url.startswith(self._plan.post_login_url_prefix)
        and self._browser.has_css(self._plan.checkpoint_css_selector)
    )
    checkpoint_id = "configured_post_login_checkpoint" if verified else None
    self._task.record_authentication_result(
        authenticated=verified,
        checkpoint_id=checkpoint_id,
    )
    return AuthenticationVerification(
        authenticated=verified,
        reason_code="verified" if verified else "checkpoint_not_verified",
        checkpoint_id=checkpoint_id,
    )
```

`confirm_and_verify` 必须先确认当前 URL 被 policy 作为目标 Origin 允许，再执行 `has_css`；若 Browser 关闭或验证异常，只返回固定失败原因码并使任务回到暂停状态。`close` 必须调用 Browser Session 的 `close`；`complete`、`partial`、`cancel` 和运行时异常路径调用同一清理函数。

- [ ] **Step 4: 运行运行时测试。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration\test_login_runtime.py tests\exploration\test_task.py`

Expected: 未确认不可恢复、验证失败不可认证、终态不可再采集均通过。

- [ ] **Step 5: 提交运行时。**

```powershell
git add backend/src/ai_ui_explorer/exploration/login_runtime.py backend/src/ai_ui_explorer/exploration/__init__.py backend/tests/exploration/test_login_runtime.py
git commit -m "feat: add human login runtime"
```

## Task 4: 本地登录验收、文档与质量门

**Files:**
- Modify: `docs/00-project-context.md`
- Modify: `docs/02-architecture.md`
- Modify: `docs/07-roadmap.md`
- Modify: `docs/superpowers/plans/2026-07-31-controlled-exploration.md`

**Interfaces:**
- Consumes: `HumanLoginSession`, `ExplorationRunner`, 本地 `login_site` fixture。
- Produces: 人工登录后只读探索的真实 Chromium 端到端验收。

- [ ] **Step 1: 写失败端到端测试。**

```python
def test_human_login_runtime_resumes_controlled_exploration(login_site: LoginSite) -> None:
    runtime, task, browser = make_browser_runtime(login_site)
    try:
        runtime.start()
        simulate_human_login(runtime)

        assert runtime.confirm_and_verify().authenticated is True

        result = ExplorationRunner(
            policy=login_site.policy,
            budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
            collector=runtime.collector_port(),
            task=task,
        ).run(modules=[ModuleEntry(module_id="dashboard", url=login_site.dashboard_url)])

        assert result.status == "completed"
        assert len(result.visits) == 1
        assert task.state is ExplorationTaskState.COMPLETED
        assert browser_session_is_closed(browser)
    finally:
        runtime.close()
```

- [ ] **Step 2: 运行端到端测试，确认在运行时实现前失败。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration\test_login_browser.py::test_human_login_runtime_resumes_controlled_exploration`

Expected: 运行时或本地登录 fixture 缺失。

- [ ] **Step 3: 更新完成状态文档。**

文档必须明确：已实现的是本地、内存态、人工确认、配置验证的人机协同登录运行时；未实现跨任务复用、加密存储、SSO/扫码/MFA、前端确认页、外部站点登录与访问控制绕过。

- [ ] **Step 4: 运行质量门。**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\exploration tests\snapshot\test_browser.py`

Run: `..\.venv\Scripts\python.exe -m ruff check --no-cache .`

Run: `..\.venv\Scripts\python.exe -m mypy --cache-dir ..\.mypy_cache_codex src\ai_ui_explorer`

Run: `git diff --check`

Expected: 全部命令退出码为 0；不因工具输出会话结束而假定 pytest 已完成，应确认实际 Python pytest 进程已退出。

- [ ] **Step 5: 提交验收与文档。**

```powershell
git add backend/tests/exploration/test_login_browser.py docs/00-project-context.md docs/02-architecture.md docs/07-roadmap.md docs/superpowers/plans/2026-07-31-controlled-exploration.md docs/superpowers/plans/2026-08-10-human-login-runtime.md
git commit -m "test: verify human login exploration runtime"
```

## 自检

- 认证 URL、登录后 URL 前缀与 CSS 检查点：Task 1。
- 内存会话、无 `storage_state`、绑定 Collector：Task 2。
- 人工确认、失败回退、同源检查、终态关闭：Task 3。
- 本地真实浏览器、恢复探索、文档与质量门：Task 4。
- 计划中没有 `TODO`、`TBD` 或未定义的接口名称；所有后续接口均在前序任务中定义。
