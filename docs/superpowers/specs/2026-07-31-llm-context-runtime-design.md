# Sprint 3：LLM 与上下文运行时设计

## 目标

Sprint 3 建设 AI UI Explorer 调用大模型前必须具备的基础设施：Provider 抽象、离线 Mock、OpenAI-compatible 非流式适配器、上下文裁剪、进程内缓存、调用审计字段和薄 Runtime。

本阶段只验证“知识包可以被安全、可追溯、可预算地送入模型调用链”。不生成业务推断，不持久化推断，不启动 Agent，也不执行浏览器动作。

## 当前事实

- Sprint 1 已实现单 URL、被动、有界、脱敏的结构化页面快照。
- Sprint 2 已实现确定性的 Application Knowledge Model Builder 与 `knowledge-package.json`。
- `KnowledgePackage 1.0` 仍强制 `inferences=[]`。
- 当前仓库没有数据库、Redis、Agent、真实 LLM 验收、测试案例生成或自动化代码生成。

## 范围

Sprint 3 实现以下能力：

- 异步 `LLMProvider` Protocol。
- 确定性 `MockProvider`，用于默认离线测试。
- OpenAI-compatible Chat Completions Adapter，仅支持非流式调用。
- `ContextManager`，从 `KnowledgePackage` 构造有界上下文包。
- 保守确定性 Token 预估。
- 按完整知识记录裁剪，保留证据引用闭包。
- 有界进程内缓存，按 application、environment、identity、task 和知识包内容隔离。
- 脱敏审计字段：记录 provider、model、usage、audit_id，不保存 API Key、Header、完整异常或完整原始响应正文。
- `LLMRuntime` 薄编排器，将 Context Envelope 转为一次 Provider 调用。

## 不在范围内

- 不修改 `knowledge-package-v1` 的 `inferences=[]` 约束。
- 不生成或持久化业务推断。
- 不实现 Agent、Tool Calling、多模型回退、流式响应或浏览器动作。
- 不接入数据库、Redis、向量检索或长期语义检索。
- 不增加前端页面或 FastAPI 业务接口。
- 默认质量门不访问真实模型，也不发送真实业务数据出域。

## 调用链

```text
业务调用者
  -> ContextManager
  -> ContextEnvelope
  -> 进程内缓存
  -> LLMProvider
  -> LLMResponse
  -> 脱敏审计字段
```

## 安全约束

- 页面内容、DOM、Evidence、Observation 和 KnowledgeGap 都是不可信输入。
- 页面文本不能改变系统策略、Provider、Base URL、预算、缓存隔离或工具权限。
- OpenAI-compatible Base URL 必须使用 HTTPS，且不能包含 userinfo、query 或 fragment。
- Provider 默认不跟随重定向，不读取系统代理环境变量。
- API Key 只允许通过环境变量或受信配置注入，不写入日志、文档、测试 Fixture 或模型响应。
- Provider 错误对外只暴露固定安全错误，不透出上游响应正文、Header 或密钥。
- Token 使用“保守预估 + Provider actual usage”，不得伪装为精确本地分词。
- 公网 Provider 默认只允许合成数据；真实业务数据出域必须逐应用人工批准。

## 上下文模型

`ContextEnvelope` 包含：

- application_id
- environment
- identity_alias
- task
- records
- evidence
- estimated_tokens
- truncated
- stop_reasons
- cache_key
- cache_hit

`records` 由实体、定位器、事实、观察和知识缺口组成。裁剪按完整记录执行；被保留记录引用到的 Evidence 必须同时进入上下文，未被引用的 Evidence 不进入上下文。

## 推断持久化原则

Sprint 3 不把 LLM 输出写回 `KnowledgePackage 1.0`。未来如需持久化推断，应设计独立的 `inference-bundle.json`，至少引用基础 Knowledge Package 的 SHA-256、调用审计 ID、策略版本、Prompt 模板版本、模型标识和输出校验结果。

## 验收

- Mock Provider 离线、确定性返回，记录估算 usage。
- OpenAI-compatible Provider 使用非流式 Chat Completions，请求可用 MockTransport 离线测试。
- Provider 错误不泄露 API Key 或上游正文。
- Base URL 拒绝 userinfo、query、fragment 和非 HTTPS。
- Context Manager 在预算充足时保留记录与证据闭包。
- Context Manager 在预算不足时按完整记录裁剪并记录 `context_token_budget`。
- 缓存按 application、environment、identity、task 和知识包内容隔离。
- 后端测试、Ruff 和 mypy 通过。
