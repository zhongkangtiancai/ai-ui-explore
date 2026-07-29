# AI UI Explorer 工程初始化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`
> to implement this plan task-by-task.

**Goal:** 建立可运行、可测试、可追溯的前后端工程骨架。

**Architecture:** FastAPI 提供版本化健康接口，Vue 状态页通过可配置 API 基地址调用该接口。
设计文档作为后续 Sprint 的事实基线，业务能力不在初始化阶段实现。

**Tech Stack:** Python 3.12、FastAPI、Vue 3、TypeScript、Vite、Element Plus、pytest、
Vitest、Ruff、mypy、ESLint、Prettier。

## Global Constraints

- 不实现数据库、Redis、Playwright、LLM、Agent 或权限探索。
- 不提交秘密信息或探索敏感产物。
- 新行为遵循测试先行。
- 完成前运行后端与前端全部质量门禁。

## Tasks

- [x] 初始化 Git、忽略规则、项目治理与设计文档。
- [x] 先写后端健康接口和非法配置测试，验证失败后实现最小代码。
- [x] 先写前端三种健康状态测试，验证失败后实现最小界面。
- [x] 增加 Windows 准备、启动和检查脚本。
- [x] 安装并锁定依赖，运行完整测试、静态检查、构建和端到端健康检查。
- [x] 创建首个基线提交。
