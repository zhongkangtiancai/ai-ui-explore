# 技术架构基线

## 目标架构

系统计划分为管理界面、API、任务调度、浏览器 Worker、理解与 Agent、上下文工程、
知识服务和持久化层。模块通过明确接口通信，避免浏览器、模型和存储相互耦合。

## 技术基线

- 后端：Python 3.12、FastAPI、Pydantic、SQLAlchemy（后续）
- 前端：Node.js 24、Vue 3、TypeScript、Vite、Element Plus
- 浏览器：Playwright（Sprint 1 已用于单 URL 被动结构化快照）
- 持久化：PostgreSQL、JSONB、pgvector（后续）
- 队列与缓存：Redis（后续）

## 关键边界

- Browser 层只负责可重复的采集和动作执行。
- Knowledge 层保存事实、观察、推断及其来源。
- Agent 层只通过稳定接口使用 Browser、Context 和 Knowledge。
- LLM Provider 层统一公网和内网模型差异。
- 长任务采用异步任务模型，不占用同步 HTTP 请求。

## 当前实现

当前已包含：

- FastAPI 健康检查和 Vue 前端状态页。
- Sprint 1 的单 URL、被动、有界、脱敏结构化页面快照 CLI。
- Sprint 2 的确定性 Application Knowledge Model Builder、Schema、Writer 和 CLI。
- Sprint 3 的 LLM Provider 抽象、Mock Provider、OpenAI-compatible 非流式适配器、Context Manager、保守 Token 估算、进程内缓存和薄 Runtime。
- Sprint 4 前三切片的 URL/Origin 风险门禁、只读动作门禁、任务状态机、最小审计事件、页面状态指纹、去重基础、指定模块入口配置、有界探索队列模型、可注入 Collector Port 的有界 Runner 编排、`SnapshotCollector` 适配器、Snapshot 1.1 脱敏 `href` 导航元数据，从快照提取去重链接导航候选的纯函数，以及 Runner 对默认候选提取和重复状态停止展开的接入；本地 HTTP fixture 已通过真实 Chromium 的两页受控端到端验收。
- Sprint 4 第四切片的后端人机协同登录运行时：每个任务使用单一、进程内存态、可见的 Playwright Browser Context；人工显式确认后，以配置的登录后 URL 前缀和 CSS 检查点认证，再由具体会话 Collector 通过模块私有的精确类型及 source/session/task 对象身份校验绑定同一 Context，恢复 Runner 的受控只读探索；Collector Port 不公开可由包装器伪造的绑定能力。Runner 可选绑定同一个任务，拒绝 task/collector 错绑，并在 completed/partial 或未处理异常对应的 failed 终态同步关闭会话。终态回调隔离各自的清理异常并继续执行，且 Runner 原始异常保持不变后继续向调用方传播。该清理保证仅覆盖进程内 finally 可执行路径。本地 HTTP 模拟登录站点已通过真实 Chromium 端到端验收。
- Sprint 5 的最小任务管理产品层：加锁的单进程内存注册表将私有任务、后台线程和浏览器运行时与可序列化的脱敏摘要隔离；后台线程运行既有受控 Runner；FastAPI 暴露创建、详情、审计、人工确认、取消和结果摘要。摘要只从 Runner visit 的页面、元素和链接标量计数累积，不持有 Snapshot、元素内容或浏览器对象；Vue 页面轮询并展示安全状态。人工登录的 Playwright sync Context 只在其所属后台线程使用，API 确认仅发送受控信号；终态会关闭 Context。服务重启不会恢复任务、结果或登录态，进程崩溃或强制终止时不保证 finally 清理。

该任务管理层与登录运行时均不持久化浏览器状态，且不等于通用登录或生产级任务系统。仍未实现：
数据库、Redis、独立 Worker、跨进程任务恢复、跨任务登录态复用、加密登录态存储、SSO/扫码/MFA
专用适配、真实外部站点登录、访问控制绕过、截图、网络正文、LLM 推断、多身份权限差异、巡检、
测试案例生成和 Playwright 自动化代码生成。
