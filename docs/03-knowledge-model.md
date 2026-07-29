# Application Knowledge Model 基线

## 核心实体

- Application、Module、Page
- Frame、Element、Locator
- Action、Workflow、Exploration Event
- Identity、Role、Permission、Data Scope
- Evidence、Inference、Change History

## 统一推断结构

```json
{
  "conclusion": "提交按钮可能启动审批流程",
  "evidence": [
    {
      "type": "network",
      "value": "POST /workflow/start"
    }
  ],
  "confidence": 0.91
}
```

`confidence` 取值为 0 到 1。模型推测不能覆盖观察事实；人工确认、真实动作结果、
网络证据和可访问性语义需要保留独立来源。

## 权限建模原则

页面或数据差异必须关联探索身份和时间。没有受控基线时，系统只能记录观察到的差异，
不能直接断言真实授权规则。

## 存储策略

目标存储为 PostgreSQL + JSONB + pgvector，同时支持版本化 JSON 知识包导出。
当前工程初始化不创建数据库模型或迁移。
