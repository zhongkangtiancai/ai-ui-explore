# Sprint 6：多身份受控探索与权限差异知识 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让测试人员以 2–5 个受控身份串行进行人工登录和只读探索，在当前进程内查看脱敏的页面/元素明细，并导出有证据和可靠性说明的 UI 可见性差异 JSON。

**Architecture:** 在现有 `ExplorationRunner` 与任务服务之间加入窄的 `ExplorationEvidenceSink`，只接收已验证、已脱敏的 Snapshot 和访问目标。每个身份运行形成私有 `IdentityEvidenceBundle`；全部身份终态后，纯函数比较器按保守页面/元素匹配规则生成 `PermissionComparisonResult`。比较服务保持现有单进程、串行 Browser Context、人工确认和终态清理模式；API/UI 只消费白名单视图和按需 Schema 校验导出。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、Playwright sync API、pytest、Vue 3、TypeScript、Vitest、Element Plus。

## Global Constraints

- 仅支持 2–5 个非敏感身份别名；身份之间共享模块入口、Origin、预算和只读动作门禁，但绝不共享 Browser/Context/Page/Collector/登录态。
- 不保存或响应账号、密码、Cookie、Token、验证码、Storage State、截图、网络正文、完整 HTML、浏览器对象或原始异常。
- 只允许既有只读链接导航；不得自动填写、点击业务按钮、提交表单、上传文件或绕过访问控制。
- 详细证据只存在当前进程私有内存；重启、崩溃或清理后不可恢复；下载不在服务器保存文件。
- 页面和元素缺失必须区分 `not_observed` 与 `inconclusive`；不得输出未经直接授权证据支持的 `permission_granted` 或 `permission_denied` 结论。
- 所有请求/响应模型 `extra="forbid"`，公开字段使用白名单、长度和敏感词校验；错误面固定且不回显输入或底层异常。
- 本 Sprint 仅使用本地多角色 HTTP fixture 和真实 Chromium 验收，不访问外站，不新增数据库、Redis、Worker、SSO/MFA/扫码适配或 LLM 推断。
- 每个任务先写失败测试并实际运行 RED；Green 后运行规定质量门并单独提交；未经用户明确确认不提交。

---

## 文件结构

| 路径 | 职责 |
| --- | --- |
| `backend/src/ai_ui_explorer/permission_comparison/models.py` | 版本化、脱敏的身份、页面/元素证据、差异和导出模型。 |
| `backend/src/ai_ui_explorer/permission_comparison/schema/permission-comparison-v1.schema.json` | 提交的导出 JSON Schema。 |
| `backend/src/ai_ui_explorer/permission_comparison/evidence.py` | Snapshot 到身份证据的纯投影和 Runner Evidence Sink。 |
| `backend/src/ai_ui_explorer/permission_comparison/comparator.py` | 保守、确定性的页面/元素匹配与可靠性计算。 |
| `backend/src/ai_ui_explorer/permission_comparison/service.py` | 比较任务注册、串行身份调度、人工登录、取消与导出。 |
| `backend/src/ai_ui_explorer/api/routes/permission_comparisons.py` | 白名单比较 API。 |
| `frontend/src/api/permissionComparisons.ts` | 比较 API 客户端和 TypeScript DTO。 |
| `frontend/src/components/PermissionComparisonForm.vue` | 共同探索配置和身份别名表单。 |
| `frontend/src/components/PermissionComparisonDetail.vue` | 身份进度、差异、页面/元素证据和下载入口。 |
| `backend/tests/permission_comparison/` | 模型、投影、比较器与服务测试。 |
| `backend/tests/api/test_permission_comparisons.py` | 安全 HTTP 和本地 Chromium E2E。 |
| `frontend/tests/PermissionComparison*.spec.ts` | 表单、详情、轮询、筛选和错误面测试。 |

---

### Task 1：身份、详细证据和比较导出模型

**Files:**
- Create: `backend/src/ai_ui_explorer/permission_comparison/__init__.py`
- Create: `backend/src/ai_ui_explorer/permission_comparison/models.py`
- Create: `backend/src/ai_ui_explorer/permission_comparison/schema/permission-comparison-v1.schema.json`
- Create: `backend/tests/permission_comparison/test_models.py`

**Interfaces:**
- Produces `IdentityProfile(identity_id, label, authentication_plan)`, `IdentityRunState`, `IdentityEvidenceBundle`, `PageEvidence`, `ElementEvidence`, `EvidenceReference`, `ObservationState`, `VisibilityDifference`, `PermissionComparisonResult` and `PermissionComparisonExport`.
- `PermissionComparisonExport.to_schema() -> dict[str, object]` must match the committed Schema.
- `IdentityProfile` rejects secrets, invalid aliases, duplicate IDs and more than five identities before any browser is created.

- [ ] **Step 1: Write failing model and Schema tests**

```python
def test_identity_profile_rejects_sensitive_aliases() -> None:
    with pytest.raises(ValidationError):
        IdentityProfile(identity_id="token-admin", label="管理员", authentication_plan=None)


def test_difference_requires_inconclusive_when_one_identity_is_partial() -> None:
    difference = VisibilityDifference(
        difference_id="difference-1",
        kind="observed_in_only_one_identity",
        subject_key="page:https://app.example.test/admin",
        identity_states={"admin": "observed", "user": "collection_incomplete"},
        evidence_refs=[make_evidence_ref()],
        reason_codes=["collection_truncated"],
    )
    assert difference.reliability == "inconclusive"


def test_permission_comparison_schema_matches_model() -> None:
    assert committed_schema() == PermissionComparisonExport.to_schema()
```

- [ ] **Step 2: Run RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_models.py`

Expected: FAIL because the comparison package does not yet exist.

- [ ] **Step 3: Implement the smallest closed model contract**

Implement frozen Pydantic models with `extra="forbid"`. Use `identity-<number>` and `comparison-<number>` public identifiers, `identity_id`/labels with explicit safe character and sensitive-term validation, and `Field(max_length=...)` on every displayable text. Model `identity_states` as the five declared observation states and calculate or validate reliability with this invariant:

```python
if any(state in {"collection_incomplete", "authentication_unverified", "collection_failed", "not_matchable"}
       for state in identity_states.values()):
    reliability = "inconclusive"
```

Only allow `observed_in_only_one_identity`, `observed_in_multiple_identities`, `safe_attribute_changed`, `link_target_changed`, and `not_comparable`. Do not declare business permission fields. Add a schema generation helper and commit its generated JSON Schema.

- [ ] **Step 4: Run Green and static checks**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_models.py`

Run: `..\.venv\Scripts\python.exe -m ruff check --no-cache src\ai_ui_explorer\permission_comparison tests\permission_comparison\test_models.py`

Run: `..\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml src\ai_ui_explorer\permission_comparison`

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/permission_comparison backend/tests/permission_comparison/test_models.py
git commit -m "feat: add permission comparison models"
```

---

### Task 2：Snapshot 证据投影与 Runner 钩子

**Files:**
- Create: `backend/src/ai_ui_explorer/permission_comparison/evidence.py`
- Modify: `backend/src/ai_ui_explorer/exploration/runner.py`
- Create: `backend/tests/permission_comparison/test_evidence.py`
- Modify: `backend/tests/exploration/test_runner.py`

**Interfaces:**
- Produces `ExplorationEvidenceSink` protocol: `record(target: ExplorationTarget, snapshot: SnapshotDocument) -> None` and `complete(result: ExplorationRunResult) -> None`.
- Produces `IdentityEvidenceCollector(identity_id).record(...)`, `.bundle(result) -> IdentityEvidenceBundle`.
- `ExplorationRunner(..., evidence_sink: ExplorationEvidenceSink | None = None)` calls `record` only after successful Snapshot collection and `complete` once for completed or partial runs.

- [ ] **Step 1: Write failing evidence tests**

```python
def test_evidence_collector_projects_only_safe_snapshot_fields() -> None:
    collector = IdentityEvidenceCollector(identity_id="identity-1")
    collector.record(make_target("https://app.example.test/admin"), sensitive_snapshot())
    payload = collector.bundle(make_completed_result()).model_dump_json().lower()
    assert "test-password" not in payload
    assert "cookie" not in payload
    assert collector.bundle(make_completed_result()).pages[0].elements[0].locator_hints


def test_runner_records_each_successful_snapshot_before_candidate_expansion() -> None:
    sink = RecordingEvidenceSink()
    result = make_runner(sink=sink).run(modules=[make_module()])
    assert [call.target.url for call in sink.calls] == [visit.target.url for visit in result.visits]
    assert sink.completed_with is result
```

- [ ] **Step 2: Run RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_evidence.py tests\exploration\test_runner.py -k "evidence or records_each"`

Expected: FAIL because no evidence sink is accepted or projected.

- [ ] **Step 3: Implement narrow evidence capture**

Add the optional sink parameter without changing existing callers. In the Runner, invoke `sink.record(target, snapshot)` after `record_snapshot_result()` and before candidate extraction; invoke `sink.complete(result)` in the existing `finally` path only when a result exists. Never catch and hide sink exceptions: an invalid private evidence projection must fail the bound task through the existing runner failure path.

Implement projection from `SnapshotDocument` only. Reuse existing sanitizer-produced fields, include target URL, Frame ID/path, tag, role, accessible name, limited text summary, safe attributes, `href`, bounds and locator candidates. Do not add raw HTML, input values, browser handles or response content. Generate `EvidenceReference` using existing Snapshot IDs/hash and JSON pointers, not copied full JSON.

- [ ] **Step 4: Run Green and regression tests**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_evidence.py tests\exploration\test_runner.py tests\snapshot\test_collector.py`

Expected: PASS, including existing collector behavior.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/permission_comparison/evidence.py backend/src/ai_ui_explorer/exploration/runner.py backend/tests/permission_comparison/test_evidence.py backend/tests/exploration/test_runner.py
git commit -m "feat: capture bounded exploration evidence"
```

---

### Task 3：确定性页面与元素可见性比较器

**Files:**
- Create: `backend/src/ai_ui_explorer/permission_comparison/comparator.py`
- Create: `backend/tests/permission_comparison/test_comparator.py`

**Interfaces:**
- Produces `PermissionComparator.compare(bundles: list[IdentityEvidenceBundle]) -> PermissionComparisonResult`.
- Produces pure helpers `canonical_page_key(url: str) -> str` and `element_match_key(page: PageEvidence, element: ElementEvidence) -> str | None`.
- Consumes only Task 1 models; it has no browser, filesystem, API or service dependency.

- [ ] **Step 1: Write failing comparison tests**

```python
def test_comparator_reports_admin_only_page_with_high_reliability() -> None:
    result = PermissionComparator().compare([
        complete_bundle("admin", pages=[page("/", elements=[]), page("/admin", elements=[])]),
        complete_bundle("user", pages=[page("/", elements=[])]),
    ])
    difference = find_difference(result, "page:https://app.example.test/admin")
    assert difference.kind == "observed_in_only_one_identity"
    assert difference.reliability == "high"


def test_comparator_marks_missing_page_inconclusive_after_budget_truncation() -> None:
    result = PermissionComparator().compare([
        complete_bundle("admin", pages=[page("/admin", elements=[])]),
        partial_bundle("user", reason_code="collection_truncated", pages=[]),
    ])
    assert find_difference(result, "page:https://app.example.test/admin").reliability == "inconclusive"


def test_comparator_matches_elements_only_by_unique_stable_key_in_same_frame() -> None:
    result = PermissionComparator().compare(two_bundles_with_same_testid_different_frames())
    assert all(item.kind == "not_comparable" for item in result.differences)
```

- [ ] **Step 2: Run RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_comparator.py`

Expected: FAIL because comparator does not exist.

- [ ] **Step 3: Implement deterministic comparison**

Retain the observed page URL: `/` and `/index.html` are distinct unless a future, evidence-backed application rule explicitly establishes an alias. Retain query/fragment as distinct. Sort identity IDs, pages and element keys before assigning IDs.

For elements, return a key only for same-frame unique `testid`, unique safe `id`, unique exact role/name, or unique safe link target combined with role/name. Do not use CSS, XPath, position, class, free text or traversal index as the sole cross-identity identity. Compare only allowlisted scalar attributes and `href`. Any partial run, unverified authentication, failed collection or missing match key emits `not_comparable`/`inconclusive` with the declared reason code.

- [ ] **Step 4: Run Green and deterministic test**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_comparator.py`

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_models.py -k deterministic`

Expected: PASS; repeated input produces byte-identical JSON.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/permission_comparison/comparator.py backend/tests/permission_comparison/test_comparator.py
git commit -m "feat: compare identity visibility evidence"
```

---

### Task 4：串行多身份任务服务与人工登录编排

> 实施状态（2026-08-12）：已完成实现与专项验证，待独立复核和本地提交。每个身份继续复用独立的单任务 Browser Context 与线程；比较服务只接收经脱敏的证据包和终态摘要，不共享登录态。

**Files:**
- Create: `backend/src/ai_ui_explorer/permission_comparison/service.py`
- Modify: `backend/src/ai_ui_explorer/task_management/service.py`
- Create: `backend/tests/permission_comparison/test_service.py`
- Modify: `backend/tests/task_management/test_service.py`

**Interfaces:**
- Produces `CreatePermissionComparisonCommand`, `PermissionComparisonService.create()`, `.get()`, `.confirm_login(comparison_id, identity_id)`, `.cancel()`, `.pages()`, `.page_detail()`, `.differences()`, `.export()`.
- Consumes existing `_TaskRuntimeContext`, `HumanLoginSession`, `ExplorationRunner`, `ExplorationCancellationToken`, Task 2 `IdentityEvidenceCollector`, and Task 3 `PermissionComparator`.
- Adds an optional `evidence_sink` factory argument to the existing service runner construction without exposing raw `ExplorationTask` beyond the existing private capability boundary.

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_service_runs_identities_serially_and_closes_each_runtime() -> None:
    service, runtimes = make_service_with_two_identity_fixture()
    comparison = service.create(two_identity_command())
    wait_for_identity(comparison.comparison_id, "admin", "paused_for_human")
    service.confirm_login(comparison.comparison_id, "admin")
    wait_for_identity(comparison.comparison_id, "user", "paused_for_human")
    assert runtimes["admin"].close_calls == 1


def test_service_cancellation_stops_current_identity_and_never_starts_next() -> None:
    service, runtimes = make_service_with_two_identity_fixture()
    comparison = service.create(two_identity_command())
    service.cancel(comparison.comparison_id)
    wait_for_terminal(comparison.comparison_id)
    assert runtimes["user"].start_calls == 0


def test_failed_identity_keeps_completed_identity_evidence_but_result_is_partial() -> None:
    comparison = run_admin_success_user_authentication_failure()
    assert comparison.state == "partial"
    assert comparison.identities["admin"].page_count > 0
    assert all(item.reliability == "inconclusive" for item in comparison.differences)
```

- [ ] **Step 2: Run RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_service.py`

Expected: FAIL because comparison service does not exist.

- [ ] **Step 3: Implement private serial scheduler**

Store a comparison handle in process-local, locked memory. Reuse existing task state transitions per identity, but do not serialize child `ManagedTask` runtime data. Start identity N+1 only after N is terminal and its Context close callback has run. `confirm_login` checks that the provided identity is exactly the current paused identity; it sends only the existing confirmation signal.

Attach `IdentityEvidenceCollector` to the Runner via Task 2's sink. After every identity terminal state, project the bundle, discard browser/runtime handles, and proceed or finalize. When all identities finish, run `PermissionComparator`; if any identity is not completed, mark the comparison `partial` and preserve evidence with `inconclusive` differences. Cancellation signals the current token, closes current runtime through existing callbacks, and prevents future starts. Fixed safe reason codes only.

- [ ] **Step 4: Run Green plus existing login regression**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_service.py tests\task_management\test_service.py tests\exploration\test_login_runtime.py`

Expected: PASS; existing single-task login behavior remains unchanged.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/permission_comparison/service.py backend/src/ai_ui_explorer/task_management/service.py backend/tests/permission_comparison/test_service.py backend/tests/task_management/test_service.py
git commit -m "feat: orchestrate serial identity comparisons"
```

---

### Task 5：安全比较 API 与下载导出

**Files:**
- Create: `backend/src/ai_ui_explorer/api/routes/permission_comparisons.py`
- Modify: `backend/src/ai_ui_explorer/api/router.py`
- Modify: `backend/src/ai_ui_explorer/main.py`
- Create: `backend/tests/api/test_permission_comparisons.py`

**Interfaces:**
- Implements `POST /api/v1/permission-comparisons`, detail, identity pages, page detail, differences, export, per-identity confirm-login, and comparison cancel endpoints from the approved design.
- `GET /export` sends `application/json` with `Content-Disposition: attachment; filename="permission-comparison.json"`; content is built from `PermissionComparisonExport` and Schema validated before sending.

- [ ] **Step 1: Write failing API security tests**

```python
def test_create_comparison_and_read_safe_differences(client: TestClient) -> None:
    created = client.post("/api/v1/permission-comparisons", json=two_identity_payload())
    assert created.status_code == 202
    detail = client.get(f"/api/v1/permission-comparisons/{created.json()['comparison_id']}")
    assert detail.status_code == 200
    assert "cookie" not in detail.text.lower()


@pytest.mark.parametrize("field", ["password", "token", "cookie", "storage_state"])
def test_create_rejects_credentials_without_echoing_them(client: TestClient, field: str) -> None:
    response = client.post("/api/v1/permission-comparisons", json={**two_identity_payload(), field: "secret"})
    assert response.status_code == 422
    assert field not in response.text.lower()


def test_export_is_schema_valid_and_never_contains_browser_data(client: TestClient) -> None:
    comparison_id = completed_comparison(client)
    response = client.get(f"/api/v1/permission-comparisons/{comparison_id}/export")
    assert response.headers["content-type"].startswith("application/json")
    validate_export(response.json())
    assert "storage_state" not in response.text.lower()
```

- [ ] **Step 2: Run RED**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\api\test_permission_comparisons.py`

Expected: FAIL with missing route.

- [ ] **Step 3: Implement allowlisted HTTP boundary**

Create request models for common configuration and identities; use explicit empty operation bodies for confirm/cancel. Convert `TaskServiceError`, unknown IDs, identity mismatch and terminal states to existing fixed error patterns without including exception text. Limit page/difference list filtering to enum values, integer limits and known identity IDs. Ensure the app lifespan initializes exactly one `PermissionComparisonService` with the same safe collector/runtime factories used by local task service.

- [ ] **Step 4: Run Green and health/API regression**

Run: `..\.venv\Scripts\python.exe -m pytest -q tests\api\test_permission_comparisons.py tests\api\test_exploration_tasks.py tests\test_health.py`

Run: `..\.venv\Scripts\python.exe -m ruff check --no-cache src\ai_ui_explorer\api tests\api`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/api backend/src/ai_ui_explorer/main.py backend/tests/api/test_permission_comparisons.py
git commit -m "feat: expose permission comparison api"
```

---

### Task 6：Vue 比较创建、明细与可靠性视图

**Files:**
- Create: `frontend/src/api/permissionComparisons.ts`
- Create: `frontend/src/components/PermissionComparisonForm.vue`
- Create: `frontend/src/components/PermissionComparisonDetail.vue`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/PermissionComparisonForm.spec.ts`
- Create: `frontend/tests/PermissionComparisonDetail.spec.ts`

**Interfaces:**
- Produces `CreatePermissionComparisonRequest`, comparison DTOs, create/fetch/confirm/cancel/download client functions.
- `PermissionComparisonForm` emits only a common safe config and 2–5 aliases; it never emits credential fields.
- `PermissionComparisonDetail` accepts a comparison DTO and emits `confirm-login`, `cancel`, `select-page`, and `download` actions.

- [ ] **Step 1: Write failing component tests**

```ts
it('requires two safe identity aliases and never renders credential inputs', async () => {
  const wrapper = mount(PermissionComparisonForm)
  expect(wrapper.findAll('[data-test="identity-label"]').length).toBe(2)
  expect(wrapper.html().toLowerCase()).not.toContain('password')
  await wrapper.get('[data-test="add-identity"]').trigger('click')
  expect(wrapper.findAll('[data-test="identity-label"]').length).toBe(3)
})


it('shows inconclusive differences with their reason instead of a permission denial', () => {
  const wrapper = mount(PermissionComparisonDetail, { props: { comparison: inconclusiveComparison } })
  expect(wrapper.text()).toContain('无法确认')
  expect(wrapper.text()).not.toContain('无权限')
})


it('stops polling after a terminal comparison', async () => {
  vi.useFakeTimers()
  const wrapper = mountComparisonPageWith(completedComparison)
  await vi.advanceTimersByTimeAsync(4000)
  expect(fetchPermissionComparison).not.toHaveBeenCalled()
  wrapper.unmount()
})
```

- [ ] **Step 2: Run RED**

Run: `pnpm test -- PermissionComparisonForm PermissionComparisonDetail`

Expected: FAIL because components and client do not exist.

- [ ] **Step 3: Implement minimal safe UI**

Add a task-mode switch without removing existing single-task flow. Require at least two identities and at most five. Per-identity login configuration remains optional and only accepts authentication URL, post-login prefix and checkpoint selector; no login value fields exist.

Render identity execution state, current identity confirmation action, comparison summary, page table, selected page evidence, difference list and explicit reliability/reason labels. Default filter is high/medium; include a deliberate toggle for low/inconclusive. Download uses the browser Blob API against the export endpoint and does not cache JSON in local storage. Poll detail every two seconds only while nonterminal; stop on terminal, request error or unmount.

- [ ] **Step 4: Run Green and frontend quality gate**

Run: `pnpm test -- PermissionComparisonForm PermissionComparisonDetail`

Run: `pnpm lint`

Run: `pnpm typecheck`

Run: `pnpm build`

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src frontend/tests
git commit -m "feat: add permission comparison views"
```

---

### Task 7：多角色真实 Chromium E2E、文档与完整质量门

**Files:**
- Create: `backend/tests/api/fixtures/permission_comparison_site.py`
- Modify: `backend/tests/api/test_permission_comparisons.py`
- Modify: `docs/00-project-context.md`
- Modify: `docs/02-architecture.md`
- Modify: `docs/07-roadmap.md`
- Modify: `docs/superpowers/plans/2026-08-12-permission-aware-exploration.md`

**Interfaces:**
- Local fixture exposes three fictional roles: `admin`, `member`, `restricted`; only test helpers may simulate login actions.
- E2E creates a comparison through public API, waits for each identity's intended state, confirms login, polls terminal result, reads a page difference and downloads export.

- [ ] **Step 1: Write failing realistic E2E tests**

```python
def test_local_multirole_comparison_reports_observed_admin_difference(login_site: PermissionComparisonSite) -> None:
    comparison_id = create_comparison_for(login_site, identities=["admin", "member"])
    login_site.complete_login_for_current_visible_context("admin")
    confirm_current_identity(comparison_id, "identity-1")
    login_site.complete_login_for_current_visible_context("member")
    confirm_current_identity(comparison_id, "identity-2")
    result = wait_for_comparison_terminal(comparison_id)
    assert result.state == "completed"
    assert difference_for(result, "/admin").reliability == "high"


def test_restricted_or_truncated_identity_is_inconclusive_and_contexts_close(login_site: PermissionComparisonSite) -> None:
    comparison_id = create_restricted_or_truncated_comparison(login_site)
    result = wait_for_comparison_terminal(comparison_id)
    assert result.state == "partial"
    assert all(item.reliability == "inconclusive" for item in result.differences)
    assert login_site.all_contexts_closed()
```

- [ ] **Step 2: Run RED**

Run: `$env:PLAYWRIGHT_BROWSERS_PATH='..\\.playwright-browsers'; ..\.venv\Scripts\python.exe -m pytest -q tests\api\test_permission_comparisons.py -k "multirole or restricted"`

Expected: FAIL until Tasks 1–6 are complete.

- [ ] **Step 3: Implement fixture-only minimum and update documentation**

Build the site from in-memory local HTTP fixture handlers using fictional credentials embedded only in tests. Do not add it to product runtime or git-tracked outputs. Update documents to state exactly: multi-identity UI visibility comparison is implemented only in process-local memory, receives manual login assistance, has local fixture Chromium evidence, and does not prove backend data scope or business authorization.

- [ ] **Step 4: Run complete quality gate**

Run: `$env:PLAYWRIGHT_BROWSERS_PATH='..\\.playwright-browsers'; ..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison tests\task_management tests\api tests\exploration tests\snapshot\test_browser.py`

Run: `..\.venv\Scripts\python.exe -m ruff check --no-cache .`

Run: `..\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml --cache-dir ..\.mypy_cache_sprint6 src\ai_ui_explorer`

Run: `pnpm test && pnpm lint && pnpm typecheck && pnpm build`

Run: `git diff --check`

Expected: every command exits 0; explicitly wait for pytest's Python process to exit, not merely for progress output to reach 100%.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/api docs
git commit -m "test: verify permission-aware exploration"
```

## Plan self-review

- Model/Schema, evidence capture, conservative comparison, serial browser lifecycle, API, UI and local Chromium acceptance each have a separate independently testable task.
- Every requirement in the approved Sprint 6 specification maps to Tasks 1–7; database, Worker, external sites, credential storage, business actions, LLM inference and V1.1 history remain explicitly absent.
- All cross-task names are introduced before use: Task 1 models, Task 2 collector, Task 3 comparator, Task 4 service, Task 5 API, Task 6 UI, Task 7 fixture/quality gate.
- The plan contains no placeholders; the risky condition “missing observation is a permission denial” is tested explicitly as prohibited behavior.
