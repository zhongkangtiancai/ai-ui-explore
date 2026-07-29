# Sprint 1 Structured Page Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Chromium-based CLI that passively captures bounded, redacted JSON snapshots of a page, its frames, and visible nested scroll containers.

**Architecture:** Add a FastAPI-independent `ai_ui_explorer.snapshot` package. The CLI calls a synchronous collector, which owns a Playwright browser adapter, bounded scrolling, redaction, Pydantic snapshot models, deterministic compaction, and atomic JSON writing. Real-browser tests use two local HTTP origins and synthetic data.

**Tech Stack:** Python 3.12, Playwright 1.61.0 synchronous API, Chromium, Pydantic 2.13.4, pytest 8.4.1, Ruff, mypy.

## Global Constraints

- Only Chromium is supported in Sprint 1.
- Default total timeout is 60,000 ms.
- Default maximum is 50 frames, 20 scroll containers per frame, 30 rounds per container, 5,000 elements, 500 characters per text segment, and 10 MiB serialized JSON.
- Collection may navigate and scroll, but must not click, type, submit, expand, paginate, or call an LLM.
- Do not capture screenshots, request bodies, response bodies, full HTML, cookies, tokens, passwords, or storage state.
- Partial frame/container failures produce a usable `partial` snapshot and CLI exit code `2`.
- Secrets are not accepted as CLI arguments.
- All new behavior follows RED → GREEN → REFACTOR; each production change must be preceded by a failing test.
- Browser binaries live under `.playwright-browsers/` and remain outside Git.
- Every emitted snapshot must validate against the committed JSON Schema.

---

## File Map

### Production

- `backend/src/ai_ui_explorer/snapshot/models.py`: Pydantic snapshot contract and limits.
- `backend/src/ai_ui_explorer/snapshot/redaction.py`: text, mapping, URL, and error redaction.
- `backend/src/ai_ui_explorer/snapshot/writer.py`: deterministic compaction, Schema validation, and atomic JSON output.
- `backend/src/ai_ui_explorer/snapshot/browser.py`: Playwright lifecycle, frame traversal, and raw observation extraction.
- `backend/src/ai_ui_explorer/snapshot/scrolling.py`: scroll-container discovery and bounded scroll loop.
- `backend/src/ai_ui_explorer/snapshot/collector.py`: end-to-end orchestration and partial-failure handling.
- `backend/src/ai_ui_explorer/snapshot/cli.py`: public console entry point and exit codes.
- `backend/src/ai_ui_explorer/snapshot/schema/snapshot-v1.schema.json`: generated public contract.

### Tests and fixtures

- `backend/tests/snapshot/test_models.py`
- `backend/tests/snapshot/test_redaction.py`
- `backend/tests/snapshot/test_writer.py`
- `backend/tests/snapshot/test_browser.py`
- `backend/tests/snapshot/test_scrolling.py`
- `backend/tests/snapshot/test_collector.py`
- `backend/tests/snapshot/test_cli.py`
- `backend/tests/snapshot/conftest.py`
- `backend/tests/snapshot/factories.py`
- `backend/tests/snapshot/fakes.py`
- `backend/tests/fixtures/snapshot_site/primary/index.html`
- `backend/tests/fixtures/snapshot_site/primary/same-frame.html`
- `backend/tests/fixtures/snapshot_site/primary/nested-frame.html`
- `backend/tests/fixtures/snapshot_site/secondary/cross-frame.html`

### Project integration

- `backend/pyproject.toml`: Playwright pin, console script, Schema package data.
- `backend/requirements.lock`: verified transitive dependency lock.
- `.gitignore`: local Chromium directory.
- `scripts/bootstrap.ps1`: explicit local Chromium installation.
- `scripts/check.ps1`: local browser path and full test suite.
- `README.md`: install and CLI usage.
- `docs/07-roadmap.md`: mark Sprint 1 as implemented only after acceptance passes.

---

### Task 1: Versioned Snapshot Contract

**Files:**
- Create: `backend/src/ai_ui_explorer/snapshot/__init__.py`
- Create: `backend/src/ai_ui_explorer/snapshot/models.py`
- Create: `backend/tests/snapshot/__init__.py`
- Create: `backend/tests/snapshot/factories.py`
- Create: `backend/tests/snapshot/test_models.py`

**Interfaces:**
- Produces: `SnapshotLimits`, `Bounds`, `LocatorHint`, `ElementSnapshot`, `ScrollResult`,
  `SnapshotError`, `FrameSnapshot`, `SourceSnapshot`, `PageSnapshot`, `SnapshotStatistics`,
  `SnapshotDocument`.
- Produces: `SnapshotDocument.status: Literal["completed", "partial"]`.
- Produces: `SnapshotDocument.to_schema() -> dict[str, object]`.
- Produces test helpers: `make_element(**overrides)`, `make_frame(**overrides)`,
  `make_snapshot(**overrides)`, and `make_oversized_snapshot(max_json_bytes: int)`.

- [ ] **Step 1: Write failing model tests**

```python
def test_snapshot_limits_use_approved_defaults() -> None:
    limits = SnapshotLimits()
    assert limits.total_timeout_ms == 60_000
    assert limits.max_frames == 50
    assert limits.max_scroll_containers_per_frame == 20
    assert limits.max_scroll_rounds_per_container == 30
    assert limits.max_elements == 5_000
    assert limits.max_text_chars == 500
    assert limits.max_json_bytes == 10 * 1024 * 1024


def test_snapshot_rejects_completed_status_when_truncated() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(status="completed", truncated=True)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_models.py -v
```

Expected: collection fails because `ai_ui_explorer.snapshot.models` does not exist.

- [ ] **Step 3: Implement the exact model surface**

Use strict Pydantic models with these required fields:

```python
class SnapshotLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    total_timeout_ms: int = Field(default=60_000, ge=1_000, le=600_000)
    max_frames: int = Field(default=50, ge=1, le=500)
    max_scroll_containers_per_frame: int = Field(default=20, ge=0, le=200)
    max_scroll_rounds_per_container: int = Field(default=30, ge=0, le=500)
    max_elements: int = Field(default=5_000, ge=1, le=100_000)
    max_text_chars: int = Field(default=500, ge=0, le=10_000)
    max_json_bytes: int = Field(default=10 * 1024 * 1024, ge=64 * 1024, le=100 * 1024 * 1024)


class SnapshotDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
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

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "completed" and (self.truncated or self.errors):
            raise ValueError("completed snapshots cannot contain errors or truncation")
        return self

    @classmethod
    def to_schema(cls) -> dict[str, object]:
        return cast(dict[str, object], cls.model_json_schema())
```

Define the nested models exactly as follows; every model uses
`ConfigDict(extra="forbid")`, and value bounds use Pydantic `Field`:

```python
class Bounds(BaseModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class LocatorHint(BaseModel):
    strategy: Literal["role", "label", "testid", "id"]
    value: str


class ElementSnapshot(BaseModel):
    element_id: str
    frame_id: str
    traversal_index: int = Field(ge=0)
    tag: str
    role: str | None
    accessible_name: str | None
    text: str | None
    attributes: dict[str, str]
    visible: bool
    enabled: bool | None
    checked: bool | None
    selected: bool | None
    expanded: bool | None
    bounds: Bounds | None
    locator_hints: list[LocatorHint]


class ScrollResult(BaseModel):
    container_id: str
    label: str
    rounds: int = Field(ge=0)
    discovered_elements: int = Field(ge=0)
    restored: bool
    truncated: bool
    stop_reason: Literal["stable", "end_reached", "round_limit", "deadline", "detached", "error"]


class SnapshotError(BaseModel):
    scope: str
    error_code: str
    message: str
    recoverable: bool
    occurred_at: datetime


class FrameSnapshot(BaseModel):
    frame_id: str
    parent_frame_id: str | None
    traversal_index: int = Field(ge=0)
    depth: int = Field(ge=0)
    name: str
    url: str
    status: Literal["completed", "partial", "failed"]
    text_summary: str
    elements: list[ElementSnapshot]
    scroll_results: list[ScrollResult]
    errors: list[SnapshotError]
    truncated: bool
    stop_reason: str | None
    redaction_count: int = Field(ge=0)


class SourceSnapshot(BaseModel):
    requested_url: str
    final_url: str
    title: str


class PageSnapshot(BaseModel):
    main_frame_id: str
    viewport_width: int = Field(ge=1)
    viewport_height: int = Field(ge=1)
    language: str | None


class SnapshotStatistics(BaseModel):
    frame_count: int = Field(ge=0)
    completed_frame_count: int = Field(ge=0)
    failed_frame_count: int = Field(ge=0)
    element_count: int = Field(ge=0)
    scroll_container_count: int = Field(ge=0)
    redaction_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
```

Use UTC datetimes and validate that `completed_at >= started_at`, element counts do not exceed the
approved limit, and `page.main_frame_id` exists in `frames`.

Implement `factories.py` with fixed UUIDs and UTC timestamps. `make_element` returns one visible,
enabled button; `make_frame` returns one completed root frame containing that element;
`make_snapshot` returns a completed document with no errors; overrides are applied only to the
top-level object. `make_oversized_snapshot` adds deterministic 500-character text summaries and
elements in ascending traversal order until the serialized form exceeds the supplied byte limit.

- [ ] **Step 4: Run model tests and static checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_models.py -v
.\.venv\Scripts\python.exe -m ruff check backend\src\ai_ui_explorer\snapshot\models.py backend\tests\snapshot\test_models.py
.\.venv\Scripts\python.exe -m mypy backend\src\ai_ui_explorer\snapshot\models.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/snapshot backend/tests/snapshot
git commit -m "feat: define snapshot data contract"
```

---

### Task 2: Redaction Before Modeling

**Files:**
- Create: `backend/src/ai_ui_explorer/snapshot/redaction.py`
- Create: `backend/tests/snapshot/test_redaction.py`

**Interfaces:**
- Produces: `RedactionResult(value: str, count: int, categories: frozenset[str])`.
- Produces: `Redactor.redact_text(value: str) -> RedactionResult`.
- Produces: `RedactionSummary(count: int, categories: frozenset[str])`.
- Produces: `Redactor.redact_mapping(values: Mapping[str, str]) -> tuple[dict[str, str], RedactionSummary]`.
- Produces: `Redactor.redact_url(value: str) -> RedactionResult`.
- Produces: `Redactor.redact_error(value: str) -> RedactionResult`.

- [ ] **Step 1: Write failing redaction tests**

```python
@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("password=hunter2", "hunter2"),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("身份证 11010519491231002X", "11010519491231002X"),
        ("银行卡 6222021001112223333", "6222021001112223333"),
        ("手机号 13800138000", "13800138000"),
        ("邮箱 demo@example.com", "demo@example.com"),
    ],
)
def test_redactor_removes_sensitive_values(raw: str, secret: str) -> None:
    result = Redactor().redact_text(raw)
    assert secret not in result.value
    assert result.count >= 1


def test_redactor_removes_sensitive_query_values() -> None:
    result = Redactor().redact_url("https://example.test/path?token=secret&view=list#section")
    assert "secret" not in result.value
    assert "view=list" in result.value
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_redaction.py -v
```

Expected: import failure for the missing `redaction` module.

- [ ] **Step 3: Implement ordered, category-aware rules**

Implement fixed sensitive-key matching for `password`, `passwd`, `secret`, `token`, `cookie`,
`authorization`, and `api_key`; then apply compiled patterns for bearer tokens, Chinese ID numbers,
bank cards, mainland mobile numbers, and email addresses. Replace values with category markers such
as `[REDACTED:TOKEN]`. URL redaction must parse with `urllib.parse`, redact sensitive query values,
drop user information, preserve non-sensitive query values, and never log the original on failure.

- [ ] **Step 4: Verify GREEN and regression safety**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_redaction.py -v
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Expected: all pass and none of the test secrets appear in captured test output.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/snapshot/redaction.py backend/tests/snapshot/test_redaction.py
git commit -m "feat: redact snapshot observations"
```

---

### Task 3: Deterministic Compaction and Atomic Writer

**Files:**
- Create: `backend/src/ai_ui_explorer/snapshot/writer.py`
- Create: `backend/tests/snapshot/test_writer.py`
- Create: `backend/src/ai_ui_explorer/snapshot/schema/snapshot-v1.schema.json`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `compact_snapshot(snapshot: SnapshotDocument) -> SnapshotDocument`.
- Produces: `write_snapshot(snapshot: SnapshotDocument, output_dir: Path) -> Path`.
- Writes exactly `<output_dir>/snapshot.json`.

- [ ] **Step 1: Write failing writer tests**

```python
def test_writer_creates_schema_valid_json_atomically(tmp_path: Path) -> None:
    output = write_snapshot(make_snapshot(), tmp_path / "result")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert output.name == "snapshot.json"
    assert payload["schema_version"] == "1.0"
    assert not list(output.parent.glob("*.tmp"))


def test_compaction_marks_snapshot_partial_and_keeps_within_limit() -> None:
    snapshot = make_oversized_snapshot(max_json_bytes=65_536)
    compacted = compact_snapshot(snapshot)
    encoded = compacted.model_dump_json().encode("utf-8")
    assert len(encoded) <= 65_536
    assert compacted.status == "partial"
    assert compacted.truncated is True
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_writer.py -v
```

Expected: import failure for `writer`.

- [ ] **Step 3: Implement stable compaction and atomic replace**

Compaction order is fixed:

1. Shorten frame text summaries from the highest traversal index backward.
2. Remove elements from the highest traversal index and highest element index backward.
3. Add one `output_size_limit` recoverable error.
4. Set `status="partial"` and `truncated=True`.
5. Raise `SnapshotTooLargeError` if the contract plus error metadata alone cannot fit.

Serialize with sorted keys and UTF-8, write a sibling temporary file, flush and close it, validate
the file back through `SnapshotDocument.model_validate_json`, then use `Path.replace()` for the final
atomic move. Generate `snapshot-v1.schema.json` from `SnapshotDocument.to_schema()` with sorted keys.
Add `snapshot/schema/*.json` to setuptools package data.

- [ ] **Step 4: Verify GREEN and committed Schema parity**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_writer.py -v
.\.venv\Scripts\python.exe -c "from ai_ui_explorer.snapshot.models import SnapshotDocument; import json, pathlib; p=pathlib.Path('backend/src/ai_ui_explorer/snapshot/schema/snapshot-v1.schema.json'); assert json.loads(p.read_text(encoding='utf-8')) == SnapshotDocument.to_schema()"
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/snapshot backend/tests/snapshot/test_writer.py backend/pyproject.toml
git commit -m "feat: write bounded snapshot documents"
```

---

### Task 4: Playwright Runtime and Frame Observation

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.lock`
- Modify: `.gitignore`
- Modify: `scripts/bootstrap.ps1`
- Modify: `scripts/check.ps1`
- Create: `backend/src/ai_ui_explorer/snapshot/browser.py`
- Create: `backend/tests/snapshot/conftest.py`
- Create: `backend/tests/snapshot/test_browser.py`
- Create: `backend/tests/fixtures/snapshot_site/primary/index.html`
- Create: `backend/tests/fixtures/snapshot_site/primary/same-frame.html`
- Create: `backend/tests/fixtures/snapshot_site/primary/nested-frame.html`
- Create: `backend/tests/fixtures/snapshot_site/secondary/cross-frame.html`

**Interfaces:**
- Consumes: `SnapshotLimits`.
- Produces:
  `BrowserObservationSource.collect(url: str, limits: SnapshotLimits) -> RawPageObservation`
  protocol method.
- Produces: `PlaywrightBrowserSource.collect(url: str, limits: SnapshotLimits) -> RawPageObservation`.
- Produces: `RawFrameObservation` and `RawElementObservation` typed dataclasses.
- Produces test fixtures: `primary_url: str`, `secondary_url: str`.

- [ ] **Step 1: Add the failing real-browser test**

```python
def test_browser_observes_main_same_origin_and_cross_origin_frames(primary_url: str) -> None:
    source = PlaywrightBrowserSource(headless=True)
    observation = source.collect(primary_url, SnapshotLimits())
    names = {frame.name for frame in observation.frames}
    assert {"main", "same-origin", "nested", "cross-origin"} <= names
    assert any(element.accessible_name == "保存草稿" for frame in observation.frames for element in frame.elements)
```

The fixture page must contain synthetic text, same-origin and secondary-origin iframes, a nested
iframe, buttons, links, text inputs, a password input with a fake value, and a delayed removable
iframe.

In `conftest.py`, start two `ThreadingHTTPServer` instances bound to `127.0.0.1` on OS-assigned
ports. Serve `primary/` and `secondary/` with a quiet `SimpleHTTPRequestHandler` subclass, inject the
secondary URL into the primary fixture through a query parameter, yield both URLs, and always call
`shutdown()`, `server_close()`, and `thread.join()` in fixture finalizers.

- [ ] **Step 2: Install the approved local dependency and verify RED**

After explicit execution approval for network/package actions:

```powershell
.\.venv\Scripts\python.exe -m pip install "playwright==1.61.0"
$env:PLAYWRIGHT_BROWSERS_PATH = (Join-Path (Get-Location) '.playwright-browsers')
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_browser.py -v
```

Expected test result: failure because `PlaywrightBrowserSource` is not implemented. The package and
browser installation are setup only; do not add production collection behavior before RED.

- [ ] **Step 3: Implement browser lifecycle and frame extraction**

Pin `playwright==1.61.0` in `backend/pyproject.toml`, regenerate the verified lock, and set
`PLAYWRIGHT_BROWSERS_PATH=<project>/.playwright-browsers` in bootstrap, check, and runtime scripts.
Bootstrap explicitly installs only `chromium`; ordinary CLI execution never downloads a browser.

Implement a synchronous context manager that always closes page, context, browser, and Playwright.
Navigate with `wait_until="domcontentloaded"` and a timeout bounded by the remaining global budget.
Traverse `page.frames` in stable parent-before-child order. Frame-level exceptions become raw
recoverable failures. Extract only:

- body `innerText` bounded before returning to Python;
- visible interactive elements selected from semantic HTML, `[role]`, `[tabindex]`, and form controls;
- allowlisted attributes;
- observable state, bounding box, accessible name, and locator hints.

Never evaluate or return `outerHTML`, input values, hidden input values, cookies, storage state,
screenshots, request bodies, or response bodies.

Use typed dataclasses with these fields:

```python
@dataclass(frozen=True, slots=True)
class RawLocatorHint:
    strategy: Literal["role", "label", "testid", "id"]
    value: str


@dataclass(frozen=True, slots=True)
class RawElementObservation:
    traversal_index: int
    tag: str
    role: str | None
    accessible_name: str | None
    text: str | None
    attributes: dict[str, str]
    visible: bool
    enabled: bool | None
    checked: bool | None
    selected: bool | None
    expanded: bool | None
    bounds: Bounds | None
    locator_hints: tuple[RawLocatorHint, ...]


@dataclass(frozen=True, slots=True)
class RawErrorObservation:
    scope: str
    error_code: str
    message: str
    recoverable: bool
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class RawScrollResult:
    container_id: str
    label: str
    rounds: int
    discovered_elements: int
    restored: bool
    truncated: bool
    stop_reason: Literal["stable", "end_reached", "round_limit", "deadline", "detached", "error"]


@dataclass(slots=True)
class RawFrameObservation:
    frame_id: str
    parent_frame_id: str | None
    traversal_index: int
    depth: int
    name: str
    url: str
    status: Literal["completed", "partial", "failed"]
    text_summary: str
    elements: list[RawElementObservation]
    scroll_results: list[RawScrollResult]
    errors: list[RawErrorObservation]
    truncated: bool
    stop_reason: str | None


@dataclass(slots=True)
class RawPageObservation:
    final_url: str
    title: str
    viewport_width: int
    viewport_height: int
    language: str | None
    frames: list[RawFrameObservation]
    errors: list[RawErrorObservation]
    deadline_reached: bool
```

Task 4 returns initial elements with empty `scroll_results`. Task 5 extends the implementation inside
the same open browser/context lifetime and populates additional elements and scroll results before
`collect()` returns. Raw dataclasses remain outside the Pydantic contract so the collector can redact
their strings before constructing final models.

- [ ] **Step 4: Verify GREEN and missing-browser behavior**

Run:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = (Join-Path (Get-Location) '.playwright-browsers')
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_browser.py -v
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m mypy backend\src\ai_ui_explorer
```

Add and pass a test that points `PLAYWRIGHT_BROWSERS_PATH` to an empty temporary directory and asserts
the raised `BrowserUnavailableError` contains the safe install command but no URL content or secret.

- [ ] **Step 5: Commit**

```powershell
git add .gitignore backend scripts/bootstrap.ps1 scripts/check.ps1
git commit -m "feat: collect initial frame observations"
```

---

### Task 5: Bounded Nested Scrolling

**Files:**
- Create: `backend/src/ai_ui_explorer/snapshot/scrolling.py`
- Create: `backend/tests/snapshot/test_scrolling.py`
- Modify: `backend/tests/fixtures/snapshot_site/primary/index.html`
- Modify: `backend/tests/fixtures/snapshot_site/primary/same-frame.html`

**Interfaces:**
- Consumes: Playwright `Frame`, `SnapshotLimits`, and remaining deadline.
- Produces: `discover_scroll_containers(frame: Frame, limit: int) -> list[ScrollContainer]`.
- Produces: `scroll_container(frame: Frame, container: ScrollContainer, max_rounds: int, deadline: float) -> RawScrollResult`.
- Produces: `collect_with_scrolling(frame: Frame, limits: SnapshotLimits, deadline: float) -> tuple[list[RawElementObservation], list[RawScrollResult]]`.
- Produces test helpers in `test_scrolling.py`:
  `collect_fixture(url: str, max_scroll_rounds_per_container: int) -> RawPageObservation`,
  `all_elements(observation: RawPageObservation) -> list[RawElementObservation]`, and
  `all_scroll_results(observation: RawPageObservation) -> list[RawScrollResult]`.

- [ ] **Step 1: Write failing finite and infinite scroll tests**

```python
def test_scrolling_discovers_elements_in_nested_container(primary_url: str) -> None:
    observation = collect_fixture(primary_url, max_scroll_rounds_per_container=10)
    names = {element.accessible_name for element in all_elements(observation)}
    assert "嵌套列表末项" in names


def test_infinite_container_stops_at_budget(primary_url: str) -> None:
    observation = collect_fixture(primary_url, max_scroll_rounds_per_container=3)
    infinite = next(item for item in all_scroll_results(observation) if item.label == "infinite-list")
    assert infinite.rounds == 3
    assert infinite.truncated is True
    assert infinite.stop_reason == "round_limit"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_scrolling.py -v
```

Expected: import failure for `scrolling`.

- [ ] **Step 3: Implement stable discovery and scroll loop**

Discover visible elements whose `scrollHeight > clientHeight + 1`, whose computed overflow permits
scrolling, and that have a non-zero bounding box. Include the document scrolling element as container
zero. Assign stable IDs from frame traversal index plus discovery index.

For each container:

1. Record the original `scrollTop`.
2. Move by `max(clientHeight * 0.8, 1)`.
3. Wait through Playwright for a bounded 100 ms settle interval.
4. Re-extract interactive observations and current `scrollHeight`.
5. Stop after two consecutive rounds with no new element signature and unchanged height.
6. Stop immediately on global deadline, container limit, detached element, or frame failure.
7. Restore original `scrollTop` in `finally`.

Use a signature from frame ID, tag, role, accessible name, allowlisted stable attributes, and rounded
bounds. Never click a load-more control.

- [ ] **Step 4: Verify GREEN and restoration**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_scrolling.py -v
```

Also assert in a real-browser test that every surviving fixture container returns to its original
`scrollTop` after collection.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/snapshot/scrolling.py backend/tests/snapshot/test_scrolling.py backend/tests/fixtures
git commit -m "feat: scan bounded scroll containers"
```

---

### Task 6: Collector Orchestration and Partial Results

**Files:**
- Create: `backend/src/ai_ui_explorer/snapshot/collector.py`
- Create: `backend/tests/snapshot/fakes.py`
- Create: `backend/tests/snapshot/test_collector.py`

**Interfaces:**
- Consumes: `BrowserObservationSource`, `Redactor`, `SnapshotLimits`, `write_snapshot`.
- Produces: `SnapshotCollector.collect(url: str, limits: SnapshotLimits) -> SnapshotDocument`.
- Produces: `CollectionFailedError` only when no valid top-level snapshot can be formed.
- Produces test double: `FakeSource`, implementing `BrowserObservationSource`, with
  `with_one_success_and_one_failure()` and `with_text(value: str)` constructors.

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_collector_keeps_successful_frames_when_one_frame_fails() -> None:
    source = FakeSource.with_one_success_and_one_failure()
    snapshot = SnapshotCollector(source=source).collect("https://example.test", SnapshotLimits())
    assert snapshot.status == "partial"
    assert snapshot.truncated is False
    assert len(snapshot.frames) == 2
    assert snapshot.frames[0].status == "completed"
    assert snapshot.frames[1].status == "failed"
    assert snapshot.errors[0].recoverable is True


def test_collector_redacts_before_snapshot_validation() -> None:
    source = FakeSource.with_text("token=super-secret")
    snapshot = SnapshotCollector(source=source).collect("https://example.test", SnapshotLimits())
    assert "super-secret" not in snapshot.model_dump_json()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_collector.py -v
```

Expected: import failure for `collector`.

- [ ] **Step 3: Implement orchestration**

Use an injected monotonic clock and UUID factory for deterministic unit tests. Enforce the global
deadline before navigation, before every frame, and before every container. Convert raw observations
to Pydantic models only after redaction. Sort frames and elements by traversal order, aggregate
redaction counts, errors, stop reasons, and statistics, and derive:

```python
partial = bool(errors) or any(frame.truncated for frame in frames)
status = "partial" if partial else "completed"
truncated = any(frame.truncated for frame in frames)
```

Navigation failure, missing browser, or inability to construct a valid root frame raises
`CollectionFailedError`; child frame and nested container failures remain recoverable.

`FakeSource` returns real raw dataclasses rather than mocks. Its one-failure variant returns a
completed root plus a failed child; its text variant returns one completed root containing the exact
provided text. This keeps collector tests focused on transformation and status derivation.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_collector.py -v
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot -q
```

Expected: all snapshot unit and browser tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/snapshot/collector.py backend/tests/snapshot/test_collector.py
git commit -m "feat: orchestrate page snapshot collection"
```

---

### Task 7: Public CLI and End-to-End Contract

**Files:**
- Create: `backend/src/ai_ui_explorer/snapshot/cli.py`
- Create: `backend/tests/snapshot/test_cli.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces console script: `ai-ui-snapshot = "ai_ui_explorer.snapshot.cli:main"`.
- Produces: `build_parser() -> argparse.ArgumentParser`.
- Produces:
  `main(argv: Sequence[str] | None = None, collector_factory: CollectorFactory = default_collector_factory) -> int`.
- Produces type alias: `CollectorFactory = Callable[[bool], SnapshotCollector]`.
- Writes: `<output>/snapshot.json`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_cli_returns_zero_for_complete_snapshot(tmp_path: Path) -> None:
    collector = FakeCollector(make_snapshot())
    result = main(
        ["--url", "https://example.test", "--output", str(tmp_path)],
        collector_factory=lambda headed: collector,
    )
    assert result == 0
    assert (tmp_path / "snapshot.json").exists()


def test_cli_returns_two_for_partial_snapshot(tmp_path: Path) -> None:
    collector = FakeCollector(make_snapshot(status="partial", truncated=True))
    result = main(
        ["--url", "https://example.test", "--output", str(tmp_path)],
        collector_factory=lambda headed: collector,
    )
    assert result == 2


def test_cli_has_no_secret_arguments() -> None:
    help_text = build_parser().format_help().lower()
    assert "password" not in help_text
    assert "cookie" not in help_text
    assert "token" not in help_text
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_cli.py -v
```

Expected: import failure for `cli`.

- [ ] **Step 3: Implement parser and exit mapping**

Arguments:

```text
--url (required)
--output (required)
--timeout-ms
--max-frames
--max-scroll-containers-per-frame
--max-scroll-rounds-per-container
--max-elements
--max-text-chars
--max-json-bytes
--headed
```

Validate URLs as HTTP or HTTPS only. Instantiate `SnapshotLimits`, run the collector, compact and
write the result, print only the output path/status/statistics, and map complete/partial/fatal to
`0/2/1`. Never print a raw Playwright exception, page text, or the unredacted requested URL.

Define `FakeCollector` in `test_cli.py` with `collect(url, limits)` returning its supplied
`SnapshotDocument`. The production default factory creates `PlaywrightBrowserSource` and
`SnapshotCollector`; tests inject the fake through `collector_factory`.

- [ ] **Step 4: Run unit and real end-to-end CLI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_cli.py -v
$env:PLAYWRIGHT_BROWSERS_PATH = (Join-Path (Get-Location) '.playwright-browsers')
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_cli.py::test_real_cli_collects_fixture -v
```

`test_real_cli_collects_fixture` uses `primary_url`, calls `main` with the production factory and a
temporary output directory, and asserts exit code `0` or `2`, Schema-valid JSON, and absence of every
synthetic secret. Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ai_ui_explorer/snapshot/cli.py backend/tests/snapshot/test_cli.py backend/pyproject.toml
git commit -m "feat: expose snapshot collection cli"
```

---

### Task 8: Windows Workflow, Documentation, and Full Acceptance

**Files:**
- Modify: `scripts/bootstrap.ps1`
- Modify: `scripts/check.ps1`
- Modify: `README.md`
- Modify: `docs/07-roadmap.md`
- Modify: `AGENTS.md`

**Interfaces:**
- `scripts/bootstrap.cmd` installs locked Python packages, frontend packages, and local Chromium.
- `scripts/check.cmd` runs all backend/frontend checks with the local browser path.
- README documents the exact CLI and data-safety boundary.

- [ ] **Step 1: Add a failing workflow assertion**

Add a test in `backend/tests/snapshot/test_cli.py` that reads `README.md`, `scripts/bootstrap.ps1`,
and `.gitignore` and asserts they respectively contain `ai-ui-snapshot`,
`python -m playwright install chromium`, and `.playwright-browsers/`.

- [ ] **Step 2: Run it and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\snapshot\test_cli.py::test_project_documents_snapshot_workflow -v
```

Expected: failure because the README and scripts do not yet expose the Sprint 1 workflow.

- [ ] **Step 3: Complete workflow and documentation**

Update bootstrap to set the project-local browser path and explicitly install Chromium after the
locked editable package. Update check to set the same path before backend tests. Document:

- installation and local Chromium disk impact;
- complete CLI example and exit codes;
- default budgets and how to tighten them;
- no screenshot/network body/login support;
- output sensitivity, Git exclusion, and retention responsibility;
- known limits for infinite scroll, virtualized lists, canvas, sandboxed frames, and dynamic content.

Do not update `AGENTS.md` current-state wording or mark the roadmap complete yet.

- [ ] **Step 4: Run full verification from a clean process**

Run:

```powershell
.\scripts\check.cmd
git diff --check
git status --short
```

Then run the local fixture acceptance twice and compare normalized snapshots after removing
`snapshot_id`, timestamps, and duration fields. Expected:

- backend tests, Ruff, mypy, frontend tests, ESLint, TypeScript, Prettier, and build all pass;
- both snapshots validate against the committed Schema;
- normalized static content is equal;
- no secret fixture values occur in output;
- no screenshot, HAR, trace, cookie, or storage-state file exists;
- only intentional source and documentation changes appear in Git.

After these checks pass, update `AGENTS.md` and `docs/07-roadmap.md` to describe Sprint 1 as
implemented bounded snapshot capture, not complete application exploration. Run `scripts\check.cmd`
and `git diff --check` once more before committing.

- [ ] **Step 5: Commit the completed Sprint**

```powershell
git add AGENTS.md README.md docs/07-roadmap.md scripts backend .gitignore
git commit -m "docs: complete structured snapshot sprint"
git status --short
```

Expected: clean working tree.

---

## Execution Checkpoints

After Tasks 3, 5, and 8:

1. Re-read the design against implemented behavior.
2. Run the complete snapshot test directory.
3. Inspect `git diff --check` and `git status --short`.
4. Stop if a test passes without first demonstrating the expected RED state.
5. Stop before any new network/package action that was not explicitly approved.

## Official Version Evidence

- [PyPI](https://pypi.org/project/playwright/) lists Playwright 1.61.0, uploaded 2026-06-29,
  with Windows x86-64 wheels and Python requirement `>=3.10`.
- [Playwright browser documentation](https://playwright.dev/python/docs/browsers) states that each
  library version requires matching browser binaries.
- The same official documentation defines `PLAYWRIGHT_BROWSERS_PATH` for a custom browser location
  and supports installing Chromium only.
