# 技术架构基线

## 目标架构

系统计划分为管理界面、API、任务调度、浏览器 Worker、理解与 Agent、上下文工程、
知识服务和持久化层。模块通过明确接口通信，避免浏览器、模型和存储相互耦合。

## 技术基线

- 后端：Python 3.12、FastAPI、Pydantic、SQLAlchemy（后续）
- 前端：Node.js 24、Vue 3、TypeScript、Vite、Element Plus
- 浏览器：Playwright（后续）
- 持久化：PostgreSQL、JSONB、pgvector（后续）
- 队列与缓存：Redis（后续）

## 关键边界

- Browser 层只负责可重复的采集和动作执行。
- Knowledge 层保存事实、观察、推断及其来源。
- Agent 层只通过稳定接口使用 Browser、Context 和 Knowledge。
- LLM Provider 层统一公网和内网模型差异。
- 长任务采用异步任务模型，不占用同步 HTTP 请求。

## 当前实现

当前仅有 API 健康检查和前端状态页，不包含目标架构中的业务层。
