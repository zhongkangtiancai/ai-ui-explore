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

Sprint 3 已实现 LLM 与上下文基础设施：Provider 抽象、确定性 Mock、OpenAI-compatible
非流式适配器、Context Manager、保守 Token 估算、按完整知识记录裁剪、Evidence 引用
闭包、有界进程内缓存、脱敏调用审计字段和薄 Runtime。默认质量门不访问真实模型。

Sprint 4 已进入第一切片：实现受控探索的纯模型基础，包括 URL/Origin 风险门禁、只读
动作门禁、任务状态机、最小审计事件、页面状态指纹和状态去重。该切片不启动浏览器、
不执行多页面探索、不实现人工登录运行时。

这些能力不是完整应用探索。截图、网络正文、登录运行时、业务动作、多页面导航、真实
模型验收、Agent、推断生成、数据库、多身份权限探索、测试案例/自动化代码生成和巡检仍未
实现；上述 V1/V1.1 产品能力中未在本段明确列为已实现的部分均为规划。
