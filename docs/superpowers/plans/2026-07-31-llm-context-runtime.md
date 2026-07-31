# Sprint 3：LLM 与上下文运行时实施计划

## 实施策略

采用测试先行、离线优先、最小运行时闭环。默认只使用 Mock Provider 和 `httpx.MockTransport`，不访问真实模型。

## 任务

1. Provider 契约测试
   - 覆盖 Mock Provider 确定性输出。
   - 覆盖 OpenAI-compatible 非流式请求格式。
   - 覆盖 Provider usage 映射和安全错误面。
   - 覆盖 Base URL 安全校验。

2. Context Manager 契约测试
   - 覆盖 Context Envelope 基本字段。
   - 覆盖按完整记录裁剪。
   - 覆盖 Evidence 引用闭包。
   - 覆盖缓存隔离与 cache hit 标记。

3. 最小实现
   - 新增 `ai_ui_explorer.llm` 包。
   - 新增 LLM 请求、响应、usage 和上下文模型。
   - 新增保守 Token 估算。
   - 新增 `LLMProvider` Protocol、`MockProvider`、`OpenAICompatibleProvider`。
   - 新增 `ContextManager` 和 `LLMRuntime`。

4. 文档同步
   - 新增 Sprint 3 设计文档。
   - 更新架构、上下文工程和路线图。
   - 明确 Sprint 3 已实现能力与未实现能力。

5. 验证
   - 运行新增 Sprint 3 测试。
   - 运行后端完整测试。
   - 运行 Ruff。
   - 运行 mypy。

## 风险与控制

- 真实 Provider 调用可能产生费用和数据出域风险：Sprint 3 默认不做真实调用。
- Token 估算不是精确分词：字段名称明确使用 `estimated_*`。
- 进程内缓存不是分布式缓存：仅作为后续 Redis/持久缓存前的接口验证。
- LLM 输出不具备确定性：本阶段不写入确定性知识包。

## 本阶段完成标准

- 后端新增 LLM/Context Runtime 基础设施。
- 所有默认测试可离线运行。
- 不提交真实密钥、Cookie、Token、截图、网络正文或探索产物。
- `KnowledgePackage 1.0` 的 `inferences=[]` 约束保持不变。
