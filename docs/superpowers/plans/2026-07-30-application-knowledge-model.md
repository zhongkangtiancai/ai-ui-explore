# Sprint 2 Application Knowledge Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将一份经过校验的 Snapshot 1.0/1.1 确定性转换为独立、脱敏、可追溯的 `knowledge-package.json`，并在 Snapshot 1.1 中补充有界、分层、经过唯一性验证的 Playwright 定位知识。

**Architecture:** 保持 `snapshot` 与新建的 `knowledge` 包解耦。采集器默认生成 Snapshot 1.1，Knowledge Builder 通过版本适配器读取 1.0/1.1，以应用清单提供 Application 身份，再建立轻量实体、定位候选、证据、原子事实、低可靠观察和知识缺口。CLI 只调用 Builder 和原子 Writer；不重新访问网站，不引入 LLM、数据库、API 或前端功能。

**Tech Stack:** Python 3.12、Playwright 1.61.0 同步 API、Chromium、Pydantic 2.13.4、jsonschema 4.25.1、pytest 8.4.1、Ruff、mypy；不新增外部包版本或前端依赖，已锁定的 jsonschema 从开发依赖提升为运行时契约校验依赖。

## Global Constraints

- 代码标识符和 JSON 字段使用英文；文档与用户提示使用简体中文。
- 所有实现严格测试先行；每项任务先观察目标测试失败，再写最小实现。
- Snapshot 1.0 Schema 必须保留且继续可读；新采集默认输出 Snapshot 1.1。
- Snapshot 1.1 不采集完整 HTML、任意属性集合、输入值、Cookie、Token、Storage State、截图或网络正文。
- `knowledge-package.json` 独立于快照；一份快照生成一份不可变知识包。
- Builder 不重新打开 URL，不调用 LLM、Agent、数据库、FastAPI 或网络服务。
- Application 身份只来自版本化应用清单，不根据标题或主机名自动命名。
- Sprint 2 只生成 observed Fact；`inferences` 必须为空。
- Observation 和 KnowledgeGap 不得转换成 Fact。
- Evidence 必须包含来源快照 ID、版本、JSON Pointer、脱敏有限摘要和规范化快照 SHA-256。
- 同一应用清单和同一快照的重复输出必须字节级一致。
- 跨快照实体不共享确定 ID，只输出 `match_hints`。
- 定位候选优先用户语义和 test id；CSS/XPath 必须有界并在当前 Frame 验证；坐标不得推荐为代码生成定位器。
- 默认预算：Evidence 摘要 500 字符、每个 Element 12 个定位候选、150,000 个 Fact、1,000 个 Observation、1,000 个 KnowledgeGap、最终 JSON 50 MB。
- 达到源快照或知识预算时输出有效 `partial` 包并返回 2；无有效包时不写文件并返回 1。
- 所有字符串在进入持久化模型前经过现有 Redactor；禁止输出敏感原值。
- Pydantic 模型是运行时契约的事实来源；提交的 JSON Schema 必须与模型完全一致，Writer 在原子替换前执行两者校验。
- 输出采用同目录临时文件、flush、fsync 和原子替换；失败不留半成品。
- 不修改前端，不创建数据库、Docker、Worker、上传 API 或登录运行时。
- 不修改根 `AGENTS.md`；只更新与本功能直接相关的产品、模型、路线图和 README 文档。
- 每个任务只提交列出的文件；不得夹带真实探索输出、浏览器状态或无关工作树变更。

---

### Task 1: Versioned Snapshot 1.1 Contract

**Files:**

- Modify: `backend/src/ai_ui_explorer/snapshot/models.py`
- Create: `backend/src/ai_ui_explorer/snapshot/schema/snapshot-v1.1.schema.json`
- Modify: `backend/tests/snapshot/factories.py`
- Modify: `backend/tests/snapshot/test_models.py`
- Modify: `backend/tests/snapshot/test_writer.py`
- Modify: `backend/tests/snapshot/test_cli.py`

**Interfaces:**

- Produces: `SnapshotDocumentV1`, `SnapshotDocument`, `AnySnapshotDocument`
- Produces: `SnapshotLocatorCandidate`
- Produces: `SnapshotDocument.schema_version == "1.1"`
- Preserves: committed `snapshot-v1.schema.json` for historical 1.0 payloads
- Consumed by: Tasks 2、3、5

- [ ] **Step 1: Write failing version and locator model tests**

Add tests that require:

```python
def test_current_snapshot_schema_is_version_1_1() -> None:
    snapshot = make_snapshot()
    assert snapshot.schema_version == "1.1"
    assert SnapshotDocument.to_schema()["properties"]["schema_version"]["const"] == "1.1"


def test_legacy_snapshot_model_accepts_version_1_0() -> None:
    payload = make_snapshot().model_dump(mode="json")
    payload["schema_version"] = "1.0"
    payload.pop("locator_candidates")
    payload["statistics"].pop("locator_candidate_count")
    legacy = SnapshotDocumentV1.model_validate(payload)
    assert legacy.schema_version == "1.0"


def test_snapshot_rejects_locator_with_missing_element_reference() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(
            locator_candidates=[
                {
                    "locator_id": "locator-missing",
                    "element_ref": "missing",
                    "frame_ref": "root",
                    "strategy": "role",
                    "parameters": {"role": "button", "name": "Submit"},
                    "source": "observed",
                    "uniqueness": "unique",
                    "match_count": 1,
                    "stability": "high",
                    "confidence": 1.0,
                    "rank": 1,
                    "recommended": True,
                    "limitations": [],
                }
            ]
        )
```

Also assert:

- locator IDs are unique;
- `(element_ref, rank)` is unique;
- every Frame and Element reference exists and agrees;
- no Element has more than 12 candidates;
- `unique` requires `match_count == 1`;
- `multiple` requires `match_count >= 2`;
- `position` cannot be `recommended`;
- `confidence` is between 0 and 1;
- statistics `locator_candidate_count` equals the actual list size.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_models.py backend\tests\snapshot\test_writer.py backend\tests\snapshot\test_cli.py -q
```

Expected: FAIL because versioned models, `SnapshotLocatorCandidate`, `locator_candidates` and `locator_candidate_count` do not exist.

- [ ] **Step 3: Implement the versioned contract**

Refactor common document fields and validators into a base model, while preserving the public name `SnapshotDocument` for the current contract:

```python
LocatorStrategy = Literal[
    "role", "label", "text", "placeholder", "alt", "title",
    "testid", "id", "name", "aria", "css", "xpath", "position",
]
LocatorParameter = str | bool | int | float


class SnapshotLocatorCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator_id: str
    element_ref: str
    frame_ref: str
    strategy: LocatorStrategy
    parameters: dict[str, LocatorParameter]
    source: Literal["observed", "generated"]
    uniqueness: Literal["unique", "multiple", "unverified"]
    match_count: int | None = Field(default=None, ge=0)
    stability: Literal["high", "medium", "low", "unknown"]
    confidence: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    recommended: bool
    limitations: list[str]


class _SnapshotDocumentBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    status: Literal["completed", "partial"]
    started_at: datetime
    completed_at: datetime
    source: SourceSnapshot
    limits: SnapshotLimits
    statistics: SnapshotStatistics
    page: PageSnapshot
    frames: list[FrameSnapshot]
    errors: list[SnapshotError]
    truncated: bool


class SnapshotDocumentV1(_SnapshotDocumentBase):
    schema_version: Literal["1.0"] = "1.0"


class SnapshotDocument(_SnapshotDocumentBase):
    schema_version: Literal["1.1"] = "1.1"
    locator_candidates: list[SnapshotLocatorCandidate] = Field(default_factory=list)


AnySnapshotDocument = SnapshotDocumentV1 | SnapshotDocument
```

Move the current `validate_status()` implementation to `_SnapshotDocumentBase`
without weakening any existing timestamp、main Frame、Element count or partial
status invariant.

Extend `SnapshotStatistics` with:

```python
locator_candidate_count: int = Field(default=0, ge=0)
```

Add a `SnapshotDocument` validator that enforces all reference, rank, count and position rules from Step 1. Keep `SnapshotDocumentV1` free of 1.1-only fields.

- [ ] **Step 4: Update deterministic test factories**

Make `make_snapshot()` emit 1.1 with an empty locator list by default. Add:

```python
def make_locator_candidate(**overrides: Any) -> SnapshotLocatorCandidate:
    values: dict[str, Any] = {
        "locator_id": "locator-root-element-0-role",
        "element_ref": "root-element-0",
        "frame_ref": "root",
        "strategy": "role",
        "parameters": {"role": "button", "name": "Submit", "exact": True},
        "source": "observed",
        "uniqueness": "unique",
        "match_count": 1,
        "stability": "high",
        "confidence": 1.0,
        "rank": 1,
        "recommended": True,
        "limitations": [],
    }
    values.update(overrides)
    return SnapshotLocatorCandidate.model_validate(values)
```

Update existing assertions from `1.0` to `1.1` only where they describe newly generated snapshots. Add a separate legacy fixture for 1.0.

- [ ] **Step 5: Generate and test the committed 1.1 Schema**

Generate `snapshot-v1.1.schema.json` from `SnapshotDocument.to_schema()` using sorted keys and UTF-8. Do not overwrite `snapshot-v1.schema.json`.

Add a parity test:

```python
def test_snapshot_v1_1_schema_matches_model() -> None:
    committed = json.loads(_SNAPSHOT_V1_1_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == SnapshotDocument.to_schema()
```

Update current CLI/Writer schema tests to validate new output with the 1.1 schema; retain one test that validates a legacy payload with the 1.0 schema.

- [ ] **Step 6: Run Task 1 verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_models.py backend\tests\snapshot\test_writer.py backend\tests\snapshot\test_cli.py -q
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\snapshot\models.py backend\tests\snapshot
.\.venv\Scripts\python.exe -m mypy -p ai_ui_explorer.snapshot
```

Expected: all commands PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add backend/src/ai_ui_explorer/snapshot/models.py backend/src/ai_ui_explorer/snapshot/schema/snapshot-v1.1.schema.json backend/tests/snapshot/factories.py backend/tests/snapshot/test_models.py backend/tests/snapshot/test_writer.py backend/tests/snapshot/test_cli.py
git commit -m "feat: add snapshot 1.1 locator contract"
```

---

### Task 2: Bounded Locator Candidate Observation

**Files:**

- Modify: `backend/src/ai_ui_explorer/snapshot/browser.py`
- Modify: `backend/tests/fixtures/snapshot_site/primary/index.html`
- Create: `backend/tests/fixtures/snapshot_site/primary/locator-candidates.html`
- Modify: `backend/tests/snapshot/conftest.py`
- Modify: `backend/tests/snapshot/fakes.py`
- Modify: `backend/tests/snapshot/test_browser.py`
- Modify: `backend/tests/snapshot/test_scrolling.py`

**Interfaces:**

- Produces: `RawLocatorCandidate`
- Extends: `RawElementObservation.locator_candidates`
- Preserves: existing `RawLocatorHint` during this task for compatibility; Task 3 removes or adapts it after collector migration
- Consumed by: Task 3

- [ ] **Step 1: Add failing real-browser locator tests**

Create a local fixture containing:

- unique role/name button;
- duplicate role/name buttons;
- labelled input;
- placeholder input;
- image with alt;
- element with title;
- unique `data-testid`;
- unique `id`;
- unique `name`;
- element requiring bounded CSS;
- element requiring bounded XPath;
- open Shadow DOM element;
- dynamic-looking class;
- sensitive-looking attributes with synthetic values.

Test the raw observation:

```python
def test_browser_collects_ranked_bounded_locator_candidates(locator_page_url: str) -> None:
    raw_page = PlaywrightBrowserSource(headless=True).observe(
        locator_page_url, SnapshotLimits()
    )
    submit = next(
        element
        for frame in raw_page.frames
        for element in frame.elements
        if element.accessible_name == "Submit order"
    )

    assert submit.locator_candidates
    assert submit.locator_candidates[0].rank == 1
    assert any(item.strategy == "role" for item in submit.locator_candidates)
    assert any(item.strategy == "position" for item in submit.locator_candidates)
    assert len(submit.locator_candidates) <= 12
```

Also assert:

- duplicate role candidate is `multiple` and not recommended;
- unique test id is ranked above low-stability structural selectors;
- CSS/XPath length and ancestor depth remain bounded;
- position is low stability and not recommended;
- no candidate parameter contains the synthetic password, token, dynamic class or input value;
- candidates discovered after scrolling retain locator metadata;
- cross-origin Frame candidates keep their own Frame scope.

- [ ] **Step 2: Run focused browser tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_browser.py backend\tests\snapshot\test_scrolling.py -q
```

Expected: FAIL because `RawLocatorCandidate` and the fixture do not exist.

- [ ] **Step 3: Define raw locator types**

Add:

```python
@dataclass(frozen=True, slots=True)
class RawLocatorCandidate:
    strategy: LocatorStrategy
    parameters: dict[str, LocatorParameter]
    source: Literal["observed", "generated"]
    uniqueness: Literal["unique", "multiple", "unverified"]
    match_count: int | None
    stability: Literal["high", "medium", "low", "unknown"]
    confidence: float
    rank: int
    recommended: bool
    limitations: tuple[str, ...]
```

Extend `RawElementObservation` with:

```python
locator_candidates: tuple[RawLocatorCandidate, ...]
```

Extend `_RawElementPayload` with the corresponding `locatorCandidates` list payload.

- [ ] **Step 4: Generate safe candidates in the isolated selector carrier**

Inside `_OBSERVATION_SELECTOR_ENGINE`, add pure helper functions that:

- normalize candidate parameters;
- count semantic duplicates among the current Frame’s visible interactive elements;
- use `querySelectorAll` for CSS count;
- use
  `document.evaluate(expression, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null)`
  for XPath count;
- build at most four DOM levels and at most 256 characters for CSS/XPath;
- reject attribute values whose names are outside the existing whitelist;
- reject values containing redaction markers or sensitive-key names;
- never read `element.value`;
- attach viewport values to position parameters.

The ranking input must be deterministic:

```javascript
const strategyOrder = {
  testid: 0, role: 1, label: 2, text: 3, placeholder: 4,
  alt: 5, title: 6, id: 7, name: 8, aria: 9,
  css: 10, xpath: 11, position: 12,
};
```

Sort first by recommended unique candidates, then stability, strategy order and canonical parameter JSON. Slice to 12 and assign one-based rank after sorting.

Semantic candidates use observed attributes. Structural selectors use `source: "generated"`. Position always uses:

```javascript
{
  strategy: "position",
  parameters: {
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
  },
  source: "observed",
  uniqueness: "unverified",
  matchCount: null,
  stability: "low",
  confidence: 1.0,
  recommended: false,
  limitations: ["viewport_and_scroll_dependent"],
}
```

- [ ] **Step 5: Parse candidates into raw observations**

Update `_element_from_payload()` to validate the finite strategy/status vocabulary and construct `RawLocatorCandidate` tuples. Do not silently accept unknown strategy names.

Update all fake `RawElementObservation` constructors to use `locator_candidates=()`.

- [ ] **Step 6: Run Task 2 verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_browser.py backend\tests\snapshot\test_scrolling.py -q
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\snapshot\browser.py backend\tests\snapshot
.\.venv\Scripts\python.exe -m mypy -p ai_ui_explorer.snapshot
```

Expected: all commands PASS with real Chromium.

- [ ] **Step 7: Commit Task 2**

```powershell
git add backend/src/ai_ui_explorer/snapshot/browser.py backend/tests/fixtures/snapshot_site/primary/index.html backend/tests/fixtures/snapshot_site/primary/locator-candidates.html backend/tests/snapshot/conftest.py backend/tests/snapshot/fakes.py backend/tests/snapshot/test_browser.py backend/tests/snapshot/test_scrolling.py
git commit -m "feat: observe bounded locator candidates"
```

---

### Task 3: Locator Redaction, Snapshot Mapping, and Size Closure

**Files:**

- Modify: `backend/src/ai_ui_explorer/snapshot/collector.py`
- Modify: `backend/src/ai_ui_explorer/snapshot/writer.py`
- Modify: `backend/src/ai_ui_explorer/snapshot/browser.py`
- Modify: `backend/src/ai_ui_explorer/snapshot/models.py`
- Modify: `backend/tests/snapshot/test_collector.py`
- Modify: `backend/tests/snapshot/test_writer.py`
- Modify: `backend/tests/snapshot/test_redaction.py`
- Modify: `backend/tests/snapshot/test_models.py`

**Interfaces:**

- Produces: Snapshot 1.1 documents with top-level `locator_candidates`
- Guarantees: every locator parameter is redacted before entering Pydantic models
- Guarantees: compaction never leaves a locator referencing a removed Element
- Consumed by: Tasks 5、6 and end-to-end acceptance

- [ ] **Step 1: Write failing collector and compaction tests**

Add tests requiring:

```python
def test_collector_redacts_and_flattens_locator_candidates() -> None:
    source = FakeSource(page_with_locator_value("token=synthetic-secret"))
    snapshot = SnapshotCollector(source=source, uuid_factory=fixed_uuid).collect(
        "https://example.test", SnapshotLimits()
    )

    candidate = snapshot.locator_candidates[0]
    assert candidate.element_ref == snapshot.frames[0].elements[0].element_id
    assert "synthetic-secret" not in json.dumps(candidate.model_dump())
    assert "[REDACTED:TOKEN]" in json.dumps(candidate.model_dump())


def test_compaction_removes_locators_for_removed_elements() -> None:
    compacted = compact_snapshot(make_oversized_snapshot_with_locators(70_000))
    element_ids = {
        element.element_id for frame in compacted.frames for element in frame.elements
    }
    assert all(item.element_ref in element_ids for item in compacted.locator_candidates)
    assert compacted.statistics.locator_candidate_count == len(
        compacted.locator_candidates
    )
```

Also assert locator IDs/ranks are deterministic and candidate limitations are redacted.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_collector.py backend\tests\snapshot\test_writer.py backend\tests\snapshot\test_redaction.py -q
```

Expected: FAIL because the collector does not map raw candidates.

- [ ] **Step 3: Sanitize and map candidates**

Add a collector helper with this exact responsibility:

```python
def _locator_candidates(
    *,
    frame_id: str,
    element_id: str,
    raw_candidates: tuple[RawLocatorCandidate, ...],
    sanitizer: _Sanitizer,
) -> list[SnapshotLocatorCandidate]:
    mapped: list[SnapshotLocatorCandidate] = []
    for raw in raw_candidates:
        parameters = {
            key: sanitizer.text(value) if isinstance(value, str) else value
            for key, value in raw.parameters.items()
        }
        limitations = [sanitizer.text(value) for value in raw.limitations]
        mapped.append(
            SnapshotLocatorCandidate(
                locator_id=_stable_locator_id(
                    frame_id,
                    element_id,
                    raw.strategy,
                    parameters,
                    raw.rank,
                ),
                element_ref=element_id,
                frame_ref=frame_id,
                strategy=raw.strategy,
                parameters=parameters,
                source=raw.source,
                uniqueness=raw.uniqueness,
                match_count=raw.match_count,
                stability=raw.stability,
                confidence=raw.confidence,
                rank=raw.rank,
                recommended=raw.recommended,
                limitations=limitations,
            )
        )
    return mapped
```

For every string parameter:

- use `redact_url` only for parameters explicitly representing URL;
- otherwise use `redact_text`;
- redact each limitation;
- preserve numeric and boolean parameters;
- generate `locator_id` from `frame_id`, `element_id`, strategy, canonical redacted parameters and rank using SHA-256 with a short readable prefix.

Flatten candidates after Element IDs are assigned. Set `locator_candidate_count` from the final list.

- [ ] **Step 4: Close compaction references**

Whenever `compact_snapshot()` removes an Element:

```python
remaining_element_ids = {
    element.element_id for frame in frames for element in frame.elements
}
locator_candidates = [
    item
    for item in snapshot.locator_candidates
    if item.element_ref in remaining_element_ids
]
```

Update statistics with both actual Element and locator counts. The compacted snapshot must pass full `SnapshotDocument` validation before serialization.

- [ ] **Step 5: Remove the legacy raw hint duplication**

After collector tests cover all 1.1 strategies:

- remove `RawLocatorHint`;
- remove `RawElementObservation.locator_hints`;
- keep `ElementSnapshot.locator_hints` only for Snapshot 1.0 compatibility inside `SnapshotDocumentV1`;
- use 1.1 `locator_candidates` as the only new-output locator source.

If the common Element model cannot preserve strict 1.0 without duplication, introduce `ElementSnapshotV1` and `FrameSnapshotV1` in the legacy branch rather than accepting ambiguous fields.

- [ ] **Step 6: Run Task 3 verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot -q
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\snapshot backend\tests\snapshot
.\.venv\Scripts\python.exe -m mypy -p ai_ui_explorer.snapshot
```

Expected: all Snapshot tests PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add backend/src/ai_ui_explorer/snapshot/collector.py backend/src/ai_ui_explorer/snapshot/writer.py backend/src/ai_ui_explorer/snapshot/browser.py backend/src/ai_ui_explorer/snapshot/models.py backend/tests/snapshot/test_collector.py backend/tests/snapshot/test_writer.py backend/tests/snapshot/test_redaction.py backend/tests/snapshot/test_models.py
git commit -m "feat: persist redacted snapshot locator knowledge"
```

---

### Task 4: Application Manifest and Knowledge Package Contract

**Files:**

- Create: `backend/src/ai_ui_explorer/knowledge/__init__.py`
- Create: `backend/src/ai_ui_explorer/knowledge/manifest.py`
- Create: `backend/src/ai_ui_explorer/knowledge/models.py`
- Create: `backend/src/ai_ui_explorer/knowledge/predicates.py`
- Create: `backend/src/ai_ui_explorer/knowledge/schema/application-manifest-v1.schema.json`
- Create: `backend/src/ai_ui_explorer/knowledge/schema/knowledge-package-v1.schema.json`
- Create: `backend/tests/knowledge/__init__.py`
- Create: `backend/tests/knowledge/factories.py`
- Create: `backend/tests/knowledge/test_manifest.py`
- Create: `backend/tests/knowledge/test_models.py`

**Interfaces:**

- Produces: `ApplicationManifest`
- Produces: `KnowledgeLimits`, `KnowledgePackage`
- Produces: `KnowledgeEntity`, `KnowledgeLocator`, `Evidence`, `Fact`, `Observation`, `Inference`, `KnowledgeGap`
- Produces: controlled `Predicate` enum
- Consumed by: Tasks 5、6、7

- [ ] **Step 1: Write failing manifest tests**

Test:

```python
def test_manifest_normalizes_exact_origins() -> None:
    manifest = ApplicationManifest(
        application_id="customer-service-portal",
        name="客服管理平台",
        environment="test",
        allowed_origins=["https://test.example.internal"],
        authentication_origins=["https://sso.example.internal"],
    )
    assert manifest.allowed_origins == ["https://test.example.internal"]


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@example.test",
        "https://example.test/path",
        "https://example.test?token=secret",
        "https://example.test/#fragment",
        "javascript:alert(1)",
    ],
)
def test_manifest_rejects_non_origin_values(origin: str) -> None:
    with pytest.raises(ValidationError):
        ApplicationManifest(
            application_id="app",
            name="App",
            environment="test",
            allowed_origins=[origin],
        )
```

Also reject duplicate normalized origins, unsafe Application IDs, empty names and overlap that would weaken target/auth distinction.

- [ ] **Step 2: Write failing knowledge invariant tests**

Require:

- `extra="forbid"` on every model;
- Fact has exactly one of `value` and `object_ref`;
- observed Fact confidence is 1.0;
- Observation has non-empty evidence, confidence, limitations and `unverified`;
- Inference requires conclusion, evidence, confidence, producer, method and UTC timestamp;
- KnowledgeGap requires a controlled reason code;
- position Locator cannot be recommended;
- every reference resolves inside the package;
- `inferences` must be empty for a Sprint 2-produced package;
- package statistics equal actual counts;
- partial package has at least one truncation reason.

- [ ] **Step 3: Run model tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_manifest.py backend\tests\knowledge\test_models.py -q
```

Expected: FAIL because the `knowledge` package does not exist.

- [ ] **Step 4: Implement the manifest**

Use `urlsplit()` and reconstruct the origin from lower-cased scheme/host plus explicit non-default port. Accept only `http` and `https`; reject userinfo, path other than empty or `/`, query and fragment. Store sorted unique origins.

Public method:

```python
class ApplicationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    application_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=64)
    allowed_origins: list[str] = Field(min_length=1, max_length=100)
    authentication_origins: list[str] = Field(default_factory=list, max_length=100)

    def classify_url(self, value: str) -> Literal["target", "authentication", "outside"]:
        origin = normalize_origin_from_url(value)
        if origin in self.allowed_origins:
            return "target"
        if origin in self.authentication_origins:
            return "authentication"
        return "outside"
```

- [ ] **Step 5: Implement the knowledge models**

Define finite Literals/Enums for:

- entity types: page、frame、element;
- source types: snapshot;
- collection/content/access/exploration statuses approved in the spec;
- knowledge status: completed、partial;
- locator strategy/source/uniqueness/stability;
- knowledge gap reason codes;
- controlled predicates.

Use JSON scalar values only:

```python
FactValue = str | bool | int | float


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str
    subject_ref: str
    predicate: Predicate
    value: FactValue | None = None
    object_ref: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=1.0, le=1.0)
    assertion_type: Literal["observed"] = "observed"
    observed_at: datetime
```

Define the remaining public record shapes with these exact field names:

```python
class IdentityContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["not_provided", "provided"]
    identity_alias: str | None
    role_label: str | None
    authorization_scope: list[str]


class ExplorationRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    exploration_run_id: str
    snapshot_id: UUID
    snapshot_schema_version: Literal["1.0", "1.1"]
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    collection_status: Literal["completed", "partial", "failed"]
    content_status: Literal["expected", "unexpected", "insufficient_evidence"]
    access_status: AccessStatus
    exploration_status: ExplorationStatus
    identity_context: IdentityContext
    started_at: datetime
    completed_at: datetime


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    snapshot_id: UUID
    snapshot_schema_version: Literal["1.0", "1.1"]
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    json_pointer: str
    evidence_type: str
    excerpt: str


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation_id: str
    subject_ref: str
    summary: str
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(gt=0, lt=1)
    limitations: list[str] = Field(min_length=1)
    promotion_status: Literal["unverified"] = "unverified"


class Inference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    inference_id: str
    conclusion: str
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    producer: str
    method: str
    created_at: datetime


class KnowledgeGap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    gap_id: str
    subject_ref: str
    aspect: str
    reason_code: KnowledgeGapReason
    reason: str
    evidence_refs: list[str]
    verification: str


class KnowledgePackage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    package_id: str
    status: Literal["completed", "partial"]
    limits: KnowledgeLimits
    application: KnowledgeApplication
    exploration_run: ExplorationRun
    entities: list[KnowledgeEntity]
    locator_candidates: list[KnowledgeLocator]
    evidence: list[Evidence]
    facts: list[Fact]
    observations: list[Observation]
    inferences: list[Inference]
    knowledge_gaps: list[KnowledgeGap]
    statistics: KnowledgeStatistics
    stop_reasons: list[str]
```

`KnowledgePackage` owns the reference-closure validator. `KnowledgeLimits` carries the approved defaults. Store Application and ExplorationRun at top level; `entities` contains only Page、Frame、Element; locators live only in `locator_candidates`.

- [ ] **Step 6: Generate committed Schemas and parity tests**

Generate both schema files from model methods using sorted UTF-8 JSON. Tests compare exact parsed JSON equality with `ApplicationManifest.to_schema()` and `KnowledgePackage.to_schema()`.

- [ ] **Step 7: Run Task 4 verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_manifest.py backend\tests\knowledge\test_models.py -q
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\knowledge backend\tests\knowledge
.\.venv\Scripts\python.exe -m mypy -p ai_ui_explorer.knowledge
```

Expected: all commands PASS.

- [ ] **Step 8: Commit Task 4**

```powershell
git add backend/src/ai_ui_explorer/knowledge backend/tests/knowledge
git commit -m "feat: define application knowledge contract"
```

---

### Task 5: Snapshot Adapter, Deterministic IDs, and Evidence

**Files:**

- Create: `backend/src/ai_ui_explorer/knowledge/snapshot_adapter.py`
- Create: `backend/src/ai_ui_explorer/knowledge/ids.py`
- Create: `backend/src/ai_ui_explorer/knowledge/evidence.py`
- Create: `backend/tests/knowledge/test_snapshot_adapter.py`
- Create: `backend/tests/knowledge/test_ids.py`
- Create: `backend/tests/knowledge/test_evidence.py`

**Interfaces:**

- Produces: `load_snapshot(path: Path) -> AnySnapshotDocument`
- Produces: `canonical_json(value: object) -> str`
- Produces: `stable_id(prefix: str, *parts: object) -> str`
- Produces: `resolve_json_pointer(document: object, pointer: str) -> object`
- Produces: `EvidenceBuilder(snapshot: AnySnapshotDocument, redactor: Redactor, excerpt_limit: int)`
- Consumed by: Task 6

- [ ] **Step 1: Write failing adapter tests**

Require:

- 1.0 payload loads as `SnapshotDocumentV1`;
- 1.1 payload loads as `SnapshotDocument`;
- unknown versions fail with a safe message;
- invalid payload does not get repaired;
- file contents are never logged in the exception.

```python
def test_load_snapshot_dispatches_by_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(make_snapshot().model_dump_json(), encoding="utf-8")
    assert isinstance(load_snapshot(path), SnapshotDocument)
```

- [ ] **Step 2: Write failing deterministic ID and pointer tests**

Test canonical key sorting, Unicode preservation, list order, escaped JSON Pointer tokens (`~0`, `~1`), invalid pointers and repeated `stable_id()` calls.

The ID format is:

```text
<prefix>-<first 24 lowercase hex characters of SHA-256>
```

- [ ] **Step 3: Write failing evidence tests**

Require:

```python
def test_evidence_is_traceable_redacted_and_bounded() -> None:
    builder = EvidenceBuilder(
        snapshot=make_snapshot_with_text("token=synthetic-secret"),
        redactor=Redactor(),
        excerpt_limit=20,
    )
    evidence = builder.at("/frames/0/text_summary", "frame.text_summary")

    assert evidence.snapshot_id == str(make_snapshot().snapshot_id)
    assert evidence.json_pointer == "/frames/0/text_summary"
    assert "synthetic-secret" not in evidence.excerpt
    assert len(evidence.excerpt) <= 20
    assert len(evidence.snapshot_sha256) == 64
```

Also verify the digest equals SHA-256 of `canonical_json(snapshot.model_dump(mode="json"))`.

- [ ] **Step 4: Implement version dispatch**

Read JSON once, inspect only `schema_version`, then call the exact model:

```python
def load_snapshot(path: Path) -> AnySnapshotDocument:
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("schema_version")
    if version == "1.0":
        return SnapshotDocumentV1.model_validate(payload)
    if version == "1.1":
        return SnapshotDocument.model_validate(payload)
    raise UnsupportedSnapshotVersionError(
        f"Unsupported snapshot schema version: {version!r}"
    )
```

Wrap JSON/Pydantic errors with fixed safe summaries; do not include payload fragments.

- [ ] **Step 5: Implement canonical serialization and IDs**

```python
def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def stable_id(prefix: str, *parts: object) -> str:
    material = canonical_json(list(parts)).encode("utf-8")
    return f"{prefix}-{sha256(material).hexdigest()[:24]}"
```

Reject unsafe ID prefixes with `^[a-z][a-z0-9-]{0,31}$`.

- [ ] **Step 6: Implement RFC 6901 subset and EvidenceBuilder**

Support object keys and list indexes; decode `~1` to `/` and `~0` to `~`; reject invalid escape sequences, negative indexes and missing paths.

`EvidenceBuilder.at(pointer, evidence_type)`:

1. resolves the pointer;
2. canonicalizes non-string values;
3. uses `Redactor.redact_text()` or `redact_url()` for URL evidence types;
4. clips to the configured excerpt limit;
5. assigns a stable Evidence ID from digest, pointer and type;
6. caches by `(pointer, evidence_type)` so repeated facts reuse one Evidence.

- [ ] **Step 7: Run Task 5 verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_snapshot_adapter.py backend\tests\knowledge\test_ids.py backend\tests\knowledge\test_evidence.py -q
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\knowledge backend\tests\knowledge
.\.venv\Scripts\python.exe -m mypy -p ai_ui_explorer.knowledge
```

Expected: all commands PASS.

- [ ] **Step 8: Commit Task 5**

```powershell
git add backend/src/ai_ui_explorer/knowledge/snapshot_adapter.py backend/src/ai_ui_explorer/knowledge/ids.py backend/src/ai_ui_explorer/knowledge/evidence.py backend/tests/knowledge/test_snapshot_adapter.py backend/tests/knowledge/test_ids.py backend/tests/knowledge/test_evidence.py
git commit -m "feat: add deterministic knowledge provenance"
```

---

### Task 6: Deterministic Knowledge Package Builder

**Files:**

- Create: `backend/src/ai_ui_explorer/knowledge/builder.py`
- Create: `backend/tests/knowledge/test_builder.py`
- Modify: `backend/tests/knowledge/factories.py`

**Interfaces:**

- Produces: `KnowledgePackageBuilder`
- Produces: `build(manifest: ApplicationManifest, snapshot: AnySnapshotDocument, limits: KnowledgeLimits | None = None) -> KnowledgePackage`
- Consumed by: Task 7

- [ ] **Step 1: Write failing end-to-end mapping tests**

Test a complete 1.1 snapshot:

```python
def test_builder_maps_entities_facts_evidence_and_locators() -> None:
    package = KnowledgePackageBuilder().build(
        manifest=make_manifest(),
        snapshot=make_snapshot_with_locators(),
    )

    assert package.status == "completed"
    assert package.application.application_id == "example-app"
    assert {entity.entity_type for entity in package.entities} == {
        "page", "frame", "element"
    }
    assert package.locator_candidates
    assert package.facts
    assert package.inferences == []
    assert all(fact.evidence_refs for fact in package.facts)
```

Also test:

- Page/Frame/Element relationships use `object_ref`;
- Fact predicates are controlled;
- all facts resolve through Evidence JSON Pointers;
- locator ordering and metadata are preserved;
- unsupported Module/Action/Workflow/Permission/DataScope/ChangeHistory appear as gaps;
- 1.0 creates `snapshot_version_limited`;
- partial snapshot creates `collection_truncated` and package status partial;
- no identity produces an `identity_not_available` gap rather than an inferred identity;
- final URL on authentication origin does not produce target Page facts;
- outside-origin request fails;
- repeated build outputs the same model dump.

- [ ] **Step 2: Run builder tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_builder.py -q
```

Expected: FAIL because `KnowledgePackageBuilder` does not exist.

- [ ] **Step 3: Implement origin and run-state mapping**

Rules:

- requested URL outside `allowed_origins`: raise `KnowledgeBuildError`;
- final URL on target origin and a fresh completed snapshot: `access_status="public"`;
- final URL on authentication origin: `access_status="authentication_required"` only when an explicit redirect/access error supports it; otherwise `unknown`;
- anti-automation/rate-limit/permission codes map only from a controlled error-code table;
- incomplete source maps collection and exploration to partial;
- content status remains `insufficient_evidence` unless an explicit Builder input proves expected content; Sprint 2 has no such input.

Use an empty IdentityContext with `status="not_provided"`; do not call it anonymous or infer a role.

- [ ] **Step 4: Implement deterministic entity mapping**

Create:

- one Page from `/source` and `/page`;
- Frame entities in traversal order;
- Element entities in `(frame traversal_index, element traversal_index)` order.

Entity IDs use `snapshot_id` plus exact source pointer. Set `match_hints` only from non-sensitive values such as normalized final URL, Frame ancestry, tag, role, test id and locator parameters; mark them as hints, not identity.

- [ ] **Step 5: Implement atomic observed facts**

Map finite facts for:

- Page: requested/final URL、title、language、viewport;
- Frame: parent、name、URL、status、depth、truncated;
- Element: located_in、tag、role、accessible_name、text、visible、enabled、checked、selected、expanded and whitelisted attributes;
- Locator: locates Element、strategy、uniqueness、stability and recommended status;
- Exploration: source snapshot、collection status and access/content status.

Every Fact is created through one helper:

```python
def _fact(
    *,
    subject_ref: str,
    predicate: Predicate,
    pointer: str,
    observed_at: datetime,
    value: FactValue | None = None,
    object_ref: str | None = None,
) -> Fact:
    evidence = evidence_builder.at(pointer, predicate.value)
    return Fact(
        fact_id=stable_id(
            "fact",
            subject_ref,
            predicate.value,
            value,
            object_ref,
            evidence.evidence_id,
        ),
        subject_ref=subject_ref,
        predicate=predicate,
        value=value,
        object_ref=object_ref,
        evidence_refs=[evidence.evidence_id],
        observed_at=observed_at,
    )
```

Never create Facts for missing values.

- [ ] **Step 6: Implement locators, observations, and gaps**

- Convert 1.1 candidates one-to-one, replacing snapshot references with knowledge Entity/Evidence references.
- Convert 1.0 hints and bounds conservatively; set CSS/XPath gap.
- Generate Observations only from a controlled mapping of explicit source error codes.
- Generate gaps for unsupported future entities, unavailable identity, version limitation and collection truncation.
- Keep `inferences=[]`.

- [ ] **Step 7: Enforce deterministic ordering and statistics**

Sort:

- entities by entity type and source pointer;
- locators by Element source order and rank;
- evidence by JSON Pointer and type;
- facts by subject, predicate and ID;
- observations and gaps by subject, reason/type and ID.

Build statistics only from final lists. Validate the complete `KnowledgePackage` before returning.

- [ ] **Step 8: Run Task 6 verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_builder.py backend\tests\knowledge\test_models.py -q
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\knowledge backend\tests\knowledge
.\.venv\Scripts\python.exe -m mypy -p ai_ui_explorer.knowledge
```

Expected: all commands PASS.

- [ ] **Step 9: Commit Task 6**

```powershell
git add backend/src/ai_ui_explorer/knowledge/builder.py backend/tests/knowledge/test_builder.py backend/tests/knowledge/factories.py
git commit -m "feat: build deterministic application knowledge"
```

---

### Task 7: Knowledge Budgets, Atomic Writer, and CLI

**Files:**

- Create: `backend/src/ai_ui_explorer/knowledge/writer.py`
- Create: `backend/src/ai_ui_explorer/knowledge/cli.py`
- Create: `backend/tests/knowledge/test_writer.py`
- Create: `backend/tests/knowledge/test_cli.py`
- Modify: `backend/src/ai_ui_explorer/knowledge/builder.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.lock` only if dependency metadata synchronization changes the locked file

**Interfaces:**

- Produces: `compact_knowledge_package(package: KnowledgePackage) -> KnowledgePackage`
- Produces: `write_knowledge_package(package: KnowledgePackage, output_dir: Path) -> Path`
- Produces: console command `ai-ui-knowledge`
- Exit codes: 0 complete、1 failure、2 partial

- [ ] **Step 1: Write failing budget tests**

Test each approved count limit and the 50 MB limit. Require:

- deterministic tail truncation;
- `partial` status;
- a `collection_truncated` gap;
- statistics and stop reasons match final records;
- all references remain closed;
- unreferenced Evidence is pruned;
- mandatory metadata that cannot fit raises `KnowledgePackageTooLargeError`.

- [ ] **Step 2: Write failing Writer tests**

Require:

```python
def test_writer_creates_schema_valid_atomic_file(tmp_path: Path) -> None:
    output = write_knowledge_package(make_knowledge_package(), tmp_path)
    assert output == tmp_path / "knowledge-package.json"
    assert not list(tmp_path.glob("*.tmp"))
    KnowledgePackage.model_validate_json(output.read_text(encoding="utf-8"))
```

Monkeypatch replacement/write failure and assert no final or temporary artifact remains.
If `knowledge-package.json` already exists, an identical byte sequence is an
idempotent success; different content must raise `KnowledgePackageExistsError`
and preserve the existing immutable file.

- [ ] **Step 3: Write failing CLI tests**

Test:

- manifest + complete snapshot => 0 and valid file;
- partial source => 2 and valid partial file;
- invalid manifest/snapshot/unknown version => 1 and no output;
- usage error => parser exit code and no output;
- stderr never contains synthetic secret or page body;
- all limit flags reject out-of-range values.

- [ ] **Step 4: Run Task 7 tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_writer.py backend\tests\knowledge\test_cli.py -q
```

Expected: FAIL because Writer and CLI do not exist.

- [ ] **Step 5: Apply count budgets during Builder construction**

Use a deterministic budget counter. When a list reaches its maximum:

- stop adding that record type;
- record its stop reason once;
- retain existing valid records;
- ensure a `collection_truncated` gap exists, replacing the last non-truncation gap if the gap budget is already full.

Do not generate a record and then silently discard its required Evidence.

- [ ] **Step 6: Implement dependency-aware JSON compaction**

For the final byte budget, remove deterministic tails in this order:

1. non-required Observations;
2. low-ranked Locator candidates;
3. non-relationship Facts;
4. tail Element entities and their Facts/Locators.

After each removal:

- compute the reference closure;
- prune Evidence not referenced by any remaining Fact/Locator/Observation/Inference/Gap;
- update statistics;
- set partial and output-size stop reason;
- preserve the truncation gap;
- revalidate the complete model.

Never remove Application、ExplorationRun、Page、root Frame or the truncation gap. If mandatory metadata alone exceeds 50 MB, raise.

- [ ] **Step 7: Implement atomic Writer**

Mirror the proven Snapshot writer:

```python
def write_knowledge_package(
    package: KnowledgePackage,
    output_dir: Path,
) -> Path:
    compacted = compact_knowledge_package(package)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "knowledge-package.json"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(
                canonical_json(compacted.model_dump(mode="json"))
            )
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        serialized = temporary_path.read_text(encoding="utf-8")
        payload = json.loads(serialized)
        KnowledgePackage.model_validate(payload)
        Draft202012Validator(load_committed_knowledge_schema()).validate(payload)
        if output_path.exists():
            if output_path.read_bytes() == temporary_path.read_bytes():
                temporary_path.unlink()
                temporary_path = None
                return output_path
            raise KnowledgePackageExistsError(
                "knowledge-package.json already contains a different package"
            )
        temporary_path.replace(output_path)
        temporary_path = None
        return output_path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
```

Move the already locked `jsonschema==4.25.1` entry from the development-only
dependency group into project runtime dependencies. Writer loads the packaged,
committed Knowledge Package Schema through `importlib.resources` and validates
the exact serialized payload before replacement. Tests still enforce exact
model-to-committed-Schema parity.

- [ ] **Step 8: Implement safe CLI**

Arguments:

```text
--manifest PATH
--snapshot PATH
--output PATH
--max-evidence-chars 1..10000
--max-locators-per-element 1..100
--max-facts 1..1000000
--max-observations 0..10000
--max-knowledge-gaps 1..10000
--max-json-bytes 65536..524288000
```

Flow:

1. parse paths and non-sensitive limits;
2. load manifest;
3. load snapshot by version;
4. build package;
5. compact and atomically write;
6. print only output path, package status and non-sensitive counts;
7. return 0 or 2;
8. on known errors print fixed redacted summaries and return 1.

Register:

```toml
[project.scripts]
ai-ui-snapshot = "ai_ui_explorer.snapshot.cli:main"
ai-ui-knowledge = "ai_ui_explorer.knowledge.cli:main"
```

- [ ] **Step 9: Run Task 7 verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge -q
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\knowledge backend\tests\knowledge
.\.venv\Scripts\python.exe -m mypy -p ai_ui_explorer.knowledge
```

Expected: all commands PASS.

- [ ] **Step 10: Commit Task 7**

```powershell
git add backend/src/ai_ui_explorer/knowledge/writer.py backend/src/ai_ui_explorer/knowledge/cli.py backend/src/ai_ui_explorer/knowledge/builder.py backend/tests/knowledge/test_writer.py backend/tests/knowledge/test_cli.py backend/pyproject.toml backend/requirements.lock
git commit -m "feat: add bounded knowledge package cli"
```

Do not add `backend/requirements.lock` if its content does not change.

---

### Task 8: Packaging, Documentation, and Full Acceptance

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `README.md`
- Modify: `docs/03-knowledge-model.md`
- Modify: `docs/07-roadmap.md`
- Modify: `docs/superpowers/specs/2026-07-30-application-knowledge-model-design.md` only if implementation reveals a confirmed contract clarification
- Modify: `scripts/check.ps1`
- Modify: `.gitignore` only if the chosen output directory is not already covered
- Create: `backend/tests/fixtures/knowledge/application-manifest.json`
- Create: `backend/tests/knowledge/test_end_to_end.py`

**Interfaces:**

- Packages: `knowledge/schema/*.json`
- Documents: Snapshot 1.1 and `ai-ui-knowledge`
- Verifies: complete local Snapshot 1.1 -> Knowledge Package flow

- [ ] **Step 1: Write failing packaging and end-to-end tests**

Test installed package resources:

```python
def test_packaged_schemas_are_available() -> None:
    root = resources.files("ai_ui_explorer")
    assert root.joinpath(
        "snapshot/schema/snapshot-v1.1.schema.json"
    ).is_file()
    assert root.joinpath(
        "knowledge/schema/knowledge-package-v1.schema.json"
    ).is_file()
```

End-to-end test:

1. collect the local locator fixture with real Chromium;
2. write Snapshot 1.1;
3. load the fixture Application Manifest;
4. run the Knowledge CLI;
5. validate the output model and Schema;
6. resolve every Fact evidence pointer;
7. assert locators include semantic, structural and position tiers;
8. assert `inferences == []`;
9. scan serialized output for synthetic password/token/input values.

- [ ] **Step 2: Run end-to-end test and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_end_to_end.py -q
```

Expected: FAIL until packaging and the fixture manifest are complete.

- [ ] **Step 3: Package all Schemas**

Update:

```toml
[tool.setuptools.package-data]
"ai_ui_explorer" = [
    "py.typed",
    "snapshot/schema/*.json",
    "knowledge/schema/*.json",
]
```

Verify that `jsonschema==4.25.1` remains exactly locked after it is promoted to
runtime dependency metadata. Regenerate the lock only if the repository's
existing lock workflow detects a metadata difference; do not upgrade unrelated
packages.

- [ ] **Step 4: Add exact Schema parity to the quality gate**

Add a backend test or a small checked Python module invoked by `scripts/check.ps1` that compares:

- Snapshot 1.1 model Schema;
- Application Manifest Schema;
- Knowledge Package Schema;

against their committed JSON files. Keep Snapshot 1.0 as an immutable compatibility artifact and validate it against a known legacy fixture.

- [ ] **Step 5: Update documentation**

README must include:

- current implemented status;
- Snapshot 1.1 output and 1.0 compatibility;
- manifest example;
- `ai-ui-knowledge` command;
- exit codes;
- output path and Git-ignore warning;
- deterministic and partial-result semantics;
- locator reliability tiers;
- explicit statement that inference、test generation、code generation、database、LLM and human login runtime are not implemented.

`docs/03-knowledge-model.md` must replace the baseline-only wording with implemented entities and evidence boundaries. `docs/07-roadmap.md` marks Sprint 2 complete only after all acceptance commands pass.

- [ ] **Step 6: Run focused end-to-end acceptance**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\knowledge\test_end_to_end.py -q
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot backend\tests\knowledge -q
```

Expected: PASS.

- [ ] **Step 7: Run the complete repository quality gate**

Run:

```powershell
.\scripts\check.cmd
```

Expected:

- all backend tests pass;
- Ruff passes;
- mypy passes;
- frontend component tests pass;
- ESLint passes;
- TypeScript passes;
- Prettier passes;
- production frontend build passes;
- all committed Schema parity checks pass.

- [ ] **Step 8: Perform deterministic and partial CLI acceptance**

Using only the local controlled fixture:

1. generate Snapshot 1.1 twice with fixed test data;
2. generate two knowledge packages from identical manifest/snapshot inputs;
3. compare SHA-256 values and require equality;
4. run with `--max-facts 1`;
5. require exit 2, `status="partial"` and `collection_truncated`;
6. validate both outputs with the committed Schema;
7. scan for forbidden synthetic secret values;
8. confirm no screenshot、network body、Cookie、Storage State or extra output file exists.

- [ ] **Step 9: Inspect Git scope**

Run:

```powershell
git status --short
git diff --check
git diff --stat
```

Expected: only Task 8 implementation, tests and documentation remain; no `exploration-output/`、`knowledge-exports/`、browser binary、secret or unrelated user file is tracked.

- [ ] **Step 10: Commit Task 8**

```powershell
git add backend/pyproject.toml backend/tests/fixtures/knowledge/application-manifest.json backend/tests/knowledge/test_end_to_end.py README.md docs/03-knowledge-model.md docs/07-roadmap.md scripts/check.ps1 .gitignore
git commit -m "docs: complete sprint 2 knowledge workflow"
```

Do not add a file from the command if it has no intentional diff.

---

## Final Review Gates

After Task 8, use `superpowers:requesting-code-review` for two independent review passes:

1. **Specification compliance:** compare every approved design requirement and every task acceptance criterion with the implementation and tests.
2. **Code quality and security:** inspect reference closure, deterministic ordering, Pydantic invariants, selector safety, redaction-before-modeling, atomic writes, CLI error disclosure and backward compatibility.

Any finding must be classified as Critical、Important or Minor. Critical and Important findings must be fixed with a failing regression test and independently re-reviewed before completion.

Finally use `superpowers:verification-before-completion` and run `scripts\check.cmd` fresh. Do not claim Sprint 2 complete from earlier or partial test output.
