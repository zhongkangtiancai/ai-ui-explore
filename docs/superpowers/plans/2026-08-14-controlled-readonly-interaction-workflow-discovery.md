# Sprint 9 受控只读交互与流程发现 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有受控探索任务中，安全执行白名单只读 UI 交互，保存脱敏步骤证据，并确定性生成观察到的流程图。

**Architecture:** 新建独立交互候选、策略及流程模型模块；Runner 通过仅能执行受限定位器的 Port 调用任务绑定浏览器会话。任务证据收集器投影步骤和流程图，API、Vue 和 `exploration-knowledge-package-v2` 只读取这些进程内脱敏 DTO。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、Playwright sync API、pytest、jsonschema、Vue 3、TypeScript、Vitest、Vue Test Utils、本地 Chromium fixture。

## Global Constraints

- 仅允许 `expand`、`collapse`、`switch_tab`、`open_menu`、`paginate`、`view_details`；其他交互默认拒绝。
- 禁止输入、提交、删除、审批、发布、支付、授权、上传、下载、确认型按钮、任意 JavaScript、坐标点击和访问控制绕过。
- 候选来自已脱敏投影，必须有唯一推荐定位器，并通过元素语义、风险词、URL/Origin 和预算检查。
- 每步仅保存安全 ID、类别、脱敏目标摘要、前后状态指纹、证据引用、结果和固定原因码；不得保存浏览器对象、输入值、Cookie、Token、DOM/HTML、网络正文或截图。
- 流程边只能来自已验证成功步骤；失败、跳过、暂停和未执行候选不得形成流程边。
- 保持进程内存态，不做数据库、Worker 或跨进程恢复；`inferences=[]`，不生成业务流程、权限或后端数据结论。
- 所有新增行为先写失败测试，再做最小实现；每项任务独立验证后精确白名单提交。

---

### Task 1: 只读交互模型、候选分类和默认拒绝策略

**Files:**

- Create: `backend/src/ai_ui_explorer/exploration/interactions.py`
- Modify: `backend/src/ai_ui_explorer/exploration/policy.py`
- Modify: `backend/src/ai_ui_explorer/exploration/__init__.py`
- Create: `backend/tests/exploration/test_interactions.py`
- Modify: `backend/tests/exploration/test_policy.py`

**Interfaces:**

- Consumes: `PageEvidence`、`ElementEvidence`、`LocatorCandidateEvidence` 与 `NavigationPolicy`。
- Produces: `ReadonlyInteractionKind`、`ReadonlyInteractionCandidate`、`InteractionDecision`、`extract_readonly_interaction_candidates(page)`、`ReadonlyInteractionGate.evaluate(candidate, policy)`。

- [ ] **Step 1: 写失败测试，锁定白名单、唯一定位器和风险暂停。**

    def test_extracts_unique_expander_and_tab_in_deterministic_order() -> None:
        candidates = extract_readonly_interaction_candidates(page_with_tab_and_expander())
        assert [(item.kind, item.element_key) for item in candidates] == [
            ("expand", "details-toggle"), ("switch_tab", "overview-tab")
        ]
        assert all(item.locator.uniqueness == "unique" for item in candidates)

    @pytest.mark.parametrize("name", ["删除", "提交订单", "Approve", "Download"])
    def test_gate_pauses_risky_or_unknown_candidate(name: str) -> None:
        decision = ReadonlyInteractionGate().evaluate(candidate_named(name), local_policy())
        assert not decision.allowed
        assert decision.reason_code in {"dangerous_semantics", "download_risk", "unknown_interaction"}

- [ ] **Step 2: 运行 RED。**

Run: `cd backend; $env:PYTHONPATH='src'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\exploration\\test_interactions.py tests\\exploration\\test_policy.py -k "interaction or readonly"`

Expected: FAIL，因为模型、提取器和门禁尚不存在。

- [ ] **Step 3: 最小实现纯模型与门禁。**

    ReadonlyInteractionKind = Literal[
        "expand", "collapse", "switch_tab", "open_menu", "paginate", "view_details",
    ]

    class ReadonlyInteractionCandidate(DeepFrozenModel):
        kind: ReadonlyInteractionKind
        element_key: str
        frame_path: str
        locator: LocatorCandidateEvidence
        target_summary: str
        target_url: str | None = None

    class ReadonlyInteractionGate:
        def evaluate(
            self, candidate: ReadonlyInteractionCandidate, navigation_policy: NavigationPolicy
        ) -> InteractionDecision: ...

从 `role`、`tag`、`aria-expanded`、`aria-controls`、`aria-selected`、`aria-haspopup`、链接 `href`、安全标签文本与唯一 `recommended` locator 分类。使用固定中英文风险词拒绝删除、提交、审批、发布、支付、授权、上传、下载；拒绝 form/submit、输入、文件控件、非唯一或非推荐定位器。具有 URL 的 `view_details`、`paginate` 必须调用 `NavigationPolicy.evaluate`。不改变既有 `ActionGate` 的 URL 导航行为。

- [ ] **Step 4: 运行 Green 与回归。**

Run: `cd backend; $env:PYTHONPATH='src'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\exploration\\test_interactions.py tests\\exploration\\test_policy.py tests\\exploration\\test_candidates.py; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m ruff check --no-cache src\\ai_ui_explorer\\exploration tests\\exploration`

Expected: PASS；普通链接、表单和危险动作仍遵守原策略。

- [ ] **Step 5: 提交。**

    git add backend/src/ai_ui_explorer/exploration/interactions.py backend/src/ai_ui_explorer/exploration/policy.py backend/src/ai_ui_explorer/exploration/__init__.py backend/tests/exploration/test_interactions.py backend/tests/exploration/test_policy.py
    git commit -m "feat: classify controlled readonly interactions"

### Task 2: 任务绑定的受限 Playwright 执行器和有界 Runner

**Files:**

- Modify: `backend/src/ai_ui_explorer/snapshot/browser.py`
- Modify: `backend/src/ai_ui_explorer/exploration/collector_adapter.py`
- Modify: `backend/src/ai_ui_explorer/exploration/runner.py`
- Modify: `backend/src/ai_ui_explorer/exploration/queue.py`
- Modify: `backend/src/ai_ui_explorer/task_management/service.py`
- Create: `backend/tests/exploration/test_readonly_executor.py`
- Modify: `backend/tests/exploration/test_runner.py`
- Modify: `backend/tests/exploration/test_login_browser.py`

**Interfaces:**

- Consumes: Task 1 候选/门禁、`PlaywrightBrowserSession`、`SessionSnapshotCollectorAdapter`、`ExplorationBudget`。
- Produces: `ReadonlyInteractionExecutorPort.execute(candidate) -> ReadonlyInteractionExecution`、`ExplorationRunResult.interaction_steps`、`ExplorationBudget.max_interaction_steps`、`max_interactions_per_page`。

- [ ] **Step 1: 写失败测试，定义执行边界和步骤预算。**

    def test_session_executor_clicks_only_a_unique_allowlisted_locator() -> None:
        execution = session_executor(local_fixture_session()).execute(unique_tab_candidate())
        assert execution.status == "executed"
        assert execution.current_url.endswith("/dashboard")

    def test_runner_stops_interaction_branch_when_budget_or_state_validation_fails() -> None:
        result = readonly_runner(max_interaction_steps=1).run(modules=[entry()])
        assert result.status == "partial"
        assert "interaction_budget_exhausted" in result.stop_reasons
        assert len([step for step in result.interaction_steps if step.status == "executed"]) == 1

- [ ] **Step 2: 运行 RED。**

Run: `cd backend; $env:PYTHONPATH='src'; $env:PLAYWRIGHT_BROWSERS_PATH='D:\\codexWS\\codx-ai-ui-explorer\\.playwright-browsers'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\exploration\\test_readonly_executor.py tests\\exploration\\test_runner.py -k "readonly or interaction"`

Expected: FAIL，因为会话没有受限交互端口，Runner 没有步骤预算和结果。

- [ ] **Step 3: 实现受限执行端口和编排。**

    class ReadonlyInteractionExecution(DeepFrozenModel):
        status: Literal["executed", "skipped", "paused", "failed"]
        reason_code: str
        safe_message: str
        url_before: str
        url_after: str | None = None

    class ReadonlyInteractionExecutorPort(Protocol):
        def execute(self, candidate: ReadonlyInteractionCandidate) -> ReadonlyInteractionExecution: ...

在 `PlaywrightBrowserSession` 新增 `execute_readonly_interaction`：只接收候选；只将唯一 `role`、`label`、`text`、`testid`、`id`、`name`、`aria`、`css`、`xpath` 映射为当前 frame 内 locator。点击前后检查 URL；不得使用任意 JS、`force=True`、坐标、键盘输入或下载调用。超时、frame 缺失、匹配数非 1、导航异常和下载事件返回固定失败/暂停码。由 `SessionSnapshotCollectorAdapter` 暴露同一任务绑定 executor，保留身份校验。

在 `ExplorationBudget` 新增有界 `max_interaction_steps`、`max_interactions_per_page`。Runner 对非重复快照提取、门禁并按 `(kind, element_key, locator.rank)` 排序；每次允许执行后重新采集，用既有状态去重记录前后状态。风险、不可验证、预算耗尽或执行失败停止该分支并记录固定 `stop_reason`。非 Session collector 继续仅导航，不伪造交互能力。

- [ ] **Step 4: 运行 Green 与探索回归。**

Run: `cd backend; $env:PYTHONPATH='src'; $env:PLAYWRIGHT_BROWSERS_PATH='D:\\codexWS\\codx-ai-ui-explorer\\.playwright-browsers'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\exploration\\test_readonly_executor.py tests\\exploration\\test_runner.py tests\\exploration\\test_queue.py tests\\exploration\\test_login_browser.py; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m mypy --config-file pyproject.toml --cache-dir ..\\.mypy-cache-sprint9-task2 src\\ai_ui_explorer\\exploration src\\ai_ui_explorer\\snapshot src\\ai_ui_explorer\\task_management`

Expected: PASS；预算、取消、重复状态和登录会话绑定均有效。

- [ ] **Step 5: 提交。**

    git add backend/src/ai_ui_explorer/snapshot/browser.py backend/src/ai_ui_explorer/exploration/collector_adapter.py backend/src/ai_ui_explorer/exploration/runner.py backend/src/ai_ui_explorer/exploration/queue.py backend/src/ai_ui_explorer/task_management/service.py backend/tests/exploration/test_readonly_executor.py backend/tests/exploration/test_runner.py backend/tests/exploration/test_login_browser.py
    git commit -m "feat: execute bounded readonly interactions"

### Task 3: 脱敏步骤证据、确定性流程图和任务详情契约

**Files:**

- Create: `backend/src/ai_ui_explorer/exploration/workflows.py`
- Modify: `backend/src/ai_ui_explorer/task_management/evidence.py`
- Modify: `backend/src/ai_ui_explorer/task_management/service.py`
- Modify: `backend/src/ai_ui_explorer/api/routes/exploration_tasks.py`
- Modify: `backend/tests/task_management/test_task_evidence.py`
- Modify: `backend/tests/task_management/test_service.py`
- Modify: `backend/tests/api/test_exploration_tasks.py`

**Interfaces:**

- Consumes: Task 2 执行结果、`SnapshotVisitResult`、`TaskEvidenceCollector`、`PageEvidence`。
- Produces: `InteractionStepView`、`WorkflowNodeView`、`WorkflowEdgeView`、`TaskWorkflowExport`、`ExplorationTaskService.workflow(task_id)`、`GET /exploration-tasks/{task_id}/workflow`。

- [ ] **Step 1: 写失败测试，锁定脱敏投影、证据闭包和归并。**

    def test_evidence_collector_projects_steps_without_runtime_or_input_values() -> None:
        workflow = collector.workflow(task_id="task-1", state="completed")
        assert workflow.steps[0].kind == "switch_tab"
        assert workflow.steps[0].before_state != workflow.steps[0].after_state
        assert "password" not in workflow.model_dump_json().lower()

    def test_workflow_graph_merges_same_verified_transition_deterministically() -> None:
        graph = build_workflow_graph([verified_step(), verified_step()])
        assert len(graph.edges) == 1
        assert graph.edges[0].observation_count == 2

- [ ] **Step 2: 运行 RED。**

Run: `cd backend; $env:PYTHONPATH='src'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\task_management\\test_task_evidence.py tests\\task_management\\test_service.py tests\\api\\test_exploration_tasks.py -k "workflow or interaction"`

Expected: FAIL，因为步骤 DTO、图构建器和 workflow 路由尚不存在。

- [ ] **Step 3: 实现受限投影与图构建器。**

    class InteractionStepView(DeepFrozenModel):
        step_id: str
        kind: ReadonlyInteractionKind
        target_summary: str
        before_state: str
        after_state: str | None = None
        status: Literal["executed", "skipped", "paused", "failed"]
        reason_code: str
        evidence_refs: list[EvidenceReference]

    class WorkflowEdgeView(DeepFrozenModel):
        edge_id: str
        source_state: str
        target_state: str
        kind: ReadonlyInteractionKind
        observation_count: int
        evidence_refs: list[EvidenceReference]

`TaskEvidenceCollector` 接收 Runner 步骤并立即投影；未成功步骤只保留固定原因和前态，绝不产生图边。 `build_workflow_graph(steps)` 只归并成功、具有前后状态与闭合证据的步骤，按 `(source_state, target_state, kind, target_summary)` 生成稳定 ID，排序节点/边并限制每边证据数。新增独立 `TaskWorkflowExport`，避免破坏 Sprint 7 的 `ExplorationEvidenceExport` 1.0 契约。API 仅返回终态任务的进程内 DTO，未知任务保持固定 404。

- [ ] **Step 4: 运行 Green 与 API 回归。**

Run: `cd backend; $env:PYTHONPATH='src'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\task_management\\test_task_evidence.py tests\\task_management\\test_service.py tests\\api\\test_exploration_tasks.py; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m ruff check --no-cache src\\ai_ui_explorer\\exploration src\\ai_ui_explorer\\task_management src\\ai_ui_explorer\\api tests\\task_management tests\\api`

Expected: PASS；既有页面明细和下载契约继续可用。

- [ ] **Step 5: 提交。**

    git add backend/src/ai_ui_explorer/exploration/workflows.py backend/src/ai_ui_explorer/task_management/evidence.py backend/src/ai_ui_explorer/task_management/service.py backend/src/ai_ui_explorer/api/routes/exploration_tasks.py backend/tests/task_management/test_task_evidence.py backend/tests/task_management/test_service.py backend/tests/api/test_exploration_tasks.py
    git commit -m "feat: project readonly workflow evidence"

### Task 4: 统一知识包、Schema 与 Vue 只读流程浏览

**Files:**

- Modify: `backend/src/ai_ui_explorer/exploration_knowledge/models.py`
- Modify: `backend/src/ai_ui_explorer/exploration_knowledge/builder.py`
- Modify: `backend/src/ai_ui_explorer/exploration_knowledge/schema/exploration-knowledge-package-v2.schema.json`
- Modify: `backend/tests/exploration_knowledge/test_builder.py`
- Modify: `backend/tests/exploration_knowledge/test_service.py`
- Modify: `frontend/src/api/explorationTasks.ts`
- Create: `frontend/src/components/ReadonlyWorkflowBrowser.vue`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/ReadonlyWorkflowBrowser.spec.ts`
- Modify: `frontend/tests/App.spec.ts`

**Interfaces:**

- Consumes: Task 3 `TaskWorkflowExport` 和终态 `TaskKnowledgeSource`。
- Produces: v2 的 `interaction_steps`、`workflow_nodes`、`workflow_edges`、相关 KnowledgeGap；`fetchExplorationTaskWorkflow(taskId)` 和只读流程面板。

- [ ] **Step 1: 写失败测试，锁定 v2 扩展与不可信文本渲染。**

    def test_builder_exports_verified_steps_and_workflow_without_business_inference() -> None:
        package = ExplorationKnowledgeBuilder().build([task_source_with_workflow()])
        assert package.interaction_steps[0].kind == "open_menu"
        assert package.workflow_edges[0].observation_count == 1
        assert package.inferences == []

    it('renders workflow text through interpolation and labels partial results as incomplete', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(workflowWithUntrustedSummary()))
      const wrapper = mount(ReadonlyWorkflowBrowser, { props: { taskId: 'task-1', taskState: 'partial' } })
      await flushPromises()
      expect(wrapper.html()).not.toContain('<img src=x')
      expect(wrapper.get('[data-test="workflow-partial"]').text()).toContain('不完整')
    })

- [ ] **Step 2: 运行 RED。**

Run: `cd backend; $env:PYTHONPATH='src'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\exploration_knowledge\\test_builder.py tests\\exploration_knowledge\\test_service.py -k "workflow or interaction"; cd ..\\frontend; pnpm test -- ReadonlyWorkflowBrowser App`

Expected: FAIL，因为 v2 模型、Builder 和 Vue 流程浏览器尚不支持这些字段。

- [ ] **Step 3: 最小扩展 v2 与只读界面。**

新增有界 `KnowledgeInteractionStep`、`KnowledgeWorkflowNode`、`KnowledgeWorkflowEdge`，使每项证据引用解析到包内 `evidence`，更新闭包校验与提交 Schema。Builder 只从 `TaskKnowledgeSource` 的受限 workflow 投影构建；未有验证步骤时保留 `actions_not_explored`、`workflows_not_observed`，存在 partial/暂停/失败时增加 `workflows_partially_observed`。保持 package ID、排序、字节预算和 `inferences=[]` 的确定性。

前端 API 只读取 workflow JSON。 `ReadonlyWorkflowBrowser` 用文本插值显示节点、边、动作类别、观察次数和固定限制；无执行按钮。组件置于 `ExplorationEvidenceBrowser` 后，加载、无数据、partial、错误使用固定安全消息。

- [ ] **Step 4: 运行 Green、Schema 和前端质量门。**

Run: `cd backend; $env:PYTHONPATH='src'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\exploration_knowledge tests\\api\\test_exploration_knowledge.py tests\\task_management; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m mypy --config-file pyproject.toml --cache-dir ..\\.mypy-cache-sprint9-task4 src\\ai_ui_explorer\\exploration_knowledge; cd ..\\frontend; pnpm test; pnpm lint; pnpm typecheck; pnpm format:check; pnpm build`

Expected: PASS；Schema 可校验、敏感 fixture 不进入下载内容，前端不生成控制能力。

- [ ] **Step 5: 提交。**

    git add backend/src/ai_ui_explorer/exploration_knowledge backend/tests/exploration_knowledge frontend/src/api/explorationTasks.ts frontend/src/components/ReadonlyWorkflowBrowser.vue frontend/src/App.vue frontend/tests/ReadonlyWorkflowBrowser.spec.ts frontend/tests/App.spec.ts
    git commit -m "feat: export readonly workflow knowledge"

### Task 5: 真实 Chromium 验收、文档更新与完整质量门

**Files:**

- Modify: `backend/tests/api/fixtures/permission_comparison_site.py`
- Modify: `backend/tests/api/test_exploration_tasks.py`
- Modify: `backend/tests/api/test_exploration_knowledge.py`
- Modify: `docs/00-project-context.md`
- Modify: `docs/02-architecture.md`
- Modify: `docs/03-knowledge-model.md`
- Modify: `docs/07-roadmap.md`
- Modify: `README.md`

**Interfaces:**

- Consumes: Tasks 1–4 的公开 Runner、workflow API、知识包和 Vue 契约。
- Produces: 本地虚构站点端到端证据，以及准确界定 Sprint 9 的项目文档。

- [ ] **Step 1: 写真实 Chromium 的失败验收。**

    def test_local_login_task_discovers_only_safe_tab_and_detail_workflow() -> None:
        app = production_app_for_local_login_fixture_with_readonly_interactions()
        with TestClient(app) as client:
            task_id = complete_local_login_task(client)
            workflow = client.get(f"/api/v1/exploration-tasks/{task_id}/workflow")
            package = client.post("/api/v1/exploration-knowledge-packages/export", json={"task_ids": [task_id]})
        assert workflow.status_code == 200
        assert {edge["kind"] for edge in workflow.json()["edges"]} <= {"switch_tab", "view_details"}
        assert package.json()["inferences"] == []
        assert "fixture-password-do-not-return" not in package.text

- [ ] **Step 2: 运行 RED 验收。**

Run: `cd backend; $env:PYTHONPATH='src'; $env:PLAYWRIGHT_BROWSERS_PATH='D:\\codexWS\\codx-ai-ui-explorer\\.playwright-browsers'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q tests\\api\\test_exploration_tasks.py tests\\api\\test_exploration_knowledge.py -k "readonly_workflow or local_login_task"`

Expected: FAIL，直到前述切片完成完整链路。

- [ ] **Step 3: 补齐 fixture 和文档。**

本地 fixture 增加唯一标签、详情抽屉和明确危险提交按钮；验收必须证明前两者产生边、后者仅暂停/跳过而不点击。更新项目上下文、架构、知识模型、路线图和 README：Sprint 9 仅覆盖六类白名单交互，流程图是观察结果，风险/不确定时暂停，无业务权限结论、无敏感持久化，真实外站/SSO/MFA 未验证。

- [ ] **Step 4: 运行完整质量门。**

Run: `cd backend; $env:PYTHONPATH='src'; $env:PLAYWRIGHT_BROWSERS_PATH='D:\\codexWS\\codx-ai-ui-explorer\\.playwright-browsers'; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m pytest -q --basetemp ..\\.pytest-tmp-sprint9-final tests\\knowledge tests\\exploration_knowledge tests\\task_management tests\\permission_comparison tests\\api tests\\exploration tests\\snapshot\\test_browser.py; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m ruff check --no-cache .; & 'D:\\codexWS\\codx-ai-ui-explorer\\.venv\\Scripts\\python.exe' -m mypy --config-file pyproject.toml --cache-dir ..\\.mypy-cache-sprint9-final src\\ai_ui_explorer; cd ..\\frontend; pnpm test; pnpm lint; pnpm typecheck; pnpm format:check; pnpm build; cd ..; git diff --check`

Expected: 全部退出码为 0；仅在 pytest Python 进程退出后接受 Chromium 结果。

- [ ] **Step 5: 提交。**

    git add backend/tests/api/fixtures/permission_comparison_site.py backend/tests/api/test_exploration_tasks.py backend/tests/api/test_exploration_knowledge.py docs/00-project-context.md docs/02-architecture.md docs/03-knowledge-model.md docs/07-roadmap.md README.md docs/superpowers/plans/2026-08-14-controlled-readonly-interaction-workflow-discovery.md
    git commit -m "test: verify readonly workflow discovery"

## Plan Self-Review

- 规格的白名单和默认拒绝由 Task 1 实现，Task 2 在浏览器边界再次强制。
- 预算、前后状态和分支暂停由 Task 2 实现；Task 3 仅投影已验证结果。
- 步骤证据、流程归并、partial 语义和固定错误面由 Task 3 实现。
- v2 知识包、证据闭包与无推断由 Task 4 验证；Task 5 提供 Chromium 集成证据及文档同步。
- 本计划不含任意点击、表单输入、提交、下载、敏感持久化、跨进程恢复、真实外站、LLM 推断或测试代码生成。

