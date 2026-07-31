# AI UI Explorer 项目上下文

## 已确认事实

- 目标用户是企业内部测试团队。
- 目标系统以中文、中大型 Vue/React SPA 为主，包含 iframe 和复杂登录。
- 登录方式可能包括用户名密码、SSO 和扫码，允许人工辅助并复用登录状态。
- 系统需要支持指定模块探索和全应用探索。
- 核心输出面向人和 AI，包括页面、元素、动作、流程、权限及证据。
- 外网开发可使用 GPT 或 DeepSeek；内网使用 DeepSeek/Qwen 的
  OpenAI-compatible API。
- 最终交付需要支持企业内网离线部署。

## 产品边界

V1 是“权限感知核心版”：支持单系统、指定模块优先、多身份差异、页面/元素/
动作知识、证据、置信度和 JSON 导出。

V1.1 再实现周期巡检和增量 Diff。

测试案例生成、自动化代码生成和回归执行不是 V1 范围，它们是知识模型的后续消费者。

## 当前实现

当前已建立前后端可运行工程骨架，实现 Sprint 1 的 Playwright 单 URL 有界结构化
快照采集，并实现 Sprint 2 的确定性 Application Knowledge Model 转换闭环：从
Application Manifest 和已校验的 Snapshot 1.0/1.1 生成独立、脱敏、Schema 校验且
可追溯的 `knowledge-package.json`。Snapshot 1.1 包含分层、排序、当前 Frame 内校验的
定位器候选；Snapshot 1.0 继续兼容读取。

这些能力不是完整应用探索。截图、网络正文、登录运行时、业务动作、多页面导航、LLM、
Agent、推断生成、数据库、多身份权限探索、测试案例/自动化代码生成和巡检仍未实现；
上述 V1/V1.1 产品能力中未在本段明确列为已实现的部分均为规划。
