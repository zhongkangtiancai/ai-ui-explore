# 上下文工程基线

## 原则

全量应用知识不得直接放入单次 Prompt。Agent 只接收完成当前任务所需的页面、
相邻路径、相关证据和压缩历史。

## 目标能力

- Working、Task、Long-term 三层上下文
- Agent 独立 Token 预算
- 历史探索压缩
- 语义检索和缓存
- 调用成本、耗时与裁剪记录

## 验证要求

未来每次 LLM 调用都必须可解释其上下文来源，并对超预算行为进行可重复裁剪。
Sprint 3 已实现第一版 `ContextManager`：它从确定性 `KnowledgePackage` 构造
`ContextEnvelope`，按完整知识记录进行保守 Token 预算裁剪，并保留 Evidence 引用闭包。
当前实现使用有界进程内缓存，按 application、environment、identity、task 和知识包内容隔离。

当前未实现语义检索、历史探索压缩、跨进程缓存、数据库持久化和 Agent 运行时。Token 数量为保守估算；
真实 Provider 返回的 usage 会单独记录为 `provider_*` 字段。
