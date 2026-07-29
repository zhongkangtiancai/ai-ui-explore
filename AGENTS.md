# AI UI Explorer 工作区规则

## 必读顺序

开始任何开发前，依次阅读：

1. `CODING_RULES.md`
2. `docs/00-project-context.md`
3. 与当前任务直接相关的设计文档

## 当前实现状态

当前仓库只包含可运行的前后端工程骨架。PostgreSQL、Redis、Playwright、
LLM、Agent、权限探索和巡检均未实现。不得把设计文档中的规划描述成已实现能力。

## 执行要求

- 文档使用简体中文；代码标识符和 API 字段使用英文。
- 新功能和缺陷修复必须先写失败测试，再实现最小代码。
- 所有秘密信息仅通过环境变量注入，不得提交真实账号、Cookie、Token 或 API Key。
- 所有未来 AI 知识必须包含 `conclusion`、`evidence`、`confidence`。
- 删除、审批、发布、支付、提交等危险动作默认拒绝；只有显式白名单或人工确认后才可执行。
- 修改实现时同步更新测试和相关设计文档。
