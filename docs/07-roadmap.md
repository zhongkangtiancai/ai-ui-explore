# 研发路线

## Sprint 0：工程初始化

前后端可运行骨架、项目文档、质量检查、锁文件和健康检查闭环。

## Sprint 1：结构化页面快照（已完成）

已实现 Playwright 单 URL 被动采集，覆盖页面、Frame、DOM/可访问性摘要、可交互元素
和有边界滚动，输出经过脱敏、模型与 Schema 校验的有边界 JSON 快照；不调用 LLM。

本阶段完成的是结构化快照采集闭环，不是完整应用探索。登录、业务动作、多页面导航、
权限差异、截图和网络正文均不在 Sprint 1 范围。

## Sprint 2：Application Knowledge Model（已完成）

已实现 Application Manifest、Snapshot 1.0/1.1 适配、Page/Frame/Element 实体、
定位候选、Evidence、observed Fact、Observation、KnowledgeGap、确定性 Builder、
原子 Writer、Schema 和 `ai-ui-knowledge` CLI。

Sprint 2 不生成推断，`inferences` 固定为空。数据库、LLM、测试案例生成、自动化代码
生成和人机协同登录运行时不属于本阶段。端到端测试覆盖本地 Snapshot 1.1 到知识包、
确定性重复输出、部分结果、Schema、证据指针和敏感 Fixture 值扫描。

## Sprint 3：LLM 与上下文（已完成基础设施）

已实现 Provider 抽象、Mock Provider、OpenAI-compatible 非流式适配器、保守 Token 预算、
按完整记录裁剪、Evidence 引用闭包、进程内缓存、调用审计字段和薄 Runtime。

Sprint 3 不生成或持久化业务推断，不修改 `knowledge-package-v1` 的 `inferences=[]` 约束，
不实现 Agent、Tool Calling、流式响应、多模型回退、数据库、Redis、向量检索或前端业务页面。

## Sprint 4：受控探索（已完成当前范围）

已实现前三个基础切片：URL/Origin 风险门禁、只读动作门禁、任务状态机、最小审计事件、
页面状态指纹、去重基础、指定模块入口配置、有界探索队列模型和可注入 Collector Port 的
有界 Runner 编排，并提供复用 Sprint 1 `SnapshotCollector` 的适配器。Snapshot 1.1
已保存脱敏后的 anchor `href` 导航元数据，并可从快照提取去重后的只读链接导航候选；
Runner 已默认接入该提取器，并在重复页面状态上停止继续展开。

已完成本地 HTTP fixture 的真实 Chromium 两页端到端验收，并修正 `max_pages` 在已访问入口页后
重复计数的问题；`/` 与 `/index.html` 保持为不同页面，除非未来有经证据验证的应用级别别名规则。

第四切片已实现后端人机协同登录运行时：使用进程内存态的可见 Browser Context，要求人工显式
确认，并按配置的登录后 URL 前缀和 CSS 检查点验证；验证成功后可复用同一 Context，通过现有
Runner 恢复受控只读探索。该切片已使用本地 HTTP 模拟登录站点和真实 Chromium 完成端到端验收。

尚未实现：跨任务登录态复用、加密登录态存储、SSO/扫码/MFA 专用适配、真实外部站点登录和
访问控制绕过。当前本地验收不能外推为这些能力已经可用。

## Sprint 5：最小任务管理（已完成）

已实现单进程内存任务注册表、后台线程编排、创建/查询/审计/人工确认/取消/结果摘要 API 和
最小 Vue 管理页。任务与登录态均只在当前进程内；重启不恢复，进程崩溃或强制终止时不保证 finally
清理。API、前端和结果摘要只暴露脱敏白名单字段；结果仅保留页面、元素和链接的标量计数。

已在本地 HTTP 模拟登录站点和真实 Chromium 上完成 API 端到端验收：创建登录任务、暂停、测试私有
辅助模拟人工登录、确认恢复探索、完成、读取脱敏摘要、拒绝终态后续操作并关闭 Browser Context。

数据库、Redis、独立 Worker、跨进程恢复、加密登录态存储、真实外站验收、截图、网络正文、LLM
推断、后端数据权限验证和测试代码生成不在本 Sprint 范围。

## Sprint 6：权限感知（已完成当前范围）

已实现 2–5 个身份的进程内串行 UI 可见性比较、人工登录确认、脱敏页面/元素证据、保守页面与
链接差异比较、安全 API/JSON 导出和 Vue 视图。任一身份认证未验证、采集失败或被截断时，结果
只会显示“无法确认”，不会宣称权限授予或拒绝。已使用本地虚构角色 HTTP 站点和真实 Chromium
验证管理员专有页面、受限身份导致的不确定差异以及 Context 终态关闭。

本 Sprint 不包含真实外站登录、访问控制绕过、后端数据权限或业务授权验证、跨进程恢复、数据库、
Worker、截图、网络正文、LLM 推断、测试案例生成或自动化代码生成。

## Sprint 7：探索结果明细与证据浏览（已完成）

- 单任务的进程内脱敏页面、Frame、元素、边界和定位器候选投影。
- 只读页面列表、详情和 Schema 校验的 JSON 下载；Vue 明细浏览不渲染原始 HTML。
- 任务内 `page-N` 用于详情定位，脱敏 URL 仅展示；`partial` 明确表示采集不完整。
- 已通过本地虚构登录站点的真实 Chromium API 验收；不代表真实外站登录、业务权限或持久化能力。

## V1.1

实现周期巡检、增量探索、版本时间线和变化报告。
