# Sprint 4：人机协同登录运行时设计

## 目标

在不保存真实账号、密码、Cookie、Token、验证码或浏览器存储状态的前提下，使受控探索任务可以
暂停，由人工在可见浏览器中完成登录，再经显式、可配置的认证检查后恢复只读探索。

本设计只覆盖后端运行时和本地模拟登录站点验收。不新增探索任务 API、Vue 登录确认页、真实外部
网站验收、跨任务登录态复用或业务动作执行。

## 已确认约束

- 登录浏览器 Context 仅存在于当前进程内存；任务结束、取消或失败时立即关闭。
- 认证 Origin、登录后 URL 前缀和检查点 CSS 选择器均由配置显式提供；不得从页面内容推断。
- 人工必须显式确认后才触发认证验证；页面跳转本身不构成登录成功。
- 认证验证只能使用已配置的同源检查点；验证失败不得将状态标记为已认证，可回到暂停状态后重试。
- 恢复后仍受现有 NavigationPolicy、只读 ActionGate、深度/页面/队列预算和状态去重约束。

## 架构与数据流

```text
created / collecting
        |
        v
paused_for_human --(人工在可见浏览器完成登录)--> verifying_authentication
        ^                                                  |
        |----------------(检查失败)------------------------|
                                                           |
                                              (URL 与检查点均通过)
                                                           v
                                                     collecting
                                                           |
                                      completed / partial / failed / cancelled
                                                           |
                                                           v
                                                   销毁 Browser Context
```

### 配置模型

`AuthenticationPlan` 是任务创建时的显式输入，至少包含：

- `authentication_url`：允许人工登录时访问的 URL，必须被认证 Origin 白名单允许。
- `post_login_url_prefix`：认证成功后当前页面 URL 必须匹配的前缀。
- `checkpoint_css_selector`：认证成功后必须在目标 Origin 页面内找到的 CSS 选择器。

配置中不允许账号、密码、Cookie、Token、验证码或任何登录表单值。

### 会话运行时

`HumanLoginSession` 持有一个非无头 Playwright Browser Context 和当前 Page。它只提供受限的状态转换：

1. `pause_for_human`：按认证 URL 打开可见浏览器，并转为 `paused_for_human`。
2. `confirm_and_verify`：只有暂停状态可以调用；依次验证当前 URL 前缀与同源检查点。
3. `collector_port`：只在验证成功后提供绑定同一 Context 的 Snapshot Collector Port。
4. `close`：幂等关闭 Page、Context 和 Browser；任何终态均必须调用。

运行时不得调用 `storage_state()`，不得向文件、日志或模型暴露浏览器存储状态。审计事件只记录状态、
配置标识和安全原因码，不记录页面敏感内容。

### 浏览器采集适配

现有 `PlaywrightBrowserSource` 会为每次采集新建 Context，无法保留登录态。新增的会话绑定采集适配器
必须复用 `HumanLoginSession` 的 Context，在同一 Page 或同一 Context 新建的受控 Page 中进行 Snapshot
收集。它不执行点击、填充、提交或文件上传；导航候选仍由现有 Runner 的只读规则处理。

## 错误与清理

- 未经人工确认调用恢复：拒绝并保持暂停状态。
- URL 前缀不匹配、检查点不存在、检查点跨 Origin 或页面关闭：认证失败并回到暂停状态。
- 启动浏览器或验证过程异常：以安全原因码记录，不暴露 URL 查询敏感值或浏览器底层错误。
- 完成、部分完成、失败、取消和显式关闭：关闭内存会话；关闭后不再允许采集或认证。

## 测试策略

使用本地 HTTP 模拟登录站点和真实 Chromium：

- 未确认前不能取得恢复用 Collector。
- 未登录或检查点失败时不能认证。
- 模拟人工完成登录后，验证成功并能通过同一 Context 采集登录后页面。
- 认证 Origin、URL 前缀和跨 Origin 检查点均拒绝。
- 终态销毁 Context；后续确认或采集被拒绝。
- 测试断言不持久化或输出凭据、Cookie、Token 与浏览器存储状态。

## 非目标

- API、前端确认界面与跨进程会话恢复。
- 加密登录态文件和跨任务复用。
- SSO、扫码、MFA 的专用协议适配。
- 对真实外部网站的自动化登录或绕过访问控制。
