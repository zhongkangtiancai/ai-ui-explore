# Sprint 10：V1 安全任务持久化实施计划

> **给实施者：** 执行本计划时必须使用 `superpowers:executing-plans`，并严格按任务顺序、先失败测试后最小实现推进。

**目标：** 使用 PostgreSQL 持久化已脱敏的探索任务、证据、只读流程、权限比较和知识来源索引；服务重启后可读取终态结果，任何未完成的浏览器任务均安全终止为不可恢复状态，且绝不写入或恢复登录态。

**架构：** 在线任务继续由现有进程内注册表和线程执行。新增同步 SQLAlchemy Repository 层，只接收现有 Pydantic/Schema 已验证的白名单 DTO；任务/比较进入终态时在一个数据库事务中写入索引与 JSONB 投影。应用创建时运行恢复协调器，将非终态记录原子标记为 `failed / interrupted / process_restarted`。服务读取先命中内存运行时，未命中时再读取仅含终态安全投影的 Repository。

**技术栈：** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、psycopg 3、Alembic、PostgreSQL、pytest、Vue 3、TypeScript、Vitest、Playwright。

**实施记录（2026-08-21）：** PostgreSQL-only 配置、迁移、白名单 DTO/Repository、任务与比较终态投影及回读、启动中断恢复、统一知识包持久化来源和 Vue 安全终态展示均已在单位、服务、API 或前端测试中覆盖。集成测试要求同时设置 `AI_UI_EXPLORER_TEST_DATABASE_URL` 与 `AI_UI_EXPLORER_RUN_DATABASE_INTEGRATION_TESTS=1`，否则安全跳过。已在隔离 PostgreSQL 18.6 上实际通过迁移、终态回读、任务/比较重启恢复和本地虚构登录站点的真实 Chromium 服务重建回读验收；测试仅使用脱敏投影，重建读取不创建浏览器、Runner 或登录态。

**前置约束：**

- 只支持 PostgreSQL；`AI_UI_EXPLORER_DATABASE_URL` 缺失、格式不合法或数据库不可连接时应用启动失败，不回退内存伪持久化。
- 永不落库 Cookie、Token、Storage State、密码、输入值、浏览器/线程/Collector 对象、原始 DOM/HTML、Snapshot、网络正文或截图。
- 永不自动删除数据；本 Sprint 不实现保留策略、人工删除 API、Worker、Redis、跨进程续跑或登录态加密复用。
- JSONB 只保存版本受限的 DTO；未知未来版本、额外敏感字段或不可序列化运行时对象必须在写入前拒绝，读取时固定拒绝且不回显数据库异常。
- 集成测试通过 `AI_UI_EXPLORER_TEST_DATABASE_URL` 指向隔离 PostgreSQL。未配置该变量的开发机只运行单位测试；发布门禁必须在真实 PostgreSQL 上运行集成与迁移测试。

---

## 任务 1：建立 PostgreSQL 配置、会话与 Alembic 迁移基础设施

**文件：**

- 修改：`backend/pyproject.toml`
- 修改：`backend/requirements.lock`
- 修改：`backend/src/ai_ui_explorer/core/config.py`
- 新增：`backend/src/ai_ui_explorer/persistence/__init__.py`
- 新增：`backend/src/ai_ui_explorer/persistence/database.py`
- 新增：`backend/alembic.ini`
- 新增：`backend/alembic/env.py`
- 新增：`backend/alembic/script.py.mako`
- 新增：`backend/alembic/versions/20260818_01_safe_task_persistence.py`
- 新增：`backend/tests/persistence/test_database.py`
- 新增：`backend/tests/persistence/test_migrations.py`

**步骤：**

1. 先写失败测试：验证 `Settings` 缺少 `database_url` 时失败；非 PostgreSQL URL 被拒绝；启动用的连接工厂无法连接时抛出固定的安全配置异常；测试数据库 URL 只由 `AI_UI_EXPLORER_TEST_DATABASE_URL` 提供。
2. 先写失败迁移测试：在空 PostgreSQL 库运行 `alembic upgrade head` 后存在预期版本和五张表；重复升级不改变版本；测试不能把 SQLite URL 作为迁移目标。
3. 在 `pyproject.toml` 增加锁定版本的 `SQLAlchemy`、二进制 PostgreSQL 驱动 `psycopg` 和 Alembic；以项目现有锁文件工具更新 `requirements.lock`，不得手写未验证的传递依赖版本。
4. 在 `Settings` 增加必填的 `database_url: PostgresDsn`（环境变量名保持 `AI_UI_EXPLORER_DATABASE_URL`），并定义不包含 URL、用户名或异常原文的固定错误类型。
5. 实现 `persistence.database`：创建 Engine、sessionmaker、`session_scope()` 事务上下文和 `verify_database_connection()`；连接与回滚异常统一转换为固定安全错误。禁止打印连接 URL。
6. 建立 Alembic 环境，使 `DATABASE_URL` 从同一 Settings 读取，并让迁移在 URL 不是 PostgreSQL 时失败。
7. 运行：`python -m pytest tests/persistence/test_database.py tests/persistence/test_migrations.py -q`（配置测试）；在提供隔离 PostgreSQL URL 后再次运行完整迁移测试。
8. 提交：`chore: add PostgreSQL persistence foundation`。

## 任务 2：定义允许持久化的 DTO、ORM 表和安全 Repository 契约

**文件：**

- 新增：`backend/src/ai_ui_explorer/persistence/models.py`
- 新增：`backend/src/ai_ui_explorer/persistence/dtos.py`
- 新增：`backend/src/ai_ui_explorer/persistence/repositories.py`
- 修改：`backend/alembic/versions/20260818_01_safe_task_persistence.py`
- 新增：`backend/tests/persistence/test_repositories.py`
- 修改：`backend/tests/task_management/test_task_evidence.py`
- 修改：`backend/tests/permission_comparison/test_permission_comparison_service.py`

**步骤：**

1. 先写失败测试：只接受 Schema/Pydantic 验证过的 `TaskSummary`、`ExplorationEvidenceExport`、`TaskWorkflowExport`、`PermissionComparisonView`、`PermissionComparisonResult`、`TaskKnowledgeSource` 和 `ComparisonKnowledgeSource` 的 JSON 模式；带有 `browser`、`cookie`、`token`、`storage_state`、`password`、`input_value`、`html`、`snapshot`、`network_body` 或 `screenshot` 键的 payload 被拒绝。
2. 先写失败测试：不可 JSON 序列化对象、未知未来 `schema_version`、缺少终态结果的写入均抛出固定 Repository 错误；错误文本不包含 payload、SQL 或连接信息。
3. 在 ORM 模型和首个迁移中创建：`exploration_tasks`、`task_evidence_exports`、`task_workflows`、`permission_comparisons`、`exploration_knowledge_sources`。为公共 ID、状态、更新时间和来源种类建立索引；JSONB 列仅对应白名单投影，外键由任务/比较公共 ID 约束。
4. 在 `dtos.py` 将模型序列化为 `model_dump(mode="json")` 后重新用目标 Pydantic 模型验证，再做递归敏感键和 JSON 深度/字节预算检查。读取同样进行版本和模型验证，禁止“尽量兼容”。
5. 实现 Repository 的显式操作：创建/更新非终态任务索引、原子写入任务终态投影、创建/更新比较索引、原子写入比较终态投影、读取任务/比较终态投影、列出知识来源、扫描并中断非终态记录。Repository 不接受浏览器对象或执行命令原始内容。
6. 每次终态写入用同一 session 事务更新索引、证据、workflow 和知识来源；比较终态写入同时更新结果和来源。事务失败不留下部分终态投影。
7. 运行：`python -m pytest tests/persistence/test_repositories.py tests/task_management/test_task_evidence.py tests/permission_comparison/test_permission_comparison_service.py -q`。
8. 提交：`feat: persist validated terminal exploration projections`。

## 任务 3：接入探索任务终态持久化、持久化回读与启动中断恢复

**文件：**

- 修改：`backend/src/ai_ui_explorer/task_management/models.py`
- 修改：`backend/src/ai_ui_explorer/task_management/service.py`
- 新增：`backend/src/ai_ui_explorer/task_management/persistence.py`
- 修改：`backend/src/ai_ui_explorer/task_management/registry.py`
- 修改：`backend/src/ai_ui_explorer/main.py`
- 修改：`backend/tests/task_management/test_service.py`
- 新增：`backend/tests/task_management/test_persistent_task_service.py`
- 修改：`backend/tests/api/test_exploration_tasks.py`

**步骤：**

1. 先写失败测试：任务运行期间仍优先返回内存视图；服务重建后完成、partial、failed、cancelled 任务的摘要、事件、结果、页面、单页、证据导出和 workflow 都从 PostgreSQL 返回相同的安全响应。
2. 先写失败测试：`paused_for_human` 和 `collecting` 记录在应用初始化时仅变为 `state=failed`、`phase=interrupted`、原因码 `process_restarted`，追加最小审计事件；初始化不调用 RuntimeFactory、CollectorFactory 或 Playwright。
3. 扩展公共安全模型的 allowlist：允许持久化回读的 `interrupted` 阶段、`process_restarted` 原因码和最小恢复事件类型；仍不向客户端暴露登录检查点文本或运行时字段。
4. 实现 `PersistentTaskProjectionStore`，将 `TaskEvidenceCollector` 的终态 export/workflow/pages 和 `TaskSummary` 投影为 Repository DTO。它只在任务处于终态且证据投影完成后写入。
5. 为 `ExplorationTaskService` 注入可选持久化端口：创建时写最小非终态索引，终态通知中先安全投影并事务持久化，再执行现有回调；持久化失败将任务保守转为固定失败并不泄露内部错误。
6. 修改 `get`、`list_summaries`、`events`、`result`、`pages`、`page_detail`、`export`、`workflow`、`knowledge_source`：内存没有对应任务时仅查询终态持久化投影；恢复后 `confirm_login`、`cancel` 一律返回既有安全拒绝。
7. 在 `create_app()` 构建数据库、执行连接验证与 `interrupt_nonterminal()`，再构建并注入服务；数据库不可用时阻止 FastAPI app 创建。
8. 运行：`python -m pytest tests/task_management/test_service.py tests/task_management/test_persistent_task_service.py tests/api/test_exploration_tasks.py -q`。
9. 提交：`feat: restore persisted terminal exploration tasks safely`。

## 任务 4：接入权限比较和统一知识导出的持久化来源

**文件：**

- 修改：`backend/src/ai_ui_explorer/permission_comparison/service.py`
- 新增：`backend/src/ai_ui_explorer/permission_comparison/persistence.py`
- 修改：`backend/src/ai_ui_explorer/exploration_knowledge/service.py`
- 修改：`backend/src/ai_ui_explorer/main.py`
- 修改：`backend/tests/permission_comparison/test_permission_comparison_service.py`
- 新增：`backend/tests/permission_comparison/test_persistent_comparison_service.py`
- 修改：`backend/tests/exploration_knowledge/test_service.py`
- 修改：`backend/tests/api/test_permission_comparisons.py`
- 修改：`backend/tests/api/test_exploration_knowledge.py`

**步骤：**

1. 先写失败测试：终态比较在服务重建后可读取详情、差异、页面、导出和 `ComparisonKnowledgeSource`；统一知识来源目录和按需包导出可组合已持久化任务与比较来源。
2. 先写失败测试：比较在任一身份处于 created、paused_for_human 或 collecting 时被启动恢复协调器中断后，比较状态为 failed，结果为 `null`，没有权限结论，也不能确认登录、取消或继续执行。
3. 为比较服务注入持久化端口：创建时写最小索引；仅在 `_finalize()` 或安全取消/失败得到终态投影后，事务写入结果和来源索引。禁止把身份认证计划、原始命令或浏览器对象传入 Repository。
4. 将比较 `get`、列表、页面、差异、export 和 knowledge_source 扩展为内存优先、终态 PostgreSQL 回退。持久化记录缺失 bundle 时只读取已验证 JSONB，不重建 Collector。
5. 将 `ExplorationKnowledgeExportService.sources()` 和 `_resolve_sources()` 连接到服务的持久化回读路径，保留现有最多 5 来源与 JSON 包预算；下载包仍按需生成且不落库。
6. 在应用启动恢复中，先中断非终态任务和比较，再暴露路由；恢复过程不创建子任务或比较结论。
7. 运行：`python -m pytest tests/permission_comparison/test_permission_comparison_service.py tests/permission_comparison/test_persistent_comparison_service.py tests/exploration_knowledge/test_service.py tests/api/test_permission_comparisons.py tests/api/test_exploration_knowledge.py -q`。
8. 提交：`feat: persist terminal comparisons and knowledge sources`。

## 任务 5：完成 API 错误隔离与 Vue 的重启中断体验

**文件：**

- 修改：`backend/src/ai_ui_explorer/api/routes/exploration_tasks.py`
- 修改：`backend/src/ai_ui_explorer/api/routes/permission_comparisons.py`
- 修改：`backend/src/ai_ui_explorer/api/routes/exploration_knowledge.py`
- 修改：`backend/src/ai_ui_explorer/main.py`
- 修改：`frontend/src/api/explorationTasks.ts`
- 修改：`frontend/src/api/permissionComparisons.ts`
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/components/ExplorationTaskDetail.vue`
- 修改：`frontend/src/components/PermissionComparisonDetail.vue`
- 修改：`frontend/src/components/ExplorationKnowledgeExport.vue`
- 新增或修改：`frontend/src/**/*.spec.ts`
- 修改：`backend/tests/api/test_exploration_tasks.py`
- 修改：`backend/tests/api/test_permission_comparisons.py`
- 修改：`backend/tests/api/test_exploration_knowledge.py`

**步骤：**

1. 先写失败 API 测试：数据库读取/DTO 校验失败映射为固定、不含 SQL、URL、JSON 原文的错误代码；已恢复的终态任务仍返回原契约；对 interrupted 任务调用确认或取消返回安全拒绝。
2. 先写失败 Vue 测试：任务事件含 `process_restarted` 时显示固定中文中断提示；结果、页面、流程、差异与知识包入口仍可浏览；不渲染确认登录、取消、重放或恢复控制。
3. 为 TypeScript 状态和事件类型增加可持久化回读的 `interrupted` 阶段/原因码，而不把它误当作可轮询运行状态；比较状态类型补齐 `failed`，轮询在所有终态停止。
4. 更新 `App.vue` 的产品边界文字：说明终态脱敏结果可在重启后读取，未完成任务会安全终止，登录态仍不可恢复。
5. 将路由层 Repository/服务错误转换为固定 API 错误，不返回数据库驱动异常；保留现有响应 DTO 与下载文件格式。
6. 运行后端 API 测试和前端单测、类型检查、lint：`python -m pytest tests/api -q`、`npm test -- --run`、`npm run typecheck`、`npm run lint`。
7. 提交：`feat: present safe restart interruption in the UI`。

## 任务 6：执行 PostgreSQL 重启验收、真实 Chromium 验收与文档同步

**文件：**

- 新增：`backend/tests/integration/test_safe_task_persistence_restart.py`
- 新增或修改：`backend/tests/integration/conftest.py`
- 修改：`README.md`
- 修改：`docs/00-project-context.md`
- 修改：`docs/superpowers/specs/2026-08-18-v1-safe-task-persistence-design.md`
- 修改：`docs/superpowers/plans/2026-08-18-v1-safe-task-persistence.md`

**步骤：**

1. 先写失败端到端测试：使用本地虚构 HTTP 登录站点和真实 Chromium 完成一个任务；销毁 app/service、保留同一 PostgreSQL、重建 app/service；验证不启动浏览器即可读取终态摘要、页面、workflow、任务导出、比较导出和统一知识包。
2. 先写失败恢复验收：在浏览器停在 `paused_for_human` 和 runner 处于 `collecting` 时模拟进程重建；验证记录被标记 `failed/interrupted/process_restarted`、不产生流程/权限结论、不会读取 Cookie 或 Storage State，且前端/API 不提供继续入口。
3. 以隔离 PostgreSQL 运行：`alembic upgrade head`、迁移重复升级、持久化集成测试和 Chromium 重启测试。若环境未配置测试数据库，记录为环境前置条件，不能把未运行描述为通过。
4. 同步 README 与项目上下文：仅把已实际验证的持久化能力标为实现；明确 PostgreSQL 配置、迁移命令、无限保留责任和禁止持久化的登录态/敏感内容。
5. 执行全量质量门：
   - `python -m pytest -q`
   - `ruff check src tests`
   - `mypy src/ai_ui_explorer`
   - `npm test -- --run`
   - `npm run lint`
   - `npm run typecheck`
   - `npm run format:check`
   - `npm run build`
6. 提交：`test: verify safe PostgreSQL persistence restart behavior`；随后按 `superpowers:verification-before-completion` 记录实际命令和结果。

## 最终验收标准

1. 无 `AI_UI_EXPLORER_DATABASE_URL` 或 PostgreSQL 不可连接时，应用无法启动，且日志/API 不泄露凭据或驱动异常。
2. 所有终态任务和比较在新服务实例中可经既有 API、Vue 与按需知识包读取；其 DTO 通过既有 Schema/Pydantic 校验。
3. 任何非终态任务或比较重启后均变为 `failed / interrupted / process_restarted`，没有浏览器、线程、登录态、重放或自动恢复。
4. 数据库、迁移、日志、下载与 Git 内容均不出现 Cookie、Token、Storage State、密码、输入值、原始 DOM/HTML、Snapshot、网络正文或截图。
5. 真实 Chromium 本地虚构站点验收与全量后端/前端质量门均有实际通过记录；未运行的 PostgreSQL 前置测试明确标为未验证，而非“通过”。
