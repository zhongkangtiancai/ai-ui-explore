# AI UI Explorer

AI UI Explorer 是面向企业 Web 应用的智能探索与知识建模平台。它计划通过
Playwright 采集 DOM、Accessibility、页面文本、操作轨迹和网络证据，并借助
LLM 生成可追溯的应用知识。

## 当前状态

当前仅实现工程初始化骨架：

- FastAPI 后端健康接口
- Vue 3 前端服务状态页
- 项目治理、测试和质量检查基线

尚未实现 Playwright、数据库、Redis、LLM、Agent、权限探索和周期巡检。

## 本地运行

首次准备：

```powershell
.\scripts\bootstrap.cmd
```

分别启动后端和前端：

```powershell
.\scripts\dev-backend.cmd
.\scripts\dev-frontend.cmd
```

访问 `http://localhost:5173`。后端健康接口为
`http://localhost:8000/api/v1/health`。

## 质量检查

```powershell
.\scripts\check.cmd
```

这些 `.cmd` 入口只为当前进程调用 PowerShell 脚本，不修改 Windows 的用户级或系统级
执行策略。

## 文档

项目事实基线从 [项目上下文](docs/00-project-context.md) 开始阅读。研发路线见
[研发路线](docs/07-roadmap.md)。
