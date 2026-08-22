# 本地权限比较用户验收闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让测试人员在本地虚构角色站中，以显式人工登录配置完成可重复的权限比较用户验收。

**Architecture:** 把现有测试夹具的角色站抽为可复用的后端验收模块，由固定 loopback 启动脚本调用；测试夹具复用相同模块。前端权限比较表单把显式人工登录配置复制为每个身份的 `AuthenticationPlan`，而实际 Origin、HTTP 和认证计划门禁继续由既有后端模型验证。

**Tech Stack:** Python 3.12、标准库 `http.server`、pytest、FastAPI、Playwright、Vue 3、TypeScript、Vitest。

**Spec:** `docs/superpowers/specs/2026-08-22-user-acceptance-loop-design.md`

## Global Constraints

- 本地验收站只能绑定 `127.0.0.1`，不得提供公网绑定选项、外网访问或凭据读取。
- 不接受或展示账号、密码、Token、Cookie 输入；不保存或恢复登录态。
- `allow_local_http` 默认关闭，仅由用户显式开启；既有 `NavigationPolicy` 仍是唯一的 URL/Origin 门禁。
- UI 差异只能描述为观察结果；`partial` 或 `inconclusive` 绝不推断业务授权或后端数据权限。
- 所有生产代码先有失败测试；不删除、暂存或提交既有 pytest/诊断遗留文件。
- 后端命令默认在 `backend` 目录执行，并使用仓库根目录的 `..\..\..\.venv\Scripts\python.exe`；前端命令默认在 `frontend` 目录执行；启动脚本命令在工作树根目录执行，并使用 `..\..\.venv\Scripts\python.exe`。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/src/ai_ui_explorer/acceptance/permission_comparison_site.py` | 仅 loopback 的虚构角色 HTTP 站、固定角色与可测试生命周期。 |
| `scripts/run_permission_acceptance_site.py` | 启动验收站并处理安全的 Ctrl+C 退出，不接受绑定地址或凭据参数。 |
| `backend/tests/acceptance/test_permission_comparison_site.py` | 对站点网络边界、角色校验、登录和受限失败页的黑盒测试。 |
| `backend/tests/api/fixtures/permission_comparison_site.py` | 复用生产验收站模块，为既有 Chromium 测试提供 pytest fixture。 |
| `frontend/src/components/PermissionComparisonForm.vue` | 收集显式人工登录配置，安全地生成每身份认证计划。 |
| `frontend/tests/PermissionComparisonForm.spec.ts` | 验证默认安全 payload、启用后 payload 与无凭据 UI。 |
| `backend/tests/api/test_permission_comparisons.py` | 使用可启动验收站完成 Chromium 的角色差异、partial、取消与导出验证。 |
| `docs/user-acceptance/sprint6-permission-comparison-cases.md` | 用户可执行的中文启动、配置、验收和边界说明。 |
| `README.md` | 链接用户验收入口并重申能力边界。 |

### Task 1: 可复用的本地虚构角色验收站

**Files:**
- Create: `backend/src/ai_ui_explorer/acceptance/__init__.py`
- Create: `backend/src/ai_ui_explorer/acceptance/permission_comparison_site.py`
- Create: `scripts/run_permission_acceptance_site.py`
- Create: `backend/tests/acceptance/test_permission_comparison_site.py`
- Modify: `backend/tests/api/fixtures/permission_comparison_site.py`

**Interfaces:**
- Produces: `PermissionAcceptanceSite(port: int = 9100)` with `start() -> None`, `close() -> None`, `origin: str`, `login_url: str`, `dashboard_url: str` and context-manager lifecycle.
- Consumes: only `http.server`, `threading`, `urllib.parse`; it must bind `("127.0.0.1", port)` internally.
- Produces: fixed roles `admin`, `member`, `restricted`; `/login-complete` returns HTTP 400 for any other role and must not emit `Set-Cookie`.

- [ ] **Step 1: Write the failing black-box tests**

```python
def test_site_binds_loopback_and_rejects_unknown_login_role() -> None:
    with PermissionAcceptanceSite(port=0) as site:
        with pytest.raises(HTTPError) as error:
            urlopen(f"{site.origin}/login-complete?role=unknown")
        assert error.value.code == 400
        assert error.value.headers.get("Set-Cookie") is None


def test_admin_login_exposes_only_fixture_admin_navigation() -> None:
    with PermissionAcceptanceSite(port=0) as site:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        opener.open(f"{site.origin}/login-complete?role=admin")
        assert b"/admin.html" in opener.open(site.dashboard_url).read()
```

- [ ] **Step 2: Run the new test file to verify it fails**

Run: `..\..\..\.venv\Scripts\python.exe -m pytest tests\acceptance\test_permission_comparison_site.py -q`

Expected: FAIL because `ai_ui_explorer.acceptance.permission_comparison_site` does not exist.

- [ ] **Step 3: Implement the smallest reusable HTTP server**

```python
_LOOPBACK_HOST = "127.0.0.1"
_ROLES = frozenset({"admin", "member", "restricted"})


class PermissionAcceptanceSite:
    def __init__(self, *, port: int = 9100) -> None:
        self._server = ThreadingHTTPServer((_LOOPBACK_HOST, port), _RoleHandler)

    @property
    def origin(self) -> str:
        return f"http://{_LOOPBACK_HOST}:{self._server.server_port}"
```

Handle the five specified paths, redirect unauthenticated protected requests to `/login.html`, reject invalid roles before setting a cookie, and close the server/thread deterministically. Keep the fixture's existing observed pages and controlled connection-close behavior. Have the script instantiate `PermissionAcceptanceSite()` with its default port, print only the loopback URL, wait until Ctrl+C, then call `close()`.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `..\..\..\.venv\Scripts\python.exe -m pytest tests\acceptance\test_permission_comparison_site.py tests\api\test_permission_comparisons.py -q`

Expected: PASS; the existing test fixture imports and uses the reusable site rather than duplicating HTTP handler behavior.

- [ ] **Step 5: Run static checks**

Run: `..\..\..\.venv\Scripts\python.exe -m ruff check src\ai_ui_explorer\acceptance tests\acceptance tests\api\fixtures\permission_comparison_site.py`

Expected: PASS with no lint findings.

- [ ] **Step 6: Commit the self-contained deliverable**

```powershell
git add backend/src/ai_ui_explorer/acceptance scripts/run_permission_acceptance_site.py backend/tests/acceptance backend/tests/api/fixtures/permission_comparison_site.py
git commit -m "feat: add local permission acceptance site"
```

### Task 2: 权限比较的受控人工登录表单

**Files:**
- Modify: `frontend/src/components/PermissionComparisonForm.vue`
- Modify: `frontend/tests/PermissionComparisonForm.spec.ts`

**Interfaces:**
- Consumes: `CreatePermissionComparisonRequest`, `IdentityProfile` and `AuthenticationPlan` from `frontend/src/api/permissionComparisons.ts`.
- Produces: a request with `authentication_origins: []`, `allow_local_http: false`, and no identity `authentication_plan` until the operator checks “需要人工登录”.
- Produces after enabled: each identity has a separate object `{ authentication_plan: { authentication_url, post_login_url_prefix, checkpoint_css_selector } }`; `authentication_origins` has the explicit Origin and `allow_local_http` mirrors the explicit checkbox.

- [ ] **Step 1: Write the failing component tests**

```ts
it('keeps local HTTP and authentication plans disabled by default', async () => {
  const wrapper = mount(PermissionComparisonForm)
  await fillRequiredComparisonFields(wrapper)
  await wrapper.get('form').trigger('submit.prevent')

  expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({
    authentication_origins: [],
    allow_local_http: false,
    identities: [{ authentication_plan: undefined }],
  })
})

it('copies explicit human-login plan to each identity without rendering credentials', async () => {
  const wrapper = mount(PermissionComparisonForm)
  await wrapper.get('[data-test="manual-login"]').setValue(true)
  await wrapper.get('[data-test="allow-local-http"]').setValue(true)
  await fillRequiredComparisonFields(wrapper)
  await fillAuthenticationFields(wrapper)
  await wrapper.get('form').trigger('submit.prevent')

  expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({
    authentication_origins: ['http://127.0.0.1:9100'],
    allow_local_http: true,
  })
  expect(wrapper.html().toLowerCase()).not.toContain('password')
})
```

- [ ] **Step 2: Run the component test to verify it fails**

Run: `pnpm test -- PermissionComparisonForm`

Expected: FAIL because the comparison form has no manual-login controls or authentication payload.

- [ ] **Step 3: Implement the minimal form controls and payload mapping**

```ts
const needsManualLogin = ref(false)
const allowLocalHttp = ref(false)

const authenticationPlan = () => ({
  authentication_url: form.authenticationUrl.trim(),
  post_login_url_prefix: form.postLoginUrlPrefix.trim(),
  checkpoint_css_selector: form.checkpointCss.trim(),
})

identities: identities.value.map((identity) => ({
  identity_id: identity.identity_id,
  label: identity.label.trim(),
  authentication_plan: needsManualLogin.value ? authenticationPlan() : undefined,
}))
```

Render the four authentication fields only when manual login is checked and mark them required then. Render the local HTTP label exactly as in `ExplorationTaskForm.vue`: “仅本地验收：允许 HTTP（127.0.0.1 / localhost）”. Do not add credentials, storage-state controls, or browser-handle data.

- [ ] **Step 4: Run the focused frontend test to verify it passes**

Run: `pnpm test -- PermissionComparisonForm`

Expected: PASS; the disabled and enabled payloads both match the API type and no credential input is rendered.

- [ ] **Step 5: Run frontend quality checks**

Run: `pnpm typecheck; pnpm lint; pnpm format:check`

Expected: all commands PASS.

- [ ] **Step 6: Commit the self-contained deliverable**

```powershell
git add frontend/src/components/PermissionComparisonForm.vue frontend/tests/PermissionComparisonForm.spec.ts
git commit -m "feat: configure manual login for comparisons"
```

### Task 3: 可执行中文验收手册与端到端覆盖

**Files:**
- Create: `docs/user-acceptance/sprint6-permission-comparison-cases.md`
- Modify: `README.md`
- Modify: `backend/tests/api/test_permission_comparisons.py`

**Interfaces:**
- Consumes: `scripts/run_permission_acceptance_site.py`, the form payload from Task 2, and existing `/api/v1/permission-comparisons` endpoints.
- Produces: four reproducible acceptance cases with no credentials or sensitive data, plus real Chromium coverage of cancellation and export safety.

- [ ] **Step 1: Write the end-to-end cancellation and export assertions**

```python
def test_cancelled_local_comparison_does_not_start_second_identity(
    permission_comparison_site: PermissionComparisonSite,
) -> None:
    with TestClient(_comparison_app(permission_comparison_site)) as client:
        comparison_id = client.post("/api/v1/permission-comparisons", json=_local_payload(permission_comparison_site)).json()["comparison_id"]
        _wait_for_comparison_state(client, comparison_id, "identity-1", "paused_for_human")
        assert client.post(f"/api/v1/permission-comparisons/{comparison_id}/cancel").json()["state"] == "cancelled"
        assert client.get(f"/api/v1/permission-comparisons/{comparison_id}").json()["identities"]["identity-2"] == "created"


# Immediately after `terminal = _wait_for_terminal_comparison(local_client, comparison_id)`
# in the existing `with TestClient(app) as local_client:` block:
export = local_client.get(f"/api/v1/permission-comparisons/{comparison_id}/export")
assert export.status_code == 200
assert "fixture_role" not in export.text
assert "storage_state" not in export.text.lower()
```

- [ ] **Step 2: Run the selected tests as a characterization check**

Run: `..\..\..\.venv\Scripts\python.exe -m pytest tests\api\test_permission_comparisons.py -k "cancelled_local or fixture_login_state" -q`

Expected: PASS. These assertions document already-required service behavior; if either fails, add a separate failing regression test before changing production code.

- [ ] **Step 3: Add only the required assertions and user documentation**

Keep existing service behavior unchanged unless the new test identifies a real observable regression. Write the handoff steps for three PowerShell windows: local acceptance site, backend with a user-supplied non-secret database environment variable, and frontend. Include exact safe UI values for `http://127.0.0.1:9100`, all four acceptance cases, expected `completed`/`partial`/`cancelled` states, export inspection terms, and the restart limitation. Add one concise README link to this guide.

- [ ] **Step 4: Run focused tests and checks to verify they pass**

Run: `..\..\..\.venv\Scripts\python.exe -m pytest tests\api\test_permission_comparisons.py -q`

Expected: PASS, including the local Chromium cases when Playwright is installed.

Run: `pnpm test -- PermissionComparisonForm PermissionComparisonDetail App`

Expected: PASS.

- [ ] **Step 5: Run the documented manual acceptance smoke test**

Run: `..\..\.venv\Scripts\python.exe scripts\run_permission_acceptance_site.py`

Expected: prints only `http://127.0.0.1:9100`; opening `/login.html` exposes fixed fictional role buttons and Ctrl+C exits cleanly.

- [ ] **Step 6: Commit the self-contained deliverable**

```powershell
git add backend/tests/api/test_permission_comparisons.py docs/user-acceptance/sprint6-permission-comparison-cases.md README.md
git commit -m "docs: add permission comparison acceptance guide"
```

### Task 4: 全量回归与交付核查

**Files:**
- Modify: none unless a preceding verification finds a defect; write a new failing regression test before any fix.

**Interfaces:**
- Consumes: Task 1–3 deliverables.
- Produces: verified local acceptance loop with declared coverage and explicit remaining limitations.

- [ ] **Step 1: Run backend unit and API regression**

Run: `..\..\..\.venv\Scripts\python.exe -m pytest tests\acceptance tests\api\test_permission_comparisons.py tests\task_management tests\permission_comparison -q`

Expected: PASS. If a test fails, stop and add or repair the smallest regression test before changing production code.

- [ ] **Step 2: Run backend static checks**

Run: `..\..\..\.venv\Scripts\python.exe -m ruff check --no-cache src tests\acceptance tests\api\test_permission_comparisons.py`

Expected: PASS.

Run: `..\..\..\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml src\ai_ui_explorer`

Expected: PASS.

- [ ] **Step 3: Run complete frontend verification**

Run: `pnpm test; pnpm lint; pnpm typecheck; pnpm format:check; pnpm build`

Expected: all commands PASS.

- [ ] **Step 4: Inspect the final diff and repository status**

Run: `git diff HEAD~3..HEAD --check; git status --short`

Expected: no whitespace errors; only known pre-existing untracked diagnostic artifacts remain. Do not stage them.

- [ ] **Step 5: Report exact evidence and limitations**

Report the commit IDs, commands run, test results, manual smoke-test result, and the unimplemented boundaries: historical result UI, real external login, SSO/MFA, browser-state persistence, backend-data authorization conclusions, and production deployment.
