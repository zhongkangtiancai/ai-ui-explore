# Sprint 8 统一探索知识包设计

## 1. 目标与范围

Sprint 8 将当前进程内已经完成的单次探索任务证据与多身份 UI 可见性比较结果，构建为一份可下载、可校验、可追溯的 `exploration-knowledge-package-v2`。它是 Application Knowledge Model 的任务运行时出口，供人工审阅、后续 LLM 上下文和测试设计消费者使用。

本 Sprint 的成功标准是：用户选择一个或多个已完成的任务和比较结果后，可以下载一份确定性、Schema 校验、脱敏且明确标记局限性的 JSON 包；包中同时包含页面、元素、定位器候选、身份可见性差异、事实、观察、证据和知识缺口。

## 2. 非目标

- 不修改 Sprint 2 的 `knowledge-package-v1`、其 CLI 或离线 Snapshot Builder。
- 不持久化知识包、Snapshot、DOM、HTML、网络正文、截图、Cookie、Token、输入值、浏览器或登录态。
- 不生成 AI 推断；`inferences` 固定为空。
- 不把 UI 可见性差异描述为业务权限、后端数据范围或授权结论。
- 不执行点击、输入、提交、审批、删除、支付、发布或流程回放。
- 不实现跨进程恢复、数据库、Worker、分片导出或大包自动截断。

## 3. 输入边界

构建器只接收当前进程中已有的受限投影：

- 单任务：`TaskSummary`、`ExplorationEvidenceExport`、任务内的 `PageEvidence`。
- 权限比较：`PermissionComparisonResult`、其 `IdentityEvidenceBundle`、`PageEvidence` 与 `VisibilityDifference`。

构建器不得读取 `SnapshotDocument`、`RawBrowserObservation`、Playwright `Page`/`BrowserContext`、任务私有运行时或认证状态。源服务只提供已脱敏、白名单化的读取 DTO；任务或比较尚未到达终态时拒绝导出。

## 4. 包模型

顶层模型：

```json
{
  "schema_version": "2.0",
  "package_id": "exploration-package-...",
  "sources": [],
  "identities": [],
  "pages": [],
  "elements": [],
  "locator_candidates": [],
  "facts": [],
  "visibility_differences": [],
  "observations": [],
  "knowledge_gaps": [],
  "inferences": []
}
```

### 4.1 Sources

`sources` 记录任务或比较结果的安全 ID、种类、终态和固定停止原因。它不记录登录计划、认证检查点、浏览器地址、原始 URL 查询参数或任何运行时句柄。

### 4.2 Identities

`identities` 只来自比较结果，包含安全 `identity_id` 与现有的非敏感显示标签。单任务不伪造身份。身份与页面/元素通过来源关系关联，而不是通过名称猜测。

### 4.3 页面、元素与定位器

页面和元素实体复用 `PageEvidence`/`ElementEvidence` 的脱敏字段。每个实体 ID 由来源安全 ID、可选身份 ID、页面或元素稳定键及确定性序号产生，因此不同运行、不同身份或同名页面不会被错误合并。

定位器候选保留策略、脱敏参数、唯一性、稳定性、置信度、推荐标记、Frame 范围、限制和证据引用。它们是观测信息，不是可执行代码，也不保证跨页面版本稳定。

### 4.4 Facts、Observations 与 KnowledgeGaps

`facts` 只表达直接观测：页面存在、元素角色、可访问名称、文本、可见性、启用状态、白名单属性、链接目标和定位器元数据。每条 Fact 引用至少一个证据，置信度固定为 `1.0`，含义仅为“本次输入直接观察到”。

`observations` 保存不会升级为 Fact 的信号，例如差异结果中可见但可靠性不足的现象。`knowledge_gaps` 以固定代码和安全描述表示：`collection_truncated`、`authentication_unverified`、`collection_failed`、`not_matchable`、`actions_not_explored`、`workflows_not_observed` 与 `evidence_process_local`。

只要来源或差异带有 `partial`、认证未验证、采集失败、不可匹配或不可比较状态，相关差异保持不确定；不得写出“允许”“拒绝”“拥有角色”或数据权限结论。

`inferences` 始终为 `[]`，不因输入内容改变。

## 5. 确定性与安全

- 调用前对来源 ID 去重并以安全 ID 词典序排序；每一类实体按来源、身份、稳定键和原有顺序排序。
- 相同受限输入生成字节稳定的 JSON；不使用当前时间、随机 UUID 或任务私有对象地址。
- 所有字符串经过现有 `Redactor`，并对包序列化 JSON 做敏感 fixture 扫描测试。
- 输出同时通过 Pydantic 与提交的 JSON Schema 校验。
- 固定总预算：最多 5 个来源、500 个页面、20,000 个元素、20,000 条差异、50,000 条证据和 10 MiB UTF-8 JSON。超过任一预算时拒绝导出并返回固定安全错误；不静默删除事实或降级可靠性。
- Evidence 仅保留既有安全 ID、Snapshot 哈希、JSON Pointer 和受限摘要。由于原 Snapshot 不保存，指针只在当前进程和来源仍在内存时可辅助人工核查；包必须含 `evidence_process_local` 缺口。

## 6. API 与前端

新增按需导出端点：

```http
POST /api/v1/exploration-knowledge-packages/export
Content-Type: application/json

{
  "task_ids": ["task-1"],
  "comparison_ids": ["comparison-1"]
}
```

请求体 `extra="forbid"`，两个列表至少有一个非空，只接受现有安全 ID 格式。未知来源、非终态来源、空来源、无权读取、Schema 失败和包超预算均映射为固定、不回显用户输入或异常文本的错误响应。成功时返回 `application/json` 附件 `exploration-knowledge-package.json`。

Vue 在现有任务与比较结果区域提供只读选择器与“下载统一知识包”按钮。页面只显示来源计数、终态和导出限制；不显示认证信息、不控制 Browser、不渲染原始 HTML。下载失败时展示固定安全消息。

## 7. 验证

- 模型与 Builder：确定性排序、Schema 校验、来源去重、实体不错误合并、Fact 证据闭包、`inferences=[]`、固定缺口和预算拒绝。
- 安全：敏感 fixture 值、Cookie、Token、密码、浏览器对象、原始 Snapshot 字样不进入序列化包或错误响应。
- API：单任务、单比较、混合来源、未知/非终态/非法请求、附件头和 Schema 校验。
- 前端：选择任务与比较、下载请求、禁用无来源提交、固定错误状态和不渲染不可信内容。
- 端到端：本地 Chromium 登录任务与本地多身份比较完成后，下载包同时包含任务页面证据和比较差异；任何 partial 结果只显示不确定性与缺口。

## 8. 取舍

独立 v2 避免改变 Sprint 2 的离线 Snapshot 契约，也避免将单进程任务语义混入 v1。它牺牲了跨重启可追溯性和大包处理能力，但这些应在后续持久化与 V1.1 巡检设计中解决，不能在本 Sprint 用不受控文件或数据库替代。
