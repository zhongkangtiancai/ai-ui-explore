# Sprint 7 探索结果明细与证据浏览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为单次受控探索任务保存进程内、脱敏、可追溯的页面与元素证据，并在 API 和 Vue 中安全浏览及导出。

**Architecture:** 在现有 Runner 的 `ExplorationEvidenceSink` 边界建立带锁的单任务证据收集器。它复用并扩展 Sprint 6 的共享证据模型，将每个成功 Snapshot 立即投影为页面、元素、边界和定位器候选；任务服务只保留该投影，不保留 Snapshot 或浏览器。FastAPI 与 Vue 都只消费受限投影，重启后由既有任务注册表语义自然丢失。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、Playwright、Vue 3、TypeScript、Vitest、Vue Test Utils。

## Global Constraints

- 只保存当前进程内的受限投影；禁止持久化原始 Snapshot、DOM、HTML、浏览器对象、Cookie、Token、输入值、网络正文或登录态。
- 复用现有文本、URL、href 与属性脱敏；只使用已有白名单字段和已验证的 Snapshot 定位器候选。
- `partial`、失败、取消不能被描述为页面不存在、权限拒绝、后端数据权限或业务授权结论。
- 保持 `/` 与 `/index.html` 为不同页面，除非未来存在证据支持的应用级别别名规则。
- API、导出、前端均为只读；不新增元素点击、输入、重放或浏览器控制。
- 文档使用简体中文，代码字段使用英文；每项新增行为先有失败测试。

---

### Task 1: 扩展共享受限证据模型与 Snapshot 投影

**Files:**
- Modify: `backend/src/ai_ui_explorer/permission_comparison/models.py`
- Modify: `backend/src/ai_ui_explorer/permission_comparison/evidence.py`
- Modify: `backend/tests/permission_comparison/test_evidence.py`
- Modify: `backend/tests/permission_comparison/test_models.py`

**Interfaces:**
- Produces `LocatorCandidateEvidence` with strategy, redacted parameters, recommendation, uniqueness, stability, confidence, frame scope and evidence references.
- Extends `ElementEvidence` with `visible`, `enabled`, `bounds: BoundsEvidence | None`, `locator_candidates: list[LocatorCandidateEvidence]`; retains `locator_hints: list[str]`.
- Produces `project_snapshot(target: ExplorationTarget, snapshot: SnapshotDocument, redactor: Redactor) -> PageEvidence`, shared by comparison and single-task evidence collection.

- [x] **Step 1: Write failing model and projection tests**

```python
def test_element_evidence_exposes_bounded_locator_candidates_and_bounds() -> None:
    evidence = collect_one_locator_snapshot().bundle(state="completed").pages[0].elements[0]
    assert evidence.visible is True
    assert evidence.bounds is not None
    candidate = evidence.locator_candidates[0]
    assert candidate.strategy in {"role", "test_id", "css", "xpath", "position"}
    assert candidate.parameters
    assert candidate.recommended in {True, False}
    assert candidate.evidence_refs[0].json_pointer.startswith("/locator_candidates/")


def test_projection_never_retains_secret_attribute_or_raw_snapshot() -> None:
    page = project_snapshot(target=target(), snapshot=sensitive_snapshot(), redactor=Redactor())
    dumped = page.model_dump_json()
    assert "fixture-secret" not in dumped
    assert "password" not in dumped.lower()
    assert not hasattr(page, "snapshot")
```

- [x] **Step 2: Run RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_evidence.py tests\permission_comparison\test_models.py -k "locator or bounds or projection"
```

Expected: FAIL because the new evidence fields and shared projection function do not exist.

- [x] **Step 3: Implement bounded model and projection**

```python
class BoundsEvidence(DeepFrozenModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class LocatorCandidateEvidence(DeepFrozenModel):
    locator_id: str = Field(min_length=1, max_length=120)
    strategy: Literal["role", "label", "placeholder", "text", "test_id", "attribute", "css", "xpath", "position"]
    parameters: dict[str, str | int | float] = Field(max_length=8)
    recommended: bool
    uniqueness: str
    stability: str
    confidence: str
    frame_path: str = Field(min_length=1, max_length=500)
    evidence_refs: list[EvidenceReference] = Field(min_length=1, max_length=2)
```

Map candidates by `(frame_ref, element_ref)` from `SnapshotDocument.locator_candidates`. Redact every string parameter using the existing `Redactor`; retain numeric position parameters unchanged; exclude parameters outside scalar `str | int | float`. Build a locator `EvidenceReference` using `/locator_candidates/{index}`. Map `element.bounds` only to numeric `BoundsEvidence`; map `visible` and `enabled` directly. Sort candidates by existing Snapshot candidate order and retain current `locator_hints` IDs for compatibility.

- [x] **Step 4: Run Green and Sprint 6 regression**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison\test_evidence.py tests\permission_comparison\test_models.py tests\permission_comparison\test_comparator.py
..\..\.venv\Scripts\python.exe -m ruff check --no-cache src\ai_ui_explorer\permission_comparison tests\permission_comparison
```

Expected: all tests pass and all exported comparison evidence remains Schema-valid.

- [x] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/permission_comparison/models.py backend/src/ai_ui_explorer/permission_comparison/evidence.py backend/tests/permission_comparison/test_evidence.py backend/tests/permission_comparison/test_models.py
git commit -m "feat: enrich bounded evidence details"
```

---

### Task 2: 单次任务证据收集、私有存储与服务读取

**Files:**
- Create: `backend/src/ai_ui_explorer/task_management/evidence.py`
- Modify: `backend/src/ai_ui_explorer/task_management/models.py`
- Modify: `backend/src/ai_ui_explorer/task_management/service.py`
- Modify: `backend/src/ai_ui_explorer/task_management/__init__.py`
- Create: `backend/tests/task_management/test_evidence.py`
- Modify: `backend/tests/task_management/test_service.py`

**Interfaces:**
- Produces `TaskEvidenceCollector.record(target, snapshot)`, `.complete(result)`, `.pages() -> list[TaskPageView]`, `.page_detail(page_id) -> PageEvidence | None`, `.export(task_summary) -> ExplorationEvidenceExport`.
- Produces `TaskPageView(page_id, page_key, frame_count, element_count, link_count, status, reason_codes, evidence_refs)`.
- Adds `ExplorationTaskService.pages(task_id)`, `.page_detail(task_id, page_id)`, `.export(task_id)` without exposing `ManagedTask`, `SnapshotDocument`, runner or browser objects. `page_id` is a task-local safe identifier; `page_key` remains a redacted display URL and is never used as a unique key.

- [x] **Step 1: Write failing lifecycle tests**

```python
def test_task_evidence_collector_keeps_projected_pages_after_partial_run() -> None:
    service = service_with_two_visit_runner(second_visit_fails=True)
    task = service.create(command())
    wait_for_terminal(service, task.task_id)
    assert service.get(task.task_id).state == "partial"
    assert [page.page_id for page in service.pages(task.task_id)] == ["page-1"]


def test_task_evidence_detail_and_export_do_not_expose_snapshot_or_browser() -> None:
    service = completed_service_with_locator_page()
    task = service.create(command())
    detail = service.page_detail(task.task_id, "https://app.example.test/one")
    exported = service.export(task.task_id)
    assert detail is not None
    assert detail.elements[0].locator_candidates
    serialized = exported.model_dump_json()
    assert "SnapshotDocument" not in serialized
    assert "cookie" not in serialized.lower()
    assert "browser" not in serialized.lower()
```

- [x] **Step 2: Run RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\task_management\test_evidence.py tests\task_management\test_service.py -k "evidence or partial"
```

Expected: FAIL because task evidence collector and service readers do not exist.

- [x] **Step 3: Implement task-private evidence bridge**

```python
class TaskEvidenceCollector(ExplorationEvidenceSink):
    def record(self, target: ExplorationTarget, snapshot: SnapshotDocument) -> None: ...
    def complete(self, result: ExplorationRunResult) -> None: ...
    def pages(self) -> list[TaskPageView]: ...
    def page_detail(self, page_id: str) -> PageEvidence | None: ...
```

Create one collector inside `ExplorationTaskService.create()` for every task and pass it to `_TaskRuntimeContext(evidence_sink=collector)`. Keep it only in `_TaskExecution`; never attach it to `TaskSummary` or `ManagedTask`. `TaskPageView` derives counts from its `PageEvidence`; `link_count` counts elements with non-null `href`. Assign `status="completed"` only after a recorded page; if runner result is partial, set collector reason codes from fixed runner `stop_reasons` and leave previously recorded pages readable. Export wraps task ID, task state, `TaskResultSummary`, pages and fixed reason codes; validate with `model_json_schema()` before returning.

- [x] **Step 4: Run Green and task-management regression**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\task_management\test_evidence.py tests\task_management\test_service.py tests\exploration\test_runner.py
..\..\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml --cache-dir ..\.mypy-cache-sprint7-task2 src\ai_ui_explorer
```

Expected: all tests pass; old summaries keep only counts and source summary.

- [x] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/task_management backend/tests/task_management
git commit -m "feat: retain bounded task evidence"
```

---

### Task 3: 任务明细 API、Schema 校验导出与安全错误

**Files:**
- Modify: `backend/src/ai_ui_explorer/api/routes/exploration_tasks.py`
- Modify: `backend/src/ai_ui_explorer/main.py`
- Modify: `backend/tests/api/test_exploration_tasks.py`

**Interfaces:**
- Produces `GET /api/v1/exploration-tasks/{task_id}/pages -> list[TaskPageView]`.
- Produces `GET /api/v1/exploration-tasks/{task_id}/pages/{page_id} -> PageEvidence`.
- Produces `GET /api/v1/exploration-tasks/{task_id}/export` as `application/json` attachment named `exploration-evidence.json`.

- [x] **Step 1: Write failing API contract tests**

```python
def test_pages_detail_and_export_are_safe_and_schema_valid(client: TestClient) -> None:
    task_id = completed_task_with_evidence(client)
    pages = client.get(f"/api/v1/exploration-tasks/{task_id}/pages")
    assert pages.status_code == 200
    page_id = pages.json()[0]["page_id"]
    detail = client.get(f"/api/v1/exploration-tasks/{task_id}/pages/{page_id}")
    assert detail.status_code == 200
    assert detail.json()["elements"][0]["locator_candidates"]
    exported = client.get(f"/api/v1/exploration-tasks/{task_id}/export")
    assert exported.headers["content-type"].startswith("application/json")
    assert "attachment; filename=exploration-evidence.json" in exported.headers["content-disposition"]
    assert "password" not in exported.text.lower()
    assert "cookie" not in exported.text.lower()


def test_unknown_task_and_page_return_fixed_safe_errors(client: TestClient) -> None:
    assert client.get("/api/v1/exploration-tasks/task-999/pages").status_code == 404
    assert client.get("/api/v1/exploration-tasks/task-1/pages/unknown").status_code == 404
```

- [x] **Step 2: Run RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\api\test_exploration_tasks.py -k "pages or export"
```

Expected: FAIL because the three routes do not exist.

- [x] **Step 3: Implement only the allowlisted read routes**

```python
@router.get("/{task_id}/pages", response_model=list[TaskPageView])
def get_task_pages(...): ...

@router.get("/{task_id}/pages/{page_id}", response_model=PageEvidence)
def get_task_page_detail(...): ...

@router.get("/{task_id}/export")
def export_task_evidence(...) -> Response: ...
```

Use `urllib.parse.unquote` only as needed by FastAPI’s route parameter handling; do not accept query filters or request body fields. Convert missing task/page to existing fixed 404 error helper. Build export bytes using `ExplorationEvidenceExport.model_dump_json()`, validate JSON against its generated schema with the existing `jsonschema` dependency, then return `Response` with fixed `Content-Disposition`. Do not log or include exceptions in HTTP responses.

- [x] **Step 4: Run Green and API regression**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\api\test_exploration_tasks.py tests\api\test_permission_comparisons.py tests\test_health.py
..\..\.venv\Scripts\python.exe -m ruff check --no-cache src\ai_ui_explorer\api tests\api
```

Expected: all API tests pass; comparison routes remain unchanged.

- [x] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/api/routes/exploration_tasks.py backend/src/ai_ui_explorer/main.py backend/tests/api/test_exploration_tasks.py
git commit -m "feat: expose exploration evidence details"
```

---

### Task 4: Vue 探索证据浏览与下载

**Files:**
- Create: `frontend/src/components/ExplorationEvidenceBrowser.vue`
- Modify: `frontend/src/api/explorationTasks.ts`
- Modify: `frontend/src/components/ExplorationTaskDetail.vue`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/ExplorationEvidenceBrowser.spec.ts`
- Modify: `frontend/tests/ExplorationTaskDetail.spec.ts`

**Interfaces:**
- Produces `fetchExplorationTaskPages(taskId)`, `fetchExplorationTaskPageDetail(taskId, pageKey)`, `downloadExplorationTaskEvidence(taskId)`.
- Produces `ExplorationEvidenceBrowser` with props `{ taskId: string; taskState: TaskState }`.
- Emits no browser-control event; all operations are GET/download only.

- [x] **Step 1: Write failing component tests**

```ts
it('lists pages, frames, elements and locator candidates without rendering HTML', async () => {
  mockedFetchPages.mockResolvedValue([pageSummary])
  mockedFetchDetail.mockResolvedValue(locatorPage)
  const wrapper = mount(ExplorationEvidenceBrowser, { props: { taskId: 'task-1', taskState: 'completed' } })
  await flushPromises()
  await wrapper.get('[data-test="evidence-page"]').trigger('click')
  expect(wrapper.text()).toContain('role')
  expect(wrapper.text()).toContain('css')
  expect(wrapper.html().toLowerCase()).not.toContain('<html')
})


it('shows partial limitations and downloads through the API client', async () => {
  const wrapper = mount(ExplorationEvidenceBrowser, { props: { taskId: 'task-1', taskState: 'partial' } })
  await flushPromises()
  expect(wrapper.text()).toContain('采集不完整')
  await wrapper.get('[data-test="download-evidence"]').trigger('click')
  expect(mockedDownload).toHaveBeenCalledWith('task-1')
})
```

- [x] **Step 2: Run RED**

Run:

```powershell
cd frontend
pnpm test -- ExplorationEvidenceBrowser ExplorationTaskDetail
```

Expected: FAIL because the API client functions and component do not exist.

- [x] **Step 3: Implement the read-only evidence browser**

Define TypeScript DTOs matching Task 2/3 fields. URL-encode `taskId` and `pageKey`; download uses `fetch`, `Blob`, a temporary object URL, a clicked anchor and `URL.revokeObjectURL`, without localStorage.

The component loads the page list on mount and when `taskId` changes. It loads detail only after an explicit page selection. Group elements by `frame_path`, show tag/role/name/visible/enabled/href in a table, and show selected-element attributes, bounds, ordered `locator_candidates` and evidence references. Use text interpolation only (`{{ }}`); do not use `v-html`. Render a persistent statement: “这是已采集的脱敏证据，不代表页面完整性或业务权限。” Show “采集不完整” when `taskState === 'partial'` or page reasons are non-empty.

Embed the component below `ExplorationTaskDetail` summary. It remains readable for all task states and does not change task polling.

- [x] **Step 4: Run Green and frontend quality gate**

Run:

```powershell
cd frontend
pnpm test -- ExplorationEvidenceBrowser ExplorationTaskDetail App
pnpm lint
pnpm typecheck
pnpm format:check
pnpm build
```

Expected: all commands exit 0.

- [x] **Step 5: Commit**

```powershell
git add frontend/src/api/explorationTasks.ts frontend/src/components/ExplorationEvidenceBrowser.vue frontend/src/components/ExplorationTaskDetail.vue frontend/src/App.vue frontend/tests/ExplorationEvidenceBrowser.spec.ts frontend/tests/ExplorationTaskDetail.spec.ts
git commit -m "feat: browse exploration evidence"
```

---

### Task 5: 真实 Chromium 验收、文档和质量门

**Files:**
- Modify: `backend/tests/api/test_exploration_tasks.py`
- Modify: `frontend/tests/App.spec.ts`
- Modify: `docs/00-project-context.md`
- Modify: `docs/02-architecture.md`
- Modify: `docs/07-roadmap.md`
- Modify: `README.md`

**Interfaces:**
- Consumes the existing local HTTP fixture and public exploration-task API.
- Produces evidence-backed documentation that says the browser displays only process-local, already-collected, redacted evidence.

- [x] **Step 1: Write Chromium API E2E test**

```python
def test_local_browser_task_exposes_redacted_page_and_locator_details() -> None:
    app = production_task_app_for_local_fixture()
    with TestClient(app) as client:
        task_id = create_local_task(client)
        wait_for_terminal_task(client, task_id)
        pages = client.get(f"/api/v1/exploration-tasks/{task_id}/pages").json()
        assert len(pages) >= 2
        detail = client.get(
            f"/api/v1/exploration-tasks/{task_id}/pages/{pages[0]['page_id']}"
        ).json()
        assert detail["elements"]
        assert any(item["locator_candidates"] for item in detail["elements"])
    assert "fixture-password-do-not-return" not in str(detail)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; $env:PLAYWRIGHT_BROWSERS_PATH='D:\codexWS\codx-ai-ui-explorer\.playwright-browsers'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\api\test_exploration_tasks.py -k "redacted_page_and_locator_details"
```

Observed: this test was first added after Tasks 1–3 had landed, so it passed immediately against the completed evidence route rather than serving as a pre-implementation RED test.

- [x] **Step 3: Update documentation precisely**

Add Sprint 7 to context, architecture, roadmap and README. State all of the following explicitly:

```text
单次探索可以浏览当前进程内、已采集、脱敏的页面和元素证据。
详情不保存或显示原始 Snapshot、HTML、网络正文、Cookie、Token、输入值或浏览器对象。
partial 代表采集不完整，不代表权限拒绝或页面不存在。
服务重启后任务和证据均不可恢复。
定位器候选是观测信息，不承诺跨页面版本稳定，也不自动生成或执行代码。
```

- [x] **Step 4: Run full quality gate**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'; $env:PLAYWRIGHT_BROWSERS_PATH='D:\codexWS\codx-ai-ui-explorer\.playwright-browsers'; ..\..\.venv\Scripts\python.exe -m pytest -q tests\permission_comparison tests\task_management tests\api tests\exploration tests\snapshot\test_browser.py
..\..\.venv\Scripts\python.exe -m ruff check --no-cache .
..\..\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml --cache-dir ..\.mypy-cache-sprint7-final src\ai_ui_explorer
cd ..\frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm format:check
pnpm build
cd ..
git diff --check
```

Expected: every command exits 0; wait for the pytest Python process to exit before accepting progress output as a result.

- [x] **Step 5: Commit**

```powershell
git add backend/tests/api/test_exploration_tasks.py frontend/tests/App.spec.ts docs/00-project-context.md docs/02-architecture.md docs/07-roadmap.md README.md
git commit -m "test: verify exploration evidence browser"
```

## Plan Self-Review

- Task 1 covers shared evidence fields missing from Sprint 6: bounds, visibility/enabled state and complete safe locator candidate metadata.
- Task 2 makes single-task evidence process-local and readable after terminal states without persisting Snapshot or browser handles.
- Task 3 provides only read/list/detail/export API boundaries with Schema validation and fixed errors.
- Task 4 provides explicit page, Frame, element, locator and partial-state UI without HTML rendering or browser control.
- Task 5 provides real Chromium evidence, sensitive-value checks, documentation and full quality gate.
- The plan intentionally excludes complete page guarantees, authorization claims, raw DOM/network data, persistence, screenshot capture, test generation and Playwright code generation.
