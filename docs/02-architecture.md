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
- Sprint 4 前三切片的 URL/Origin 风险门禁、只读动作门禁、任务状态机、最小审计事件、页面状态指纹、去重基础、指定模块入口配置、有界探索队列模型、可注入 Collector Port 的有界 Runner 编排和 `SnapshotCollector` 适配器。

仍未实现：数据库、Redis、Agent、多页面受控探索运行时、人机协同登录运行时、多身份权限差异、巡检、测试案例生成和 Playwright 自动化代码生成。
