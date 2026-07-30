# Sprint 2 Application Knowledge Model 设计

## 文档状态

- 日期：2026-07-30
- 状态：设计讨论已完成，等待书面评审
- 适用范围：Sprint 2 知识模型、JSON 知识包和 Snapshot 1.1 定位知识前置扩展
- 不代表：当前代码已经实现知识包、推断、案例生成或自动化代码生成

## 1. 背景

Sprint 1 已实现有边界、只读、脱敏的单 URL 结构化页面快照。快照记录页面、Frame、元素、滚动、错误和预算等观测结果，但它仍是采集产物，不是可供后续推理、权限分析和测试生成直接消费的 Application Knowledge Model。

Sprint 2 将一份 Sprint 1 快照确定性转换为一份独立、不可变、可校验的知识包，建立实体、事实、证据、低可靠观察、推断契约和知识缺口之间的明确边界。

为了提高未来测试案例生成和 Playwright 自动化代码生成的质量，Sprint 2 开始前需要将快照契约升级为向后兼容的 1.1，补充有来源、有唯一性验证、有稳定性说明的定位候选。

## 2. 目标

- 一份探索快照生成一份独立的 `knowledge-package.json`。
- 知识包通过 `snapshot_id`、JSON Pointer 和 SHA-256 摘要与原快照建立可验证证据链。
- 只把可直接观察的数据提升为事实。
- 保留已观察但证据不足的信号，并明确其置信度和限制。
- 明确记录预期需要但本次没有获得的知识及缺失原因。
- 实现推断数据契约，但本阶段不自动产生推断。
- 为页面元素保存分层、排序、可解释的 Playwright 定位知识。
- 相同输入产生字节级一致的知识包。
- 提供 CLI 和可直接调用的 Python Builder API。
- 使用 Pydantic 和提交到版本库的 JSON Schema 双重校验。
- 保持输出有界、脱敏、原子写入和可追溯。

## 3. 非目标

- 不调用 LLM 或 Agent。
- 不实现自然语言或规则引擎推断。
- 不实现测试案例生成和 Playwright 自动化代码生成。
- 不创建 PostgreSQL、pgvector、Redis、Worker 或数据库迁移。
- 不新增 FastAPI 知识包上传接口或前端知识页面。
- 不合并多次探索结果，不实现跨快照实体等同性判断或 Diff。
- 不创建没有可靠数据来源的 Module、Action、Workflow、Permission、DataScope 或 ChangeHistory 实体。
- 不重新访问目标网站来补充知识。
- 不采集完整 HTML、任意 DOM 属性、网络正文、Cookie、Token、Storage State 或登录状态。
- 不把低可靠观察或知识缺口伪装成事实。

## 4. 已确认的设计决策

1. 知识包独立于 Sprint 1 快照，通过引用关联，不嵌入快照 Schema。
2. Sprint 2 只确定性生成事实和证据；`inferences` 默认为空。
3. 强类型实体限于当前有可靠来源的 Application、Page、Frame、Element、ExplorationRun 和 IdentityContext；Locator 作为一级定位知识对象保存。
4. 同时引入 `observations` 与 `knowledge_gaps`。
5. 证据保存快照 ID、Schema 版本、JSON Pointer、脱敏有限摘要和快照 SHA-256。
6. 同一快照重复转换产生相同 ID；跨快照只输出匹配提示。
7. Snapshot 升级到向后兼容的 1.1，采集分层定位候选。
8. Application 身份由版本化、非敏感的应用清单提供。
9. 一份快照对应一份不可变知识包。
10. 采用“轻量实体 + 原子事实”。
11. 提供 `ai-ui-knowledge` CLI 和 Python Builder API。
12. 达到知识包预算时保留有效部分，标记 `partial` 并记录知识缺口。

## 5. 总体架构

```text
Application Manifest
        +
Snapshot 1.0 / 1.1
        |
        v
KnowledgePackageBuilder
        |- SnapshotAdapter
        |- EntityMapper
        |- LocatorMapper
        |- EvidenceBuilder
        |- FactBuilder
        |- ObservationClassifier
        |- KnowledgeGapBuilder
        `- PackageValidator
        |
        v
knowledge-package.json
```

### 5.1 SnapshotAdapter

- 读取并校验 Snapshot 1.0 或 1.1。
- 向 Builder 提供统一内部视图。
- 对 1.0 缺失的定位知识只记录缺口，不推测 CSS/XPath。
- 不访问浏览器或目标网站。

### 5.2 EntityMapper

- 从应用清单和快照映射轻量实体。
- 使用来源 JSON Pointer 生成确定性 ID。
- 不创建没有数据来源的未来实体。

### 5.3 LocatorMapper

- 转换 Snapshot 1.1 的定位候选。
- 转换 Snapshot 1.0 已有的 role、label、test id、id 和边界提示。
- 保留排序、唯一性、稳定性、置信度、来源和限制。

### 5.4 EvidenceBuilder

- 生成可回到原快照的 JSON Pointer。
- 提取经过脱敏和长度限制的证据摘要。
- 绑定原快照的规范化 JSON SHA-256。

### 5.5 FactBuilder

- 把可直接观察的属性和关系转换为原子事实。
- 使用受控谓词命名空间。
- 不产生业务推断。

### 5.6 ObservationClassifier

- 只根据明确、确定性的分类规则记录低可靠信号。
- 不使用自然语言启发式猜测页面业务含义。

### 5.7 KnowledgeGapBuilder

- 记录未观察到、证据不足、版本受限、访问受限或超出本 Sprint 的知识。
- 提供原因代码和后续验证建议。

### 5.8 PackageValidator

- 校验模型不变量、引用完整性、预算和敏感信息规则。
- 校验 Pydantic Schema 与提交的 JSON Schema 一致。
- 只有通过校验的包才能交给 Writer 原子写入。

## 6. 输入契约

### 6.1 Application Manifest

应用身份不能仅根据页面标题或域名推断。应用清单至少包含：

```json
{
  "schema_version": "1.0",
  "application_id": "customer-service-portal",
  "name": "客服管理平台",
  "environment": "test",
  "allowed_origins": [
    "https://test-customer.example.internal"
  ],
  "authentication_origins": [
    "https://sso.example.internal"
  ]
}
```

约束：

- `application_id` 是稳定、非敏感标识。
- origin 必须包含协议和主机，不得包含路径、查询参数或凭据。
- 使用规范化后的精确 origin 校验，禁止不安全的字符串后缀匹配。
- 默认禁止 HTTPS 降级。
- 请求 URL 必须属于 `allowed_origins`。
- 最终 URL 若属于认证域名，只能作为访问状态证据，不能伪装成目标页面事实。
- 清单不得保存账号、密码、验证码、Cookie 或 Token。
- 清单使用独立、版本化的 JSON Schema。

### 6.2 Snapshot

- Builder 必须支持 Snapshot 1.0 和 1.1。
- Snapshot 必须先通过对应版本的 JSON Schema。
- Builder 不修补无效快照。
- Builder 不重新打开 URL。
- Snapshot URL 和错误摘要进入知识包前继续执行脱敏。

## 7. Snapshot 1.1 定位知识扩展

### 7.1 目的

Snapshot 1.0 只包含有限的 role、label、test id、id 定位提示和边界坐标，无法为 CSS/XPath 提供足够的生成与唯一性证据。Snapshot 1.1 在采集时建立有界的 `locator_candidates`。

### 7.2 定位候选结构

```json
{
  "locator_id": "locator-...",
  "element_ref": "element-...",
  "frame_ref": "frame-...",
  "strategy": "role",
  "parameters": {
    "role": "button",
    "name": "提交",
    "exact": true
  },
  "source": "observed",
  "uniqueness": "unique",
  "match_count": 1,
  "stability": "high",
  "confidence": 1.0,
  "rank": 1,
  "recommended": true,
  "evidence_refs": ["evidence-..."],
  "limitations": []
}
```

快照中的候选尚未拥有知识包 Evidence ID 时，使用可解析的快照内来源引用；Knowledge Builder 在转换时生成正式 Evidence 引用。

### 7.3 支持策略

定位策略分层：

1. 用户语义：`role`、`label`、`text`、`placeholder`、`alt`、`title`
2. 显式测试契约：`testid`
3. 属性：`id`、`name`、允许的 `aria-*`
4. 结构：`css`、`xpath`
5. 位置：`position`

实际排名同时考虑唯一性、稳定性和可用性。匹配多个元素的 role 候选不能排在唯一 test id 之前。

### 7.4 CSS 与 XPath

- 只使用允许的标签、属性和有限 DOM 结构。
- 表达式长度和层级有明确上限。
- 生成后必须在当前 Frame 内重新查询。
- 结果为一个元素时标记 `unique`。
- 结果为多个元素时可作为低优先级候选，但不得推荐代码生成。
- 无法校验时标记 `unverified`。
- 动态值、敏感值和超出预算的选择器不得保存。
- 不生成无限增长的绝对 DOM 链。
- XPath 无法穿透 Shadow DOM 时必须记录限制。

### 7.5 坐标

位置知识包含边界、viewport、Frame、可见状态和采集时间。它只用于布局诊断、未来视觉对齐和人工排查，不得标记为推荐定位器，也不得在 Sprint 2 中直接生成坐标点击代码。

### 7.6 稳定性

- `high`：唯一且基于明确测试契约或稳定的用户语义组合。
- `medium`：当前唯一，但依赖普通属性、可变文本或有限结构。
- `low`：依赖 DOM 层级、XPath、顺序或位置。
- `unknown`：证据不足。

稳定性和事实置信度分别建模。

### 7.7 1.0 兼容

读取 Snapshot 1.0 时：

- 转换现有 role、label、test id、id 定位提示。
- 转换已有边界为位置线索。
- 不生成缺乏原始证据的 CSS/XPath。
- 创建 `snapshot_version_limited` 知识缺口。

## 8. 知识包契约

顶层结构：

```json
{
  "schema_version": "1.0",
  "package_id": "kp-...",
  "status": "completed",
  "application": {},
  "exploration_run": {},
  "entities": [],
  "locator_candidates": [],
  "evidence": [],
  "facts": [],
  "observations": [],
  "inferences": [],
  "knowledge_gaps": [],
  "statistics": {}
}
```

### 8.1 实体

`entities` 只保存：

- `Page`
- `Frame`
- `Element`

`Application` 和 `ExplorationRun` 位于顶层。`IdentityContext` 由 `exploration_run.identity_context` 表达。Locator 存放在 `locator_candidates`，避免重复记录。

每个轻量实体保存：

- 确定性实体 ID
- 类型
- 可读标签
- Application 引用
- 来源引用
- 当前探索时间范围
- 跨快照匹配提示

不在实体上堆叠缺乏独立证据的业务属性。

### 8.2 Fact

```json
{
  "fact_id": "fact-...",
  "subject_ref": "element-...",
  "predicate": "element.role",
  "value": "button",
  "object_ref": null,
  "evidence_refs": ["evidence-..."],
  "confidence": 1.0,
  "assertion_type": "observed",
  "observed_at": "2026-07-30T00:00:00Z"
}
```

规则：

- `value` 与 `object_ref` 必须二选一。
- `predicate` 使用受控命名空间。
- Sprint 2 自动生成的事实只能是 `observed`。
- `confidence=1.0` 只表示该值在本次快照时刻被直接观察到，不表示永久稳定。
- 推断不能覆盖或修改事实。

### 8.3 Evidence

证据包含：

- Evidence ID
- `snapshot_id`
- Snapshot `schema_version`
- JSON Pointer
- 证据类型
- 脱敏、有限摘要
- 快照规范化 JSON SHA-256

摘要不是原文副本，不得包含完整页面正文、完整 Frame、完整 Element 或敏感值。

### 8.4 Observation

```json
{
  "observation_id": "observation-...",
  "summary": "页面可能包含会员专属内容",
  "evidence_refs": ["evidence-..."],
  "confidence": 0.42,
  "limitations": ["匿名状态下只看到内容入口"],
  "promotion_status": "unverified"
}
```

Observation 表示确实观察到信号，但证据不足以形成事实。它必须包含证据、置信度和限制原因。

### 8.5 Inference

Sprint 2 实现以下约束，但默认输出：

```json
{
  "inferences": []
}
```

未来推断必须包含：

- `conclusion`
- `evidence_refs`
- `confidence`
- `producer`
- `method`
- `created_at`

### 8.6 KnowledgeGap

```json
{
  "gap_id": "gap-...",
  "subject_ref": "page-...",
  "aspect": "permission.data_scope",
  "reason_code": "identity_not_available",
  "reason": "本次探索未使用受控会员身份",
  "evidence_refs": [],
  "verification": "使用获授权的测试身份进行对比探索"
}
```

`reason_code` 至少支持：

- `not_observed`
- `insufficient_evidence`
- `snapshot_version_limited`
- `authentication_required`
- `identity_not_available`
- `permission_denied`
- `anti_automation_blocked`
- `collection_truncated`
- `unsupported_in_current_sprint`

没有证据引用的知识缺口必须由明确的输入状态或范围规则产生，不能由自由文本猜测产生。

## 9. 探索、内容与访问状态

ExplorationRun 分别记录：

- `collection_status`：`completed | partial | failed`
- `content_status`：`expected | unexpected | insufficient_evidence`
- `access_status`：
  - `public`
  - `authentication_required`
  - `authentication_in_progress`
  - `authenticated`
  - `permission_denied`
  - `anti_automation_blocked`
  - `rate_limited`
  - `unknown`
- `exploration_status`：
  - `created`
  - `collecting`
  - `paused_for_human`
  - `verifying_authentication`
  - `completed`
  - `partial`
  - `failed`
  - `cancelled`
- `identity_context`
- 开始、完成时间
- 原始快照引用

Sprint 2 只能依据当前快照填写可证明的状态。Snapshot 1.0/1.1 当前没有人机登录运行时事件时，不得伪造 `authenticated` 或人工介入记录。页面仅出现“登录”链接不能证明需要登录。

## 10. 确定性与跨快照边界

业务 ID 使用规范化输入生成：

- Entity ID：实体类型、`snapshot_id`、来源 JSON Pointer。
- Evidence ID：快照摘要、JSON Pointer、证据类型。
- Fact ID：主体、谓词、值或对象引用、证据引用。
- Locator ID：元素、策略、规范化参数。
- Gap/Observation ID：主体、类别、原因和证据。
- Package ID：Application、`snapshot_id` 和快照摘要。

相同应用清单和相同快照重复转换时，输出应字节级一致。生成时间取源快照时间，不把当前系统时间写入业务输出。

跨快照不保证实体 ID 相同。`match_hints` 只是后续匹配证据，不是实体等同性结论。跨版本匹配和 Change History 留给 V1.1 Diff。

## 11. 受控谓词

初始谓词命名空间至少覆盖：

- `application.*`
- `page.*`
- `frame.*`
- `element.*`
- `locator.*`
- `exploration.*`
- `identity.*`
- `access.*`

谓词清单必须由代码枚举或受控注册表定义并测试。Builder 不接受输入文件提供任意谓词，不把自然语言文本当作结构字段名。

## 12. 默认预算

- 证据摘要：500 字符。
- 每个 Element 定位候选：12 个。
- Fact：150,000 条。
- Observation：1,000 条。
- KnowledgeGap：1,000 条。
- 最终 JSON：50 MB。

所有预算记录限制、实际用量和停止原因。达到预算时：

- 知识包状态为 `partial`。
- 保留已经生成且完整校验的记录。
- 创建 `collection_truncated` 知识缺口。
- 按确定顺序截断。
- 不把结果描述为完整知识包。

普通知识缺口不必然导致 `partial`。只有源快照不完整、转换预算耗尽或关键映射失败才导致部分状态。

## 13. 脱敏与安全

- 复用并扩展 Sprint 1 脱敏规则。
- 证据摘要、URL、定位参数、错误信息进入模型前完成脱敏。
- CSS/XPath 不得包含密码、Token、账号值或未授权属性。
- 不读取输入框当前值。
- 不保存完整 HTML、网络正文、Cookie、Storage State 或登录状态。
- SHA-256 只用于来源完整性验证，不替代脱敏。
- 输出目录默认进入 Git 忽略规则。
- 模型使用 `extra="forbid"`，阻止未设计字段静默进入持久化结果。

## 14. CLI 与 Python API

未来命令形式：

```powershell
ai-ui-knowledge `
  --manifest .\application-manifest.json `
  --snapshot .\snapshot.json `
  --output .\knowledge-output
```

CLI 只处理参数、调用 Builder 和稳定退出码。未来 Worker 直接调用 Python Builder API，不启动 CLI 子进程。

输出：

```text
knowledge-output/
`-- knowledge-package.json
```

Writer 在同目录创建临时文件，完成模型与 Schema 校验后原子替换目标文件。失败时不得留下半成品。

## 15. 状态与退出码

知识包状态：

- `completed`：转换完成，未因源快照、预算或关键映射失败而截断。
- `partial`：知识包有效，但源快照或转换过程存在截断。
- 无法形成有效知识包：不写文件。

CLI：

- `0`：有效且完整。
- `1`：配置、输入、Schema、写入或不可恢复转换失败。
- `2`：生成有效但部分完整的知识包。
- 参数错误使用 CLI 框架的独立退出码。

错误信息必须脱敏，不输出应用清单中的潜在敏感误配值或完整页面内容。

## 16. 测试策略

### 16.1 模型与 Schema

- 禁止额外字段。
- Fact 的 `value/object_ref` 互斥。
- Observation、Inference 和 KnowledgeGap 的证据与置信度约束。
- 采集、内容和访问状态相互独立。
- Pydantic Schema 与提交的 JSON Schema 完全一致。

### 16.2 Application Manifest

- 合法 origin。
- 拒绝 origin 中的路径、查询参数、用户信息和凭据。
- 拒绝不安全后缀匹配和默认 HTTPS 降级。
- 请求 URL 必须属于允许 origin。
- 认证 origin 不能被当作目标页面事实。

### 16.3 映射与证据

- Snapshot 1.0 和 1.1 兼容。
- 每条 Fact 的 Evidence 引用存在。
- JSON Pointer 可解析到原快照。
- SHA-256 使用规范化快照 JSON。
- 相同输入生成相同 ID 和字节级输出。
- Snapshot 1.0 不生成无证据 CSS/XPath。

### 16.4 定位器

本地真实 Chromium 测试覆盖：

- role、label、text、placeholder、alt、title、test id、id 和 name。
- 唯一和重复候选的匹配计数。
- 同源和跨源 iframe 的 Frame 作用域。
- 有界 CSS/XPath 生成及唯一性验证。
- 动态 class、长 DOM 链和敏感属性不进入可靠候选。
- 坐标保留为低稳定性、不推荐候选。
- Shadow DOM 下 XPath 限制。

### 16.5 预算与写入

- 每类预算耗尽时稳定截断。
- `partial`、停止原因、用量和知识缺口一致。
- 原子写入失败不留下半成品。
- 超过 JSON 体积预算时按确定顺序收缩。

### 16.6 安全

- 证据摘要和定位表达式不泄露测试密码、Token、Cookie、认证头或输入值。
- 不生成 HTML、网络正文或登录状态文件。
- 错误消息经过脱敏。
- 输出目录被版本控制忽略。

### 16.7 CLI

- 完整成功返回 0。
- 不可恢复失败返回 1 且无输出。
- 部分成功返回 2 且输出通过 Schema。
- 参数错误提供明确、非敏感提示。

## 17. 人工验收

1. 使用本地受控站点生成 Snapshot 1.1。
2. 使用应用清单生成知识包。
3. 检查 Application、Page、Frame、Element、Fact 和 Evidence。
4. 通过 JSON Pointer 将事实追溯到原快照。
5. 检查一个元素的多个候选定位器、排序和可靠性说明。
6. 确认未获得的权限、Workflow 等位于知识缺口，不是虚假实体。
7. 重复运行并确认输出文件字节级一致。
8. 使用 Snapshot 1.0 验证兼容转换和 `snapshot_version_limited` 缺口。
9. 使用受限预算验证 `partial` 和退出码 2。
10. 扫描输出，确认不存在测试密码、Token、Cookie 或输入值。

## 18. 完成标准

Sprint 2 只有同时满足以下条件才可完成：

1. Snapshot 1.1 定位扩展通过模型、Schema、单元和真实浏览器测试。
2. Snapshot 1.0 继续被 Knowledge Builder 正确读取。
3. 应用清单、知识包模型及提交 Schema 完整。
4. 一份快照稳定生成一份独立知识包。
5. 所有 Fact 均可追溯到 Evidence。
6. Observation 与 KnowledgeGap 不被包装成 Fact。
7. `inferences` 默认为空。
8. 定位候选包含 Frame 范围、唯一性、稳定性、排序、证据和限制。
9. 相同输入产生字节级一致输出。
10. 完整、部分和失败退出码符合约定。
11. 所有新增和现有质量检查通过。
12. Git 中不存在真实探索输出、浏览器状态或敏感数据。

## 19. 已知风险

- Snapshot 1.1 扩展会增加 Sprint 2 前置工作量，但没有采集期证据就无法可靠补充 CSS/XPath。
- CSS/XPath 即使当前唯一，也可能随 DOM 改版失效，不能与高稳定定位器等价。
- 坐标对 viewport、滚动和响应式布局高度敏感，只能作为诊断线索。
- 应用清单配置错误可能把不同系统错误归并，必须严格校验和评审。
- 低可靠观察的自动分类范围必须保守，否则会形成隐性推断。
- 一个不可变知识包不解决跨快照合并；这属于 V1.1 Diff。
- 50 MB 上限和其他默认预算需要通过真实企业页面验收，当前是设计基线而非已验证容量结论。

## 20. 参考

- Playwright Locators：https://playwright.dev/docs/locators
- Playwright Best Practices：https://playwright.dev/docs/best-practices
- 人机协同登录设计：`docs/superpowers/specs/2026-07-30-human-assisted-authentication-design.md`
- Sprint 1 结构化页面快照设计：`docs/superpowers/specs/2026-07-29-structured-page-snapshot-design.md`

