# Sprint 10 V1 安全任务持久化设计

## 1. 目标

Sprint 10 为现有受控探索、权限比较、证据浏览、只读流程和统一知识包提供 PostgreSQL
持久化。服务重启后，用户仍可查询和导出已完成任务的脱敏结果；任何重启前未完成的任务都
安全终止，绝不尝试恢复浏览器、线程或登录会话。

## 2. 范围

### 包含

- PostgreSQL-only 数据库、SQLAlchemy 模型与 Alembic 迁移。
- 脱敏任务元数据、终态证据、workflow、权限比较结果和知识来源索引的持久化。
- 启动恢复：将非终态任务和比较标记为 `failed` / `process_restarted`。
- 既有 API、知识导出和 Vue 只读浏览在重启后的终态投影读取。
- 中断提示与本地虚构站点的重启后 Chromium 验收。

### 不包含

- Cookie、Token、Storage State、密码、输入值或浏览器登录态持久化与复用。
- Browser Context、线程、Worker、Redis、跨进程续跑、任务抢占、重试或队列。
- 原始 DOM/HTML、Snapshot、网络正文、截图和业务动作。
- 真实外站、SSO、扫码、MFA、访问控制绕过或业务权限推断。

## 3. 持久化边界

数据库只接收已脱敏、可 JSON 序列化并经 Pydantic/Schema 校验的白名单 DTO。所有写入都
沿用既有数量和字节预算；未知未来 `schema_version` 的记录在读取时固定拒绝，不能猜测兼容。

禁止落库的对象包括浏览器对象、线程句柄、Collector、Cookie、Token、Storage State、密码、
输入值、原始 DOM/HTML、网络正文、截图与未脱敏 Snapshot。

数据不自动删除。即使内容已脱敏，部署方仍负责无限期保留产生的存储、合规和人工清理责任；
模型为未来人工删除和保留策略保留扩展点。

## 4. 数据模型

使用关系索引加受限 JSONB 投影，而不把当前 DTO 全面关系化：

- `exploration_tasks`：任务 ID、时间、模块、预算、允许 Origin、状态、阶段、固定原因码、
  摘要计数与格式版本。
- `task_evidence_exports`：终态 `ExplorationEvidenceExport` JSONB。
- `task_workflows`：终态 `TaskWorkflowExport` JSONB。
- `permission_comparisons`：比较索引及终态 `PermissionComparisonResult` JSONB。
- `exploration_knowledge_sources`：可导出来源索引；完整知识包继续按需构建，不持久化下载包。

终态为 `completed`、`partial`、`failed`、`cancelled`。非终态记录只保存索引与最小审计，
没有可恢复运行时。

## 5. 运行与恢复语义

在线执行保持现有 API → 内存注册表 → 后台线程模型。任务或比较进入终态时，先投影脱敏 DTO，
再以事务写入索引和 JSONB。

服务启动时执行一次恢复协调：读取所有非终态记录，原子更新为 `failed`、阶段
`interrupted`、原因码 `process_restarted`，并追加最小审计事件。它不创建浏览器、不读取
登录数据、不恢复线程，也不伪造完成结果。

服务层读取优先当前进程运行时；不存在时只读取 PostgreSQL 的终态投影。恢复后的中断任务
拒绝 `confirm-login` 和 `cancel`。比较任务任一未完成身份中断时，不产生权限结论。

## 6. 配置、接口与 UI

`DATABASE_URL` 是必填配置。无法连接 PostgreSQL 时应用启动失败，不回退到内存伪持久化。
数据库凭据仅由环境变量或部署 secret 注入。SQLAlchemy 和 Alembic 是唯一数据库/迁移路径。

既有任务、页面、workflow、比较和知识导出 API 保持响应契约。持久化读取或验证失败仅返回
固定安全错误，绝不回显原始 JSON 或数据库异常。Vue 对 `process_restarted` 显示固定中断提示，
仍允许浏览终态脱敏结果；不展示确认、取消、重放或登录态控制。

## 7. 验证

- Repository 单元测试拒绝运行时对象、敏感字段和未知未来版本。
- 集成测试覆盖终态任务与比较在服务重建后的页面、workflow 和知识导出读取。
- 恢复测试覆盖 `paused_for_human`、`collecting` 与比较身份被安全中断，且不创建浏览器。
- Alembic 测试覆盖空库升级、重复升级和版本读取拒绝。
- API/Vue 测试覆盖固定中断提示和无确认/取消控制。
- 真实 Chromium 本地虚构站点验收覆盖终态重启后读取；不持久化或使用真实登录态。

## 8. 取舍

本设计优先实现可靠的终态可读性与安全失败，而非连续执行。独立 Worker、Redis、登录态加密
复用和跨进程恢复需要独立的威胁建模、密钥管理、租约与重试设计，不能混入 Sprint 10。
