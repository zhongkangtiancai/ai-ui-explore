# Sprint 8 统一探索知识包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前进程内已完成的任务证据和权限比较结果按需构建为可下载、脱敏、确定性且 Schema 校验的 `exploration-knowledge-package-v2`。

**Architecture:** 新建独立 `exploration_knowledge` 模块，绝不修改 Sprint 2 的离线 `knowledge-package-v1`。任务服务和比较服务只暴露终态的受限来源 DTO；导出服务将这些 DTO 交给纯 Builder，再由 FastAPI 和 Vue 提供安全的来源选择与 JSON 下载。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、jsonschema、pytest、Playwright、本地 Chromium、Vue 3、TypeScript、Vitest、Vue Test Utils。

## Global Constraints

- 只消费 `TaskSummary`、`PageEvidence`、`PermissionComparisonResult` 和 `VisibilityDifference`；禁止读取 Snapshot、DOM、HTML、网络正文、浏览器、Cookie、Token、输入值或登录态。
- 不修改 `knowledge-package-v1`、其离线 CLI、Schema 或 Builder；新包 Schema 固定版本 `2.0`。
- `inferences` 始终为空；不产生 AI 推断、业务权限、后端数据范围或角色结论。
- `partial`、认证未验证、采集失败、不可匹配和不可比较必须转为 Observation/KnowledgeGap 或 inconclusive 差异，绝不升级为权限结论。
- 所有 ID、排序和 JSON 序列化必须由受限输入确定；不得使用当前时间、随机 UUID、对象地址或浏览器状态。
- 导出只在当前进程响应中生成，不写文件、不持久化；最多 5 个来源、500 页、20,000 元素、20,000 条差异、50,000 条证据和 10 MiB UTF-8 JSON；超过任一预算时固定拒绝，不静默截断。
- API 请求 `extra="forbid"`，错误面固定且不回显输入、异常、敏感字段或浏览器对象。
- 文档使用简体中文；代码标识符和 API 字段使用英文；每项行为遵循先失败测试、最小实现、专项复核和提交。

---

### Task 1: 统一知识包模型、确定性 Builder 与提交 Schema

**Files:**
- Create: `backend/src/ai_ui_explorer/exploration_knowledge/models.py`
- Create: `backend/src/ai_ui_explorer/exploration_knowledge/builder.py`
- Create: `backend/src/ai_ui_explorer/exploration_knowledge/__init__.py`
- Create: `backend/src/ai_ui_explorer/exploration_knowledge/schema/exploration-knowledge-package-v2.schema.json`
- Create: `backend/tests/exploration_knowledge/test_builder.py`
- Create: `backend/tests/exploration_knowledge/test_models.py`

**Interfaces:**
- Consumes: `ExplorationKnowledgeSource`, `TaskKnowledgeSource`, `ComparisonKnowledgeSource` defined in this task and existing `PageEvidence`, `EvidenceReference`, `PermissionComparisonResult`.
- Produces: `ExplorationKnowledgePackageV2` and `ExplorationKnowledgeBuilder.build(sources: list[ExplorationKnowledgeSource]) -> ExplorationKnowledgePackageV2`.

- [x] **Step 1: Write the failing model and Builder tests**

```python
def test_builder_combines_task_and_comparison_without_merging_same_page_keys() -> None:
    package = ExplorationKnowledgeBuilder().build(
        [completed_task_source("task-1"), completed_comparison_source("comparison-1")]
    )

    assert package.schema_version == "2.0"
    assert {source.source_id for source in package.sources} == {"task-1", "comparison-1"}
    assert len({page.page_id for page in package.pages}) == len(package.pages)
    assert package.inferences == []
    assert any(gap.code == "evidence_process_local" for gap in package.knowledge_gaps)


def test_builder_is_deterministic_and_marks_incomplete_comparison_inconclusive() -> None:
    sources = [partial_comparison_source("comparison-2"), completed_task_source("task-2")]
    first = ExplorationKnowledgeBuilder().build(sources).model_dump_json()
    second = ExplorationKnowledgeBuilder().build(list(reversed(sources))).model_dump_json()

    assert first == second
    assert all(item.reliability == "inconclusive" for item in package.visibility_differences)
```

- [x] **Step 2: Run the tests to verify RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q tests\exploration_knowledge\test_models.py tests\exploration_knowledge\test_builder.py
```

Expected: FAIL because `exploration_knowledge` and its v2 models do not exist.

- [x] **Step 3: Implement bounded v2 models and the pure Builder**

```python
class TaskKnowledgeSource(DeepFrozenModel):
    source_id: str = Field(pattern=r"^task-[0-9]{1,20}$")
    state: ExplorationTaskState
    pages: list[PageEvidence] = Field(max_length=100)
    reason_codes: list[str] = Field(max_length=20)


class ComparisonKnowledgeSource(DeepFrozenModel):
    source_id: str = Field(pattern=r"^comparison-[0-9]{1,20}$")
    result: PermissionComparisonResult


ExplorationKnowledgeSource = TaskKnowledgeSource | ComparisonKnowledgeSource


class ExplorationKnowledgeBuilder:
    def build(
        self,
        sources: list[ExplorationKnowledgeSource],
    ) -> ExplorationKnowledgePackageV2:
        ordered_sources = _sorted_unique_sources(sources)
        return _package_from_sources(ordered_sources)
```

Define separate v2 source, identity, page, element, locator, fact, observation, gap, difference and statistics models in `models.py`. Reuse only safe field values and existing `EvidenceReference`; derive v2 IDs with a stable SHA-256 prefix over `(source_id, identity_id, page_key, element_key, ordinal)`. Sort sources by `source_id`, comparison identities by `identity_id`, pages by source/identity/page key/original ordinal, elements by stable key/original ordinal, and evidence by `evidence_id`.

Emit Facts only for directly observed fields and require every fact/difference/locator to resolve to package evidence. Add fixed `actions_not_explored`, `workflows_not_observed`, and `evidence_process_local` gaps. Convert incomplete comparison states to `inconclusive`; preserve existing `reason_codes` without inventing authorization wording. Set `inferences=[]` in a validator and reject any non-empty input. Add explicit non-negative count and max-item limits; serialize once with `ensure_ascii=False, separators=(",", ":")` and reject if the byte budget is exceeded.

Generate the committed v2 schema from `ExplorationKnowledgePackageV2.to_schema()` and test exact model/schema agreement.

- [x] **Step 4: Run Green plus knowledge regressions**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q tests\exploration_knowledge tests\knowledge tests\permission_comparison
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m ruff check --no-cache src\ai_ui_explorer\exploration_knowledge tests\exploration_knowledge
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m mypy --config-file pyproject.toml --cache-dir ..\.mypy-cache-sprint8-task1 src\ai_ui_explorer\exploration_knowledge
```

Expected: all commands exit 0; existing v1 knowledge tests stay unchanged.

- [x] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/exploration_knowledge backend/tests/exploration_knowledge
git commit -m "feat: build unified exploration knowledge package"
```

---

### Task 2: 安全来源目录与进程内导出服务

**Files:**
- Modify: `backend/src/ai_ui_explorer/task_management/registry.py`
- Modify: `backend/src/ai_ui_explorer/task_management/service.py`
- Modify: `backend/src/ai_ui_explorer/permission_comparison/service.py`
- Create: `backend/src/ai_ui_explorer/exploration_knowledge/service.py`
- Create: `backend/tests/exploration_knowledge/test_service.py`
- Modify: `backend/tests/task_management/test_service.py`
- Modify: `backend/tests/permission_comparison/test_service.py`

**Interfaces:**
- Consumes: Task 1 `ExplorationKnowledgeBuilder`, `TaskKnowledgeSource`, `ComparisonKnowledgeSource`.
- Produces: `ExplorationSourceView`, `ExplorationKnowledgeExportService.sources()` and `.export(request)`.

- [x] **Step 1: Write the failing source catalog and boundary tests**

```python
def test_export_service_lists_only_safe_terminal_sources() -> None:
    catalog = export_service_with_completed_task_partial_comparison_and_running_task().sources()

    assert [item.source_id for item in catalog] == ["comparison-1", "task-1"]
    assert all(item.state in {"completed", "partial", "failed", "cancelled"} for item in catalog)
    assert "authentication_plan" not in catalog[0].model_dump_json()


def test_export_service_rejects_unknown_and_non_terminal_sources_without_runtime_leak() -> None:
    with pytest.raises(ExplorationKnowledgeExportError, match="source unavailable"):
        service.export(ExplorationKnowledgeExportRequest(task_ids=["task-999"]))
    with pytest.raises(ExplorationKnowledgeExportError, match="source unavailable"):
        service.export(ExplorationKnowledgeExportRequest(task_ids=["task-2"]))
```

- [x] **Step 2: Run the tests to verify RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q tests\exploration_knowledge\test_service.py -k "catalog or source"
```

Expected: FAIL because neither service exposes safe source reading nor an export coordinator.

- [x] **Step 3: Implement terminal-only source adapters**

```python
class ExplorationSourceView(DeepFrozenModel):
    source_id: str
    source_kind: Literal["task", "comparison"]
    state: Literal["completed", "partial", "failed", "cancelled"]
    page_count: int = Field(ge=0)
    identity_count: int = Field(ge=0)


class ExplorationKnowledgeExportRequest(DeepFrozenModel):
    task_ids: list[str] = Field(default_factory=list, max_length=5)
    comparison_ids: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def require_at_least_one_source(self) -> Self:
        if not self.task_ids and not self.comparison_ids:
            raise ValueError("knowledge export requires one source")
        if len(set(self.task_ids + self.comparison_ids)) > 5:
            raise ValueError("knowledge export source limit exceeded")
        return self


class ExplorationKnowledgeExportService:
    def sources(self) -> list[ExplorationSourceView]:
        return _sort_source_views(self._terminal_source_views())
    def export(
        self,
        request: ExplorationKnowledgeExportRequest,
    ) -> ExplorationKnowledgePackageV2:
        return self._builder.build(self._resolve_sources(request))
```

Add registry/service list methods that return copied public `TaskSummary` values in safe ID order. Add `ExplorationTaskService.knowledge_source(task_id)` that copies only terminal task summary, collector `PageEvidence`, and safe reason codes; it returns `None` for unknown/non-terminal items and never returns `ManagedTask`, execution, context, runtime or collector. Add equivalent comparison list and source methods that copy `PermissionComparisonResult` only after its terminal result exists.

The coordinator deduplicates requested IDs, accepts all terminal states to preserve gaps, calls the pure Builder, and maps every unavailable source to one fixed `ExplorationKnowledgeExportError("source unavailable")`. It does not cache or store the completed package.

- [x] **Step 4: Run Green plus task/comparison regression**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q tests\exploration_knowledge\test_service.py tests\task_management\test_service.py tests\permission_comparison\test_service.py
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m ruff check --no-cache src\ai_ui_explorer\exploration_knowledge src\ai_ui_explorer\task_management src\ai_ui_explorer\permission_comparison tests\exploration_knowledge
```

Expected: all tests pass; terminal source lists and exports never expose runtime values.

- [x] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/task_management/registry.py backend/src/ai_ui_explorer/task_management/service.py backend/src/ai_ui_explorer/permission_comparison/service.py backend/src/ai_ui_explorer/exploration_knowledge/service.py backend/tests/exploration_knowledge backend/tests/task_management/test_service.py backend/tests/permission_comparison/test_service.py
git commit -m "feat: export terminal exploration knowledge sources"
```

---

### Task 3: 严格 API 下载契约与应用装配

**Files:**
- Create: `backend/src/ai_ui_explorer/api/routes/exploration_knowledge.py`
- Modify: `backend/src/ai_ui_explorer/main.py`
- Create: `backend/tests/api/test_exploration_knowledge.py`
- Modify: `backend/tests/api/test_exploration_tasks.py`
- Modify: `backend/tests/api/test_permission_comparisons.py`

**Interfaces:**
- Consumes: Task 2 `ExplorationKnowledgeExportService` and request/view DTOs.
- Produces: `GET /api/v1/exploration-knowledge-packages/sources` and `POST /api/v1/exploration-knowledge-packages/export`.

- [x] **Step 1: Write the failing HTTP contract tests**

```python
def test_export_route_returns_schema_valid_task_and_comparison_package(client: TestClient) -> None:
    payload = {"task_ids": ["task-1"], "comparison_ids": ["comparison-1"]}
    response = client.post("/api/v1/exploration-knowledge-packages/export", json=payload)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="exploration-knowledge-package.json"'
    )
    body = response.json()
    assert body["schema_version"] == "2.0"
    assert {item["source_id"] for item in body["sources"]} == {"task-1", "comparison-1"}
    assert "fixture-password-do-not-return" not in response.text


@pytest.mark.parametrize("payload", [{}, {"task_ids": ["task-999"]}, {"task_ids": ["task-1"], "token": "x"}])
def test_export_route_returns_fixed_safe_errors(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post("/api/v1/exploration-knowledge-packages/export", json=payload)
    assert response.status_code in {404, 422}
    assert "token" not in response.text
```

- [x] **Step 2: Run the tests to verify RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q tests\api\test_exploration_knowledge.py
```

Expected: FAIL because the router and app-state export service are missing.

- [x] **Step 3: Implement allowlisted routes and fixed error mapping**

```python
router = APIRouter(
    prefix="/exploration-knowledge-packages",
    tags=["exploration-knowledge-packages"],
)


@router.get("/sources", response_model=list[ExplorationSourceView])
def list_sources(
    service: Annotated[ExplorationKnowledgeExportService, Depends(get_export_service)],
) -> list[ExplorationSourceView]:
    return service.sources()


@router.post("/export")
def export_knowledge(
    payload: ExplorationKnowledgeExportRequest,
    service: Annotated[ExplorationKnowledgeExportService, Depends(get_export_service)],
) -> Response:
    package = service.export(payload)
    return _knowledge_download_response(package)
```

Create one `ExplorationKnowledgeExportService` in `create_app`, using the same process-local task and comparison service instances already attached to `app.state`; attach it as `app.state.exploration_knowledge_export_service`. On success, serialize with fixed separators, validate against `ExplorationKnowledgePackageV2.to_schema()` via `Draft202012Validator`, and return an attachment named exactly `exploration-knowledge-package.json`.

Map invalid body to the existing fixed `invalid_request` handler, unavailable source to a fixed 404 `source_not_found`, and package budget/Schema construction failures to fixed 409 `knowledge_export_unavailable`. Do not log exception text or source payload. Add the router without changing existing task/comparison endpoint behavior.

- [x] **Step 4: Run Green and API regression**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
$env:PLAYWRIGHT_BROWSERS_PATH='D:\codexWS\codx-ai-ui-explorer\.playwright-browsers'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q tests\api\test_exploration_knowledge.py tests\api\test_exploration_tasks.py tests\api\test_permission_comparisons.py
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m mypy --config-file pyproject.toml --cache-dir ..\.mypy-cache-sprint8-task3 src\ai_ui_explorer
```

Expected: all tests pass; route errors never echo unknown JSON keys.

- [x] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/api/routes/exploration_knowledge.py backend/src/ai_ui_explorer/main.py backend/tests/api/test_exploration_knowledge.py backend/tests/api/test_exploration_tasks.py backend/tests/api/test_permission_comparisons.py
git commit -m "feat: download unified exploration knowledge"
```

---

### Task 4: Vue 来源选择与安全下载

**Files:**
- Create: `frontend/src/api/explorationKnowledge.ts`
- Create: `frontend/src/components/ExplorationKnowledgeExport.vue`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/ExplorationKnowledgeExport.spec.ts`
- Modify: `frontend/tests/App.spec.ts`

**Interfaces:**
- Consumes: Task 3 source catalog and export HTTP routes.
- Produces: a read-only source selector and `downloadExplorationKnowledge(request)` client method.

- [x] **Step 1: Write the failing component and client tests**

```ts
it('selects terminal task and comparison sources and requests a JSON download', async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse([
    { source_id: 'task-1', source_kind: 'task', state: 'completed', page_count: 1, identity_count: 0 },
    { source_id: 'comparison-1', source_kind: 'comparison', state: 'partial', page_count: 2, identity_count: 2 },
  ]))

  const wrapper = mount(ExplorationKnowledgeExport)
  await flushPromises()
  await wrapper.get('[data-test="source-task-1"]').setValue(true)
  await wrapper.get('[data-test="source-comparison-1"]').setValue(true)
  await wrapper.get('[data-test="download-knowledge"]').trigger('click')

  expect(fetchMock).toHaveBeenLastCalledWith(
    expect.stringContaining('/exploration-knowledge-packages/export'),
    expect.objectContaining({ method: 'POST' }),
  )
})
```

- [x] **Step 2: Run the tests to verify RED**

Run:

```powershell
cd frontend
pnpm test -- ExplorationKnowledgeExport App
```

Expected: FAIL because the client module and selector component do not exist.

- [x] **Step 3: Implement the safe selector and download client**

```ts
export interface ExplorationSourceView {
  source_id: string
  source_kind: 'task' | 'comparison'
  state: 'completed' | 'partial' | 'failed' | 'cancelled'
  page_count: number
  identity_count: number
}

export async function downloadExplorationKnowledge(
  request: { task_ids: string[]; comparison_ids: string[] },
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/exploration-knowledge-packages/export`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(request),
  })
  if (!response.ok) throw new ExplorationKnowledgeApiError()
  triggerJsonDownload(await response.blob(), 'exploration-knowledge-package.json')
}
```

`ExplorationKnowledgeExport.vue` loads `/sources` on mount, guards that the response is an array, exposes only terminal source labels/counts/states, and disables download until at least one source is selected. The component uses text interpolation only, displays the fixed process-local/partial limitation, and on any fetch/download/JSON-shape error emits one generic error event without rendering response content.

In `App.vue`, render this independent read-only panel below task/comparison details. Do not couple it to polling, login confirmation, cancellation, Browser state or credential forms. Keep existing task/comparison downloads unchanged.

- [x] **Step 4: Run Green and frontend quality gate**

Run:

```powershell
cd frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm format:check
pnpm build
```

Expected: all commands exit 0; tests prove untrusted source labels are rendered as text, not HTML.

- [x] **Step 5: Commit**

```powershell
git add frontend/src/api/explorationKnowledge.ts frontend/src/components/ExplorationKnowledgeExport.vue frontend/src/App.vue frontend/tests/ExplorationKnowledgeExport.spec.ts frontend/tests/App.spec.ts
git commit -m "feat: export unified exploration knowledge from ui"
```

---

### Task 5: 真实 Chromium 组合验收、文档与最终质量门

**Files:**
- Modify: `backend/tests/api/test_exploration_knowledge.py`
- Modify: `docs/00-project-context.md`
- Modify: `docs/02-architecture.md`
- Modify: `docs/03-knowledge-model.md`
- Modify: `docs/07-roadmap.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–4 public Builder, API and Vue contracts.
- Produces: verified local fixture evidence and precise documentation of Sprint 8 boundaries.

- [x] **Step 1: Write the failing local Chromium end-to-end test**

```python
def test_local_task_and_comparison_export_one_redacted_knowledge_package() -> None:
    app = production_app_for_local_login_and_roles_fixture()
    with TestClient(app) as client:
        task_id = complete_local_login_task(client)
        comparison_id = complete_local_role_comparison(client)
        response = client.post(
            "/api/v1/exploration-knowledge-packages/export",
            json={"task_ids": [task_id], "comparison_ids": [comparison_id]},
        )

    assert response.status_code == 200
    exported = response.json()
    assert exported["pages"]
    assert exported["visibility_differences"]
    assert exported["inferences"] == []
    assert "fixture-password-do-not-return" not in response.text
```

- [x] **Step 2: Run the test to verify RED**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
$env:PLAYWRIGHT_BROWSERS_PATH='D:\codexWS\codx-ai-ui-explorer\.playwright-browsers'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q tests\api\test_exploration_knowledge.py -k "local_task_and_comparison"
```

Expected: FAIL before Tasks 1–4 expose a unified package download.

- [x] **Step 3: Add precise documentation**

Document all of the following without claiming more:

```text
Sprint 8 的知识包只来自当前进程、已经脱敏的任务与比较投影。
它包含直接观测事实、可见性差异、可靠性和知识缺口；不产生 AI 推断、业务权限或后端数据范围结论。
原 Snapshot 不持久化，Evidence 的 JSON Pointer 只能辅助当前进程内人工核查。
超过包预算会拒绝导出，不会静默截断；服务重启后来源与包都不可恢复。
```

- [x] **Step 4: Run the complete quality gate**

Run:

```powershell
cd backend
$env:PYTHONPATH='src'
$env:PLAYWRIGHT_BROWSERS_PATH='D:\codexWS\codx-ai-ui-explorer\.playwright-browsers'
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m pytest -q --basetemp ..\.pytest-tmp-sprint8-final tests\knowledge tests\exploration_knowledge tests\task_management tests\permission_comparison tests\api tests\exploration tests\snapshot\test_browser.py
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m ruff check --no-cache .
& 'D:\codexWS\codx-ai-ui-explorer\.venv\Scripts\python.exe' -m mypy --config-file pyproject.toml --cache-dir ..\.mypy-cache-sprint8-final src\ai_ui_explorer
cd ..\frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm format:check
pnpm build
cd ..
git diff --check
```

Expected: every command exits 0; accept Chromium progress only after the pytest Python process exits.

- [x] **Step 5: Commit**

```powershell
git add backend/tests/api/test_exploration_knowledge.py docs/00-project-context.md docs/02-architecture.md docs/03-knowledge-model.md docs/07-roadmap.md README.md docs/superpowers/plans/2026-08-14-unified-exploration-knowledge-package.md
git commit -m "test: verify unified exploration knowledge package"
```

## Plan Self-Review

- Task 1 covers v2-only models, deterministic entity construction, schema, evidence closure, explicit gaps, fixed empty inferences and budget refusal.
- Task 2 supplies the missing multi-source selection capability through terminal-only safe DTOs, without exposing registry handles or runtime state.
- Task 3 exposes exactly one source catalog and one generated-download route with a strict body and fixed failures.
- Task 4 gives users a multiple-source selector without adding browser control or untrusted HTML rendering.
- Task 5 validates local Chromium task-plus-comparison integration and keeps product, architecture, knowledge-model and roadmap documentation aligned.
- The plan deliberately excludes raw artifacts, persistence, auto-retry, action execution, flow inference, LLM inference, test generation and cross-process recovery.
