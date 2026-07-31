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

## Sprint 3：LLM 与上下文

实现 Provider 抽象、Mock、Token 预算、裁剪、缓存和调用审计。

## Sprint 4：受控探索

实现导航、状态去重、风险门禁、指定模块探索和人工辅助登录。

## Sprint 5：权限感知

实现多身份探索、菜单/页面/动作差异和权限证据视图。

## V1.1

实现周期巡检、增量探索、版本时间线和变化报告。
