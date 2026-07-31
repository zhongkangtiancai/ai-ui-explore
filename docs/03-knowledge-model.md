# Application Knowledge Model

## 当前已实现边界

Sprint 2 已实现从一份经过 Schema 校验的 Snapshot 1.0/1.1 确定性生成一份独立
`knowledge-package.json`。转换只读取本地文件，不重新访问目标网站，不调用 LLM、
Agent、数据库、FastAPI 或前端。

Application 身份只来自版本化 Application Manifest。知识包保存：

- 顶层 Application 和 ExplorationRun
- Page、Frame、Element 轻量实体
- 带 Frame 作用域、唯一性、稳定性、排序和限制的 Locator Candidate
- 可通过 JSON Pointer 回溯到源 Snapshot 的 Evidence
- 受控谓词命名空间内的 observed Fact
- 证据不足但确实观察到信号的 Observation
- 明确说明缺失原因与验证方式的 KnowledgeGap
- 固定为空的 `inferences`

Module、Action、Workflow、Identity、Role、Permission、Data Scope、Change History
等仍是后续知识模型方向，当前不会虚构这些实体。

## 事实、观察与缺口

Fact 只表达 Snapshot 中可直接观察且有证据的值，必须包含：

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

`confidence=1.0` 只表示该值在本次 Snapshot 中被直接观察到，不代表跨版本稳定，也不
代表业务含义已经得到人工确认。

Observation 用于保存“确实发现，但证据不足以形成事实”的信号，包含证据、置信度和
限制原因。KnowledgeGap 用于说明未获取的信息、原因及建议验证方式。二者不会被包装成
Fact。没有受控身份和测试数据时，权限与数据范围只能进入缺口或待验证观察，不能断言
真实授权规则。

Sprint 2 不产生推断。未来推断必须独立保存 `conclusion`、`evidence_refs`、
`confidence`、`producer`、`method` 和 `created_at`，且不能覆盖观察事实。

## 证据与追溯

每条 Evidence 包含源 `snapshot_id`、Snapshot Schema 版本、规范化 Snapshot
SHA-256、JSON Pointer、证据类型和有界脱敏摘要。所有 Fact 的证据引用必须存在，且
JSON Pointer 必须能解析到原 Snapshot。

证据摘要不是原文副本。知识包不保存完整 HTML、截图、网络正文、Cookie、Token、
Storage State 或登录状态。所有字符串进入持久化模型前继续使用 Sprint 1 Redactor；
组织已知的业务敏感格式应通过受信任的自定义脱敏规则补充。默认规则降低泄漏风险，
但不能证明识别了所有业务秘密。

## 定位知识

Snapshot 1.1 在采集期生成有界定位器候选，Knowledge Builder 将其转换为正式 Evidence
引用。候选覆盖用户语义、test id、稳定属性、有界 CSS/XPath 和位置五层。

CSS/XPath 必须在当前 Frame 内验证且受长度与层级预算约束。位置候选依赖 viewport、
滚动和响应式布局，只能作为诊断线索，不能标记为推荐定位器。Snapshot 1.0 只转换已有
定位提示和边界信息，不补造 CSS/XPath，并生成 `snapshot_version_limited` 缺口。

## 确定性、预算与持久化

相同 Manifest 与相同 Snapshot 输入产生字节级一致的知识包；业务 ID 和生成时间均来自
规范化输入，不使用当前系统时间。跨 Snapshot 的实体 ID 不保证相同，`match_hints`
只是后续匹配线索，不是实体同一性结论。

Writer 在同目录写临时文件，完成 Pydantic 与提交 Schema 双重校验、flush 和 fsync 后
执行原子 no-clobber 发布。已有相同字节视为幂等成功，已有不同内容则拒绝覆盖；并发
写入不会越过检查窗口覆盖另一份知识包。

达到数量或 JSON 体积预算时，系统按确定顺序收缩，输出有效 `partial` 包、停止原因和
`collection_truncated` 缺口。无法形成有效包时不写目标文件。

目标长期存储仍规划为 PostgreSQL + JSONB + pgvector；当前没有数据库模型、迁移或向量
检索实现。
