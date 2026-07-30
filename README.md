# AI UI Explorer

AI UI Explorer 是面向企业 Web 应用的智能探索与知识建模平台。它计划通过
Playwright 采集 DOM、Accessibility、页面文本、操作轨迹和网络证据，并借助
LLM 生成可追溯的应用知识。

## 当前状态

仓库当前包含：

- FastAPI 后端健康接口
- Vue 3 前端服务状态页
- 项目治理、测试和质量检查基线
- Sprint 1 的单 URL、有预算、被动、脱敏结构化页面快照 CLI

结构化快照会采集页面、Frame、可见文本摘要、可交互元素及滚动结果，并输出经过
Schema 校验的 JSON。它不是完整应用探索，不会调用 LLM。数据库、Redis、Agent、
权限探索和周期巡检仍未实现。

## 本地运行

首次准备：

```powershell
.\scripts\bootstrap.cmd
```

该命令先按 `backend\requirements.lock` 在项目自己的 `.venv` 精确安装 Python
应用与测试运行依赖，再以 `--no-deps` 安装 editable 后端包，避免重新解析运行依赖；
前端按锁文件安装到 `frontend\node_modules`。pip 自身以及 editable 构建隔离可能使用
的 setuptools/wheel 属于 bootstrap/build 工具链，不属于应用或测试运行依赖锁定
范围。

bootstrap 还会将匹配当前 Playwright 版本的 Chromium 安装到项目自己的
`.playwright-browsers`，不会执行全局安装。Chromium 及其运行组件会额外占用数百 MB
磁盘空间，实际大小随 Playwright 版本和 Windows 平台变化；当前验证环境约为
688 MB。`.playwright-browsers`、`.venv`、前端依赖和 pnpm store 均不进入 Git。

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

## 采集结构化页面快照

完整参数示例：

```powershell
.\.venv\Scripts\ai-ui-snapshot.exe `
  --url http://127.0.0.1:9000 `
  --output .\exploration-output\sample `
  --timeout-ms 60000 `
  --max-frames 50 `
  --max-scroll-containers-per-frame 20 `
  --max-scroll-rounds-per-container 30 `
  --max-elements 5000 `
  --max-text-chars 500 `
  --max-json-bytes 10485760
```

默认使用无界面 Chromium。仅在本地诊断时可追加 `--headed` 显示浏览器窗口。输出文件
固定为 `<output>\snapshot.json`。

退出码约定：

- `0`：生成完整快照，没有局部错误或截断。
- `1`：无法生成有效快照。
- `2`（部分采集）：已生成可用的 `<output>\snapshot.json`，但存在局部失败或达到
  预算后的截断。
- `2`（参数用法错误）：参数缺失、非数字或超出允许范围；不会生成
  `<output>\snapshot.json`。

默认预算为总采集时间 60 秒、最多 50 个 Frame、每个 Frame 最多 20 个滚动容器、
每个容器最多 30 轮滚动、最多 5,000 个元素、每段文本最多 500 字符、JSON 最大
10 MB。预算是资源上限，不是“页面已探索完整”的证明。处理未知或不可信页面时，
建议先收紧预算，例如：

```powershell
.\.venv\Scripts\ai-ui-snapshot.exe `
  --url http://127.0.0.1:9000 `
  --output .\exploration-output\bounded-sample `
  --timeout-ms 15000 `
  --max-frames 10 `
  --max-scroll-containers-per-frame 5 `
  --max-scroll-rounds-per-container 5 `
  --max-elements 500 `
  --max-text-chars 200 `
  --max-json-bytes 1048576
```

达到 Frame、滚动容器、滚动轮次、元素或文本预算时，对应 Frame 和最终文档会记录为
`partial`、`truncated=true`，并保留 `max_frames`、`max_scroll_containers`、
`round_limit`、`max_elements` 或 `max_text_chars` 等停止原因。脱敏命中的类别会以
排序、去重后的 `redaction_categories` 写入 Frame 和全局统计；原值不会进入这些审计
字段。

### 程序化自定义脱敏规则

自定义规则只通过受信任的程序配置注入，不提供 CLI 秘密参数：

```python
from ai_ui_explorer.snapshot.redaction import CustomRedactionRule, Redactor

redactor = Redactor(
    custom_rules=[
        CustomRedactionRule(
            name="case-reference",
            category="CASE_REFERENCE",
            pattern=r"\bCASE-\d{4}\b",
        )
    ]
)
```

配置只包含规则名称、类别和结构化正则表达式，不需要也不得包含真实秘密值。最多配置
32 条规则；单条 pattern 最长 512 个字符；名称和类别必须是最多 64 个字符的安全
标识符；内建规则名、内建类别、重复名称、非法表达式和可匹配空字符串的表达式会被
拒绝。替换结果固定为 `[REDACTED:<CATEGORY>]`，不能配置 replacement 模板重新插入
原匹配值。

自定义正则属于受信任的管理员配置。当前实现使用 Python 正则引擎，没有对最坏情况
运行时间提供强制上限；配置者必须审查并避免灾难性回溯模式，再在虚构数据上验证。

### 数据安全边界

- Sprint 1 不支持截图、HAR/trace、请求或响应正文、登录、SSO、扫码、MFA、Cookie、
  Token 或 storage state 持久化，也不执行点击、输入、提交、“加载更多”等业务动作。
- 脱敏只能降低常见敏感信息泄露风险，不能保证识别全部业务敏感数据。快照仍可能包含
  页面名称、业务字段、可访问文本和 URL 等敏感信息。
- 自定义脱敏正则仅允许受信任的管理员配置，不能把用户输入或真实秘密拼成规则。
- 默认输出目录 `exploration-output/` 已被 Git 排除。使用其他输出目录时，操作者必须
  自行确保不提交快照，并按组织的数据分级、访问控制和保留制度及时归档或删除。
- 不要在 `--url` 或其他命令参数中放入密码、Token、Cookie 或其他秘密，避免进入命令
  历史和进程列表。

### 已知限制

- 无限滚动只会运行到稳定条件或预算上限；达到上限时结果为截断，不代表已发现全部内容。
- 虚拟列表通常只暴露当前渲染窗口，已离开 DOM 的项目可能不会出现在同一次快照中。
- `canvas` 内部绘制内容没有可采集的 DOM/可访问节点时，无法还原其中的文字和控件。
- sandboxed frame、动态卸载 Frame 或浏览器安全策略可能导致局部失败；其他可访问
  Frame 会尽量保留。
- 动态内容、定时更新、动画和异步懒加载会使重复采集的运行字段或业务内容发生变化。
- 本功能不导航到其他页面，不展开折叠区域，也不推断业务流程、权限或页面语义。

## 文档

项目事实基线从 [项目上下文](docs/00-project-context.md) 开始阅读。研发路线见
[研发路线](docs/07-roadmap.md)。
