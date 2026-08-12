# Sprint 6：多身份受控探索与权限差异知识设计

## 文档状态

- 日期：2026-08-12
- 状态：待用户审核
- 适用范围：Sprint 6 的多身份探索、任务内详细结果、确定性可见性差异、明细 API/UI 与 JSON 导出
- 已选方案：进程内详细结果 + 受控下载 JSON；数据库、独立 Worker 与跨进程恢复留至 Sprint 7

## 1. 目标

将现有的单身份受控探索任务扩展为可比较的多身份探索：由测试人员以多个获授权身份分别完成必要的人工登录，系统在相同模块、Origin、预算与只读策略下采集脱敏页面证据，展示页面、元素、链接和定位器明细，并输出确定性的身份可见性差异。

Sprint 6 的核心结果是“有证据的可见性差异”，不是对真实业务权限规则的自动裁决。缺少观察、预算截断、认证失败、采集失败或无法稳定匹配，都必须明确标为无法确认，不能转换为“没有权限”。

## 2. 范围与非目标

### 范围

- 创建一个比较任务，包含 2–5 个非敏感身份别名，以及共同的模块入口、Origin、预算和只读策略。
- 每个身份使用独立、进程内的 Browser Context；需要登录时仍由人工在可见浏览器完成登录并显式确认。
- 在每次受控访问后保留有边界、已脱敏的页面、Frame、元素、链接、定位器和采集状态，供当前进程的明细与差异计算使用。
- 在所有身份终态后生成版本化、确定性的比较结果；支持完整、部分和无法比较状态。
- 提供任务、身份、页面、元素、差异、证据和知识缺口的安全 API、Vue 明细界面与按需下载 JSON。
- 通过本地多角色 HTTP fixture 与真实 Chromium 验收身份隔离、人工登录、差异、部分结果、取消和脱敏。

### 非目标

- 不保存账号、密码、Cookie、Token、验证码、Storage State、截图、网络正文或完整 HTML。
- 不自动填写登录表单，不绕过 MFA、扫码、反自动化或任何访问控制。
- 不执行按钮点击、提交、审批、删除、支付、上传等业务动作；继续只跟随已允许的只读链接导航。
- 不引入 PostgreSQL、Redis、独立 Worker、跨进程任务恢复、跨任务登录态复用或加密登录态存储。
- 不改变现有 `knowledge-package-v1` 的“一份快照一份知识包”契约，也不启用 LLM 推断、测试案例生成或 Playwright 代码生成。
- 不宣称外部网站、SSO、扫码或真实企业登录流程已验收可用。

## 3. 关键决策

1. **比较对象是身份别名，不是凭据。** `identity_id` 使用受控、非敏感标识；显示标签由用户提供但受长度和敏感词规则限制。认证计划只包含 URL、URL 前缀和检查点，不包含任何凭据。
2. **身份运行串行。** 同一比较任务一次只驱动一个身份的浏览器会话，避免多个可见浏览器、Playwright 线程亲和和人工确认混淆；每个会话终态立即关闭。
3. **详细结果保存在任务私有内存。** API 只返回白名单明细视图；服务重启、崩溃或任务被清理后，结果不可恢复。导出由当前内存的已脱敏模型流式生成，不在服务器保留导出文件。
4. **差异先比较观察，再解释可靠性。** 本 Sprint 不产生“某角色具有/不具有某业务权限”的推断；输出“仅在身份 A 中观察到”“身份 B 未观察到”“无法比较”等事实性分类。
5. **实体匹配必须保守。** 页面以规范化、已脱敏 URL 匹配；元素只在相同 Frame 路径且存在安全、稳定的匹配依据时匹配。低稳定 CSS/XPath、坐标或普通文本不能单独证明同一元素。
6. **共同探索条件是可比性的前提。** 同一比较任务的身份必须共享入口、允许 Origin、预算和动作门禁；若任一身份的设置不同，创建请求拒绝，而不是产出误导性差异。

## 4. 数据模型

### 4.1 比较任务

`PermissionComparisonCommand` 包含：

- `comparison_id`：系统生成的安全 ID。
- `module_entry`、`allowed_origins`、`authentication_origins`、`ExplorationBudget`、`allow_local_http`：所有身份共享的显式探索配置。
- `identities`：2–5 个 `IdentityProfile`。

`IdentityProfile` 包含 `identity_id`、安全显示标签和可选 `AuthenticationPlan`。没有认证计划的身份按非登录探索执行；有认证计划的身份进入既有人工登录流程。身份之间不共享 Browser、Context、Page、Collector、取消令牌或认证结果。

### 4.2 身份证据包

每个身份运行完成后，在任务私有内存中生成 `IdentityEvidenceBundle`：

- `identity_id`、运行状态、可比性状态、开始/结束时间和安全原因码。
- 有界 `PageEvidence` 列表，每页包括已脱敏 URL、页面状态、Frame 摘要、元素和链接观察、采集错误与预算信息。
- `ElementEvidence` 仅保留 Sprint 1 已允许的结构字段、经过脱敏的文本摘要、定位候选、Frame 作用域和来源指针；不保留输入值、HTML 或浏览器对象。
- 每项记录都带 `EvidenceRef`：快照 ID、Schema 版本、JSON Pointer、规范化快照摘要和有限证据摘要。
- `KnowledgeGap`：记录身份未登录、认证失败、页面预算耗尽、状态去重停止、采集失败、定位器无法稳定匹配等限制。

详细数据上限沿用并收紧已有 Snapshot/知识模型预算：身份数最多 5、每身份最多 100 页、每页最多使用采集器现有元素上限；超限时运行标记为 `partial` 并添加 `collection_truncated` 缺口。

### 4.3 差异结果

`PermissionComparisonResult` 的记录为 `VisibilityDifference`：

- `difference_id`、比较范围（页面或元素）、`subject_key`、参与身份。
- `kind`：`observed_in_only_one_identity`、`observed_in_multiple_identities`、`safe_attribute_changed`、`link_target_changed`、`not_comparable`。
- 每个身份的观察状态：`observed`、`not_observed`、`collection_incomplete`、`authentication_unverified`、`collection_failed`、`not_matchable`。
- `reliability`：`high`、`medium`、`low`、`inconclusive`。
- `evidence_refs`、受控 `reason_codes`、限制和验证建议。

不得出现 `permission_granted`、`permission_denied` 之类没有直接服务端授权证据的结论。只有目标站点在已观察页面中明确提供脱敏、允许的拒绝状态证据时，才可保留为 `access_denied_observed`，并仍不推广为全局权限规则。

## 5. 可比性与匹配规则

### 页面

- 使用 NavigationPolicy 已规范化且脱敏后的 URL 作为页面键；根目录 `/` 与无查询、无片段的 `/index.html` 按现有队列规则视为同一页面。
- 相同页面键在两个身份都有完整观察时，页面集合差异可靠性最高。
- 一个身份未观察到页面，只能称为“未观察到”；若该身份运行部分完成、认证未验证、入口不可达或页面预算耗尽，可靠性必须是 `inconclusive`。

### 元素

元素匹配按以下优先级选择第一个可验证依据：

1. 同 Frame 内唯一、稳定的 `testid`。
2. 同 Frame 内唯一的安全 `id`。
3. 同 Frame 内唯一的精确 role + accessible name。
4. 同 Frame 内唯一的安全链接目标 + role/name。

只有相同页面键、相同规范化 Frame 路径和相同匹配依据的元素才可比较。CSS、XPath、位置、动态 class、普通文本或顺序只能作为证据或人工排查线索，不能单独建立跨身份元素等同关系。

### 可靠性

- `high`：参与身份均完整、已认证（如需要）、页面可比，且存在唯一稳定的匹配与直接证据。
- `medium`：页面完整但元素匹配依赖唯一 role/name 或安全链接目标，或存在有限采集限制。
- `low`：只有单边直接观察，另一边在可比较页面中未观察到，但未满足完整覆盖条件。
- `inconclusive`：任一边部分完成、认证失败/未验证、页面未访问、无稳定匹配、页面状态去重阻断或出现采集失败。

## 6. 运行时与数据流

```text
比较任务创建
  -> 依次创建身份子任务
  -> （若需要）人工在对应可见浏览器登录并确认
  -> 同一身份 Context 中受控只读探索
  -> Snapshot 访问钩子收集脱敏详细证据
  -> 关闭该身份 Context
  -> 下一个身份
  -> 所有身份终态后，确定性比较与生成结果
  -> 明细 API / Vue 视图 / 按需 JSON 下载
```

在 Runner 与任务服务之间新增窄的 `ExplorationEvidenceSink`：只接收已经过采集器脱敏和模型校验的 `SnapshotDocument`、目标和访问状态。它不接收 Page、Context、Browser、凭据或网络响应。服务把快照立即投影为 `IdentityEvidenceBundle`，并在比较结果完成后仅保留受控模型。

现有单身份任务 API 保持兼容；多身份功能使用独立比较 API，不把身份数组塞入现有单任务模型，避免破坏既有安全边界。

## 7. API 与前端

### API

新增端点：

```text
POST /api/v1/permission-comparisons
GET  /api/v1/permission-comparisons/{comparison_id}
GET  /api/v1/permission-comparisons/{comparison_id}/identities/{identity_id}/pages
GET  /api/v1/permission-comparisons/{comparison_id}/pages/{page_key}
GET  /api/v1/permission-comparisons/{comparison_id}/differences
GET  /api/v1/permission-comparisons/{comparison_id}/export
POST /api/v1/permission-comparisons/{comparison_id}/identities/{identity_id}/confirm-login
POST /api/v1/permission-comparisons/{comparison_id}/cancel
```

所有请求/响应采用 `extra="forbid"` 和白名单字段。未知 ID、身份错配、非法状态、超出边界的筛选器和终态操作使用固定安全错误码。下载响应为版本化 JSON，并经同一模型/Schema 校验；不得包含运行时对象、选择器原始异常、完整 URL 查询参数或秘密字段。

### 前端

新增比较任务创建页与比较详情页：

- 选择 2–5 个身份别名，配置共同入口和预算；登录配置按身份展开，不出现凭据输入框。
- 串行显示当前待登录身份、人工确认、进度、终态和安全原因码。
- 身份列对照的页面列表；选择页面后显示 Frame、元素、链接、定位器和对应证据摘要。
- 差异列表支持按身份、页面、对象类型、可靠性和“无法确认”筛选。
- 可靠性标签必须解释原因；默认先展示 `high`/`medium`，但用户可显式查看 `low`/`inconclusive`。
- 提供“下载已脱敏比较 JSON”；不显示或缓存登录凭据、Cookie、Token 或浏览器存储状态。

当前产品没有多用户访问控制，因此 Sprint 6 界面仅适用于受信任的本机/受控内部操作者。面向共享部署的产品级访问控制、导出授权和审计留到 Sprint 7，不能在本 Sprint 中宣称已解决。

## 8. 失败处理与安全

- 任一身份的 Browser Context 终态必须关闭；取消比较任务会触发当前身份的取消令牌，并阻止启动后续身份。
- 一个身份失败不会抹去已完成身份的证据；比较结果为 `partial`，相关差异标记 `inconclusive`。
- 身份标签、审计、差异原因和导出内容全部执行白名单/敏感词验证；拒绝任何疑似凭据、Cookie、Token、验证码或 storage 字样进入公共模型。
- 原始 Snapshot 只在任务私有内存中以已脱敏版本存在；任务清理、进程重启或崩溃后不可恢复。
- 所有 URL、证据摘要、定位参数和错误面复用现有脱敏器；不新增原始网络或页面内容采集。
- 输出目录和本地 fixture 继续被 Git 忽略；测试使用虚构身份与本地内容。

## 9. 测试与验收

### 单元与模型

- 身份配置拒绝凭据、重复/非法身份 ID、超过身份数和不可比较的共同配置。
- 详细证据模型、导出模型与提交的 JSON Schema 一致；额外字段、敏感字段和越界预算均拒绝。
- 页面 `/` 与 `/index.html` 一致性、页面/元素匹配优先级、稳定性和可靠性计算可重复。
- 部分、认证失败、未访问、状态去重和无稳定元素匹配全部产出 `inconclusive`，不产生权限断言。
- 导出字节级确定性；扫描确认不存在密码、Cookie、Token、验证码、Storage State、完整 HTML、截图或网络正文。

### 服务、API 与前端

- 身份按顺序运行、会话严格隔离、任务终态释放 runtime。
- 详细端点只返回白名单字段；身份不能读取其他比较任务的私有运行时。
- 取消、未知任务、确认错身份、终态重试、后台异常和下载错误均使用固定安全面。
- Vue 覆盖创建、待登录、身份进度、页面明细、差异筛选、无法确认提示、下载与轮询停止。

### 真实 Chromium 本地验收

构建本地多角色 fixture：管理员能看到管理页和“用户管理”链接；普通用户只能看到工作台；第三个受限身份登录后停在明确拒绝页。验证：

1. 三个身份各自在独立可见 Context 中完成/失败登录，互不共享状态。
2. 管理员与普通用户的页面、链接和元素差异有直接证据。
3. 受限身份或预算截断只产生无法确认，不被标为无权限。
4. 页面明细显示安全定位器和证据摘要，下载 JSON 与 API 视图一致且无秘密。
5. 取消或异常后 Context 全部关闭，后续身份不启动。

## 10. 完成标准

Sprint 6 完成需要同时满足：

1. 2–5 个身份可在共同、受控配置下串行探索，人工登录沿用现有安全验证。
2. 每个身份的页面、元素、链接、定位器、证据和缺口可在当前进程内通过 API/UI 查看。
3. 比较结果确定性、可追溯，明确区分直接观察、低可靠差异和无法确认。
4. 没有缺失观察被自动升级为权限结论；未实现业务动作或访问控制绕过。
5. JSON 导出通过模型/Schema 校验且不含秘密、浏览器状态、截图、网络正文或完整 HTML。
6. 本地多角色真实 Chromium E2E、后端测试、前端测试、Lint、类型检查和构建全部通过。
7. 文档准确声明单进程内存、无恢复、无产品级多用户授权与仅本地 fixture 验收的限制。

## 11. 已知风险与后续

- 仅靠前端可见性无法证明后端数据权限；Sprint 6 只能报告 UI 可见性与可达性差异。
- 动态 SPA、A/B 实验、语言、时间和测试数据差异会产生非权限差异；实际验收应固定环境、租户、数据和浏览器条件。
- 页面与元素跨身份匹配天然存在不稳定性，因此规则必须宁可产出“无法比较”，不能强行配对。
- 详细结果放在内存会受到页面数量和任务时长限制；Sprint 7 再以数据库、Worker、恢复与加密存储解决。
- 周期巡检、跨时间版本匹配和变化报告属于 V1.1，不能复用 Sprint 6 的一次性比较结果直接宣称实现。
