# AI UI Explorer 工作区规则

## 必读顺序

开始任何开发前，依次阅读：

1. `CODING_RULES.md`
2. `docs/00-project-context.md`
3. 与当前任务直接相关的设计文档

## 当前实现状态

当前仓库包含可运行的前后端工程骨架，以及 Sprint 1 的 Playwright 单 URL 结构化页面
快照：通过 CLI 执行有预算、被动、脱敏的页面、Frame、元素和滚动采集，并输出版本化
JSON 与 Schema。Snapshot 1.1 包含分层定位器候选，同时兼容读取 Snapshot 1.0。

Sprint 2 已实现从版本化 Application Manifest 与 Snapshot 1.0/1.1 生成确定性、可追溯、
经 Schema 校验的 `knowledge-package.json`。当前知识只包含有证据的 observed Fact；
`knowledge-package-v1` 的 `inferences` 仍固定为空。

Sprint 3 已实现 LLM 与上下文基础设施：异步 Provider 抽象、确定性 Mock Provider、
OpenAI-compatible 非流式 Chat Completions 适配器、保守 Token 估算、按完整知识记录裁剪的
Context Manager、Evidence 引用闭包、有界进程内缓存、脱敏调用审计字段和薄 Runtime。

Sprint 4 已实现第一切片：URL/Origin 风险门禁、只读动作门禁、任务状态机、最小审计事件、
页面状态指纹和状态去重基础。该切片不启动浏览器，不执行多页面探索，也不实现人工登录
运行时。

上述能力仍不等于完整应用探索。PostgreSQL、Redis、真实模型验收、Agent、推断生成、
人机协同登录运行时、业务动作、多页面导航运行时、多身份权限探索、测试案例与自动化代码生成、
周期巡检与增量 Diff、截图和网络正文仍未实现。不得把设计文档中的这些后续规划描述
成已实现能力。

## 执行要求

- 文档使用简体中文；代码标识符和 API 字段使用英文。
- 新功能和缺陷修复必须先写失败测试，再实现最小代码。
- 所有秘密信息仅通过环境变量注入，不得提交真实账号、Cookie、Token 或 API Key。
- 所有未来 AI 知识必须包含 `conclusion`、`evidence`、`confidence`。
- 删除、审批、发布、支付、提交等危险动作默认拒绝；只有显式白名单或人工确认后才可执行。
- 修改实现时同步更新测试和相关设计文档。
