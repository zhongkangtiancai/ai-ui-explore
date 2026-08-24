# Sprint 6 权限比较本地用户验收

## 验收范围

本手册验证多身份下的**UI 可见性观察**：人工登录协同、串行执行、可见性差异、保守的 `partial` / `inconclusive`、取消、安全导出，以及服务重启后的终态查询。

它不验证业务授权、后端数据权限、真实外站、SSO、扫码、MFA 或访问控制绕过。请只使用本手册提供的本地虚构站点；不要输入生产账号、客户数据、密码、Token、Cookie 或连接串。

## 前置条件

- 已按 README 完成依赖与项目本地 Chromium 的准备；
- PostgreSQL 测试库已配置，且当前 PowerShell 已有 `AI_UI_EXPLORER_TEST_DATABASE_URL`；
- 当前目录为工作树根目录：`D:\codexWS\codx-ai-ui-explorer\.worktrees\human-login-runtime`；
- 数据库环境变量的值属于敏感信息，不要输出、截图或粘贴到聊天中。

## 启动

打开三个 PowerShell 窗口。

### 窗口 1：本地虚构角色站

```powershell
Set-Location 'D:\codexWS\codx-ai-ui-explorer\.worktrees\human-login-runtime'
& '..\..\.venv\Scripts\python.exe' scripts\run_permission_acceptance_site.py
```

预期：仅输出 `http://127.0.0.1:9100`。该脚本没有公网绑定、账号或密码参数；按 `Ctrl+C` 可以安全停止。

### 窗口 2：后端

```powershell
Set-Location 'D:\codexWS\codx-ai-ui-explorer\.worktrees\human-login-runtime'
$env:AI_UI_EXPLORER_DATABASE_URL = $env:AI_UI_EXPLORER_TEST_DATABASE_URL
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\codexWS\codx-ai-ui-explorer\.playwright-browsers'
$env:PYTHONPATH = "$PWD\backend\src"
& '..\..\.venv\Scripts\python.exe' -m uvicorn ai_ui_explorer.main:create_app --factory --host 127.0.0.1 --port 8000
```

预期：后端监听 `127.0.0.1:8000`。不要显示或记录上述数据库环境变量的值。

### 窗口 3：前端

```powershell
Set-Location 'D:\codexWS\codx-ai-ui-explorer\.worktrees\human-login-runtime\frontend'
pnpm dev --host 127.0.0.1 --port 5173
```

打开 `http://127.0.0.1:5173`，确认页面显示“服务正常”，然后切换到“权限比较”。

## 通用比较配置

在权限比较表单填写：

| 字段 | 值 |
| --- | --- |
| 模块标识 | `dashboard` |
| 模块地址 | `http://127.0.0.1:9100/dashboard.html` |
| 允许来源 | `http://127.0.0.1:9100` |
| 需要人工登录 | 勾选 |
| 仅本地验收：允许 HTTP | 勾选 |
| 认证 Origin | `http://127.0.0.1:9100` |
| 认证 URL | `http://127.0.0.1:9100/login.html` |
| 登录后 URL 前缀 | `http://127.0.0.1:9100/dashboard.html` |
| 认证检查点 | `#signed-in-marker` |

身份别名使用下文各案例指定的非敏感展示文本。当前比较表单使用内置预算 `max_pages=20`、`max_depth=2`、`max_queue_size=100`；本地站点内容很小，预算不会扩大到外部站点。

当身份状态显示 `paused_for_human` 时，会出现本地 Chromium 窗口。只点击对应案例指定的虚构角色按钮，然后回到 AI UI Explorer 点击“确认已完成登录”。不要在浏览器中输入任何数据。

## AC-01：管理员与普通用户的可见性差异

1. 身份别名填写“管理员”和“普通用户”，创建比较。
2. 第一个浏览器暂停后点击 `Admin`，回到页面确认登录。
3. 验证第二个身份只在第一个身份结束后才进入 `paused_for_human`。
4. 第二个浏览器暂停后点击 `Member`，回到页面确认登录。
5. 等待终态，查看差异。

预期：比较状态为 `completed`；管理员专属的 `/admin.html` 显示为高可靠性 UI 可见性差异。该结果仅说明本地虚构站的 UI 观察结果，不说明任何业务权限。

## AC-02：受限身份必须保持不确定

1. 身份别名填写“管理员”和“受限用户”，创建比较。
2. 第一个身份点击 `Admin` 并确认登录。
3. 第二个身份点击 `Restricted` 并确认登录。
4. 等待终态，勾选“显示低可靠性与无法确认的差异”。

预期：比较状态为 `partial`；受限角色会进入本地受控失败页，所有差异为 `inconclusive` 并显示“无法确认”。页面不得把结果写成“无权限”、业务授权失败或后端数据范围结论。

## AC-03：取消阻止后续身份

1. 使用任意两个身份创建比较。
2. 第一个身份进入 `paused_for_human` 后，点击“取消比较”。
3. 等待页面状态稳定。

预期：比较状态为 `cancelled`；第二个身份不启动，确认登录按钮不再可用，当前 Chromium 窗口关闭。

## AC-04：安全导出

1. 在 AC-01 或 AC-02 的终态结果中点击“下载 JSON”。
2. 使用文本编辑器搜索：`password`、`token`、`cookie`、`storage_state`、`<html`、`fixture_role`。

预期：下载的是 JSON 附件，包含受限、脱敏的页面/元素证据与差异；不含上述敏感字段、原始 HTML、浏览器对象或登录状态。

## 服务重启后的终态查询

1. 记录已终态比较显示的 `comparison_id`。
2. 在后端窗口按 `Ctrl+C`，再用同一窗口的后端命令启动服务。
3. 当前前端尚未提供历史结果列表；可在浏览器访问：

```text
http://127.0.0.1:8000/api/v1/permission-comparisons/<comparison_id>
```

预期：已持久化、脱敏的终态视图可查询。运行中的浏览器比较会被安全标记为不可恢复；Cookie、Token 和登录态绝不会恢复。

## 记录与清理

每个案例只记录日期、应用提交、虚构身份组合、`comparison_id`、终态、可靠性、导出检查结果和结论。不要把下载 JSON、浏览器截图、Cookie 或任何环境变量值提交到版本库。

验收结束后依次停止前端、后端和本地验收站。关闭浏览器 Context、停止站点或重启进程后，虚构角色状态都会消失。
