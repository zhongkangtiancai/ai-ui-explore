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

Sprint 4 已完成第四切片。在前三个切片中实现了受控探索的纯模型基础，包括 URL/Origin
风险门禁、只读动作门禁、任务状态机、最小审计事件、页面状态指纹、状态去重、指定模块入口配置和
有界探索队列模型、可注入 Snapshot Collector Port 的有界 Runner 编排，以及复用 Sprint 1
`SnapshotCollector` 的适配器。Snapshot 1.1 已保存经过 URL 脱敏的 anchor `href`
导航元数据，并可从页面快照确定性提取去重后的只读链接导航候选；Runner 默认接入该
提取器，并在遇到重复页面状态时停止继续展开候选。已通过本地 HTTP fixture 与真实 Chromium
完成入口页到同源链接页的端到端验收；验收同时覆盖 `max_pages` 预算边界。

第四切片实现了后端人机协同登录运行时：任务使用进程内存态的可见 Playwright Browser Context，
由人工显式确认后，按配置的登录后 URL 前缀和 CSS 检查点验证认证结果；验证成功后，Runner 可通过
经 source 身份校验、绑定同一 Context 的 Collector Port 恢复受控只读探索。Runner 绑定同一任务时，
会在 completed/partial 结果落定后同步驱动任务终态并关闭会话。该能力只通过本地 HTTP 模拟登录站点
与真实 Chromium 验收，不持久化 Cookie、Token 或浏览器存储状态，也未对真实外部登录流程做出可用性声明。

这些能力不是完整应用探索。跨任务登录态复用、加密登录态存储、SSO/扫码/MFA 专用适配、
前端人工确认页、真实外部站点登录、访问控制绕过、截图、网络正文、业务动作、通用多页面导航
运行时、真实模型验收、Agent、推断生成、数据库、多身份权限探索、测试案例/自动化代码生成和
巡检仍未实现；上述 V1/V1.1 产品能力中未在本段明确列为已实现的部分均为规划。
