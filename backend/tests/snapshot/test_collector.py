"""Tests for raw-observation collection orchestration."""

import json
from uuid import UUID

import pytest

from ai_ui_explorer.snapshot.browser import RawLocatorCandidate
from ai_ui_explorer.snapshot.collector import CollectionFailedError, SnapshotCollector
from ai_ui_explorer.snapshot.models import LocatorStrategy, SnapshotLimits
from ai_ui_explorer.snapshot.redaction import CustomRedactionRule, Redactor

from .fakes import FakeSource

_FIXED_SNAPSHOT_ID = UUID("12345678-1234-5678-1234-567812345678")
_DEFAULT_PARAMETERS_BY_STRATEGY: dict[
    LocatorStrategy,
    dict[str, str | bool | int | float],
] = {
    "role": {"role": "button", "name": "Continue", "exact": True},
    "label": {"value": "Continue", "exact": True},
    "text": {"value": "Continue", "exact": True},
    "placeholder": {"value": "Continue", "exact": True},
    "alt": {"value": "Continue", "exact": True},
    "title": {"value": "Continue", "exact": True},
    "testid": {"value": "continue"},
    "id": {"value": "continue"},
    "name": {"value": "continue"},
    "aria": {"attribute": "aria-label", "value": "Continue"},
    "css": {"selector": "button"},
    "xpath": {"expression": "//button"},
    "position": {
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 32,
        "viewportWidth": 1280,
        "viewportHeight": 720,
    },
}


def _raw_locator_candidate(
    *,
    strategy: LocatorStrategy = "role",
    parameters: dict[str, str | bool | int | float] | None = None,
    rank: int = 1,
    limitations: tuple[str, ...] = (),
) -> RawLocatorCandidate:
    return RawLocatorCandidate(
        strategy=strategy,
        parameters=parameters or _DEFAULT_PARAMETERS_BY_STRATEGY[strategy],
        source="observed",
        uniqueness="unique",
        match_count=1,
        stability="high",
        confidence=0.95,
        rank=rank,
        recommended=strategy != "position",
        limitations=limitations,
    )


def test_collector_keeps_successful_frames_when_one_frame_fails() -> None:
    source = FakeSource.with_one_success_and_one_failure()

    snapshot = SnapshotCollector(source=source).collect(
        "https://example.test", SnapshotLimits()
    )

    assert snapshot.status == "partial"
    assert snapshot.truncated is False
    assert len(snapshot.frames) == 2
    assert snapshot.frames[0].status == "completed"
    assert snapshot.frames[1].status == "failed"
    assert snapshot.errors[0].recoverable is True


def test_collector_redacts_before_snapshot_validation() -> None:
    source = FakeSource.with_text("token=super-secret")

    snapshot = SnapshotCollector(source=source).collect(
        "https://example.test", SnapshotLimits()
    )

    assert "super-secret" not in snapshot.model_dump_json()


def test_collector_redacts_element_href_as_url() -> None:
    source = FakeSource.with_href(
        "https://example.test/detail?token=href-secret&view=list#access_token=fragment"
    )

    snapshot = SnapshotCollector(source=source).collect(
        "https://example.test", SnapshotLimits()
    )

    href = snapshot.frames[0].elements[0].href
    assert href is not None
    assert "href-secret" not in href
    assert "fragment" not in href
    assert "token=%5BREDACTED%3ATOKEN%5D" in href
    assert "#" not in href


def test_collector_redacts_and_flattens_locator_candidates() -> None:
    """Missing candidate mapping must not drop or persist raw locator secrets."""
    source = FakeSource.with_locator_candidates(
        (
            _raw_locator_candidate(
                parameters={
                    "role": "button",
                    "name": "token=synthetic-secret",
                    "exact": True,
                },
                limitations=("token=limitation-secret",),
            ),
            _raw_locator_candidate(
                strategy="position",
                rank=2,
            ),
        )
    )

    snapshot = SnapshotCollector(
        source=source,
        uuid_factory=lambda: _FIXED_SNAPSHOT_ID,
    ).collect("https://example.test", SnapshotLimits())

    candidate = snapshot.locator_candidates[0]
    serialized = json.dumps(candidate.model_dump(), ensure_ascii=False)
    assert candidate.element_ref == snapshot.frames[0].elements[0].element_id
    assert candidate.frame_ref == snapshot.frames[0].frame_id
    assert "synthetic-secret" not in serialized
    assert "limitation-secret" not in serialized
    assert "[REDACTED:TOKEN]" in serialized
    assert candidate.parameters["exact"] is True
    assert snapshot.locator_candidates[1].parameters["width"] == 100
    assert snapshot.statistics.locator_candidate_count == 2


def test_collector_generates_locator_ids_from_redacted_parameters() -> None:
    """Generating IDs before redaction would make equivalent secrets observable."""
    first = SnapshotCollector(
        source=FakeSource.with_locator_candidates(
            (
                _raw_locator_candidate(
                    strategy="testid",
                    parameters={"value": "token=first-secret"},
                ),
            )
        )
    ).collect("https://example.test", SnapshotLimits())
    second = SnapshotCollector(
        source=FakeSource.with_locator_candidates(
            (
                _raw_locator_candidate(
                    strategy="testid",
                    parameters={"value": "token=second-secret"},
                ),
            )
        )
    ).collect("https://example.test", SnapshotLimits())

    first_json = first.model_dump_json()
    second_json = second.model_dump_json()
    assert "first-secret" not in first_json
    assert "second-secret" not in second_json
    assert "[REDACTED:TOKEN]" in first_json
    assert "[REDACTED:TOKEN]" in second_json
    assert first.locator_candidates[0].locator_id == second.locator_candidates[0].locator_id
    assert first.locator_candidates[0].locator_id.startswith("locator-")


@pytest.mark.parametrize(
    ("parameters", "secret"),
    [
        ({"token=key-secret": "safe"}, "key-secret"),
        ({"token": "plain-token-secret"}, "plain-token-secret"),
        ({"password": "plain-password-secret"}, "plain-password-secret"),
    ],
    ids=["secret-in-key", "token-key", "password-key"],
)
def test_collector_rejects_locator_parameters_outside_strategy_vocabulary(
    parameters: dict[str, str | bool | int | float],
    secret: str,
) -> None:
    """Unknown or sensitive parameter keys must fail before persistence or ID hashing."""
    collector = SnapshotCollector(
        source=FakeSource.with_locator_candidates(
            (_raw_locator_candidate(strategy="role", parameters=parameters),)
        )
    )

    with pytest.raises(CollectionFailedError) as exc_info:
        collector.collect("https://example.test", SnapshotLimits())

    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    ("key", "secret"),
    [
        ("url", "first-path-secret"),
        ("href", "second-path-secret"),
        ("src", "third-path-secret"),
    ],
)
def test_collector_rejects_url_keys_absent_from_browser_strategy_contract(
    key: str,
    secret: str,
) -> None:
    """Browser does not emit URL keys, so no strategy may persist or hash them."""
    value = f"https://example.test/token={secret}"
    collector = SnapshotCollector(
        source=FakeSource.with_locator_candidates(
            (
                _raw_locator_candidate(
                    parameters={key: value}
                ),
            )
        )
    )

    with pytest.raises(CollectionFailedError) as exc_info:
        collector.collect("https://example.test", SnapshotLimits())

    exception_messages: list[str] = []
    error: BaseException | None = exc_info.value
    while error is not None:
        exception_messages.append(str(error))
        error = error.__cause__
    serialized_errors = " ".join(exception_messages)
    assert key not in serialized_errors
    assert value not in serialized_errors
    assert secret not in serialized_errors


@pytest.mark.parametrize(
    "strategy",
    [
        "role",
        "label",
        "text",
        "placeholder",
        "alt",
        "title",
        "testid",
        "id",
        "name",
        "aria",
        "css",
        "xpath",
        "position",
    ],
)
def test_collector_persists_each_snapshot_1_1_locator_strategy(
    strategy: LocatorStrategy,
) -> None:
    """Dropping any supported raw strategy would make Snapshot 1.1 incomplete."""
    snapshot = SnapshotCollector(
        source=FakeSource.with_locator_candidates(
            (_raw_locator_candidate(strategy=strategy),)
        )
    ).collect("https://example.test", SnapshotLimits())

    assert [candidate.strategy for candidate in snapshot.locator_candidates] == [strategy]
    assert [candidate.rank for candidate in snapshot.locator_candidates] == [1]


def test_collector_tracks_redactions_per_frame_and_globally() -> None:
    snapshot = SnapshotCollector(
        source=FakeSource.with_one_success_and_one_failure()
    ).collect("https://example.test", SnapshotLimits())

    assert snapshot.frames[0].redaction_count == 2
    assert snapshot.frames[0].redaction_categories == ["TOKEN"]
    assert snapshot.frames[1].redaction_count == 0
    assert snapshot.frames[1].redaction_categories == []
    assert snapshot.statistics.redaction_count == 2
    assert snapshot.statistics.redaction_categories == ["TOKEN"]


def test_collector_aggregates_redaction_categories_in_deterministic_order() -> None:
    snapshot = SnapshotCollector(
        source=FakeSource.with_text(
            "password=fixture-password email fixture@example.test"
        )
    ).collect("https://example.test", SnapshotLimits())

    assert snapshot.frames[0].redaction_categories == ["EMAIL", "PASSWORD"]
    assert snapshot.statistics.redaction_categories == ["EMAIL", "PASSWORD"]


def test_collector_persists_custom_redaction_category() -> None:
    redactor = Redactor(
        custom_rules=[
            CustomRedactionRule(
                name="case-reference",
                category="CASE_REFERENCE",
                pattern=r"\bCASE-\d{4}\b",
            )
        ]
    )
    snapshot = SnapshotCollector(
        source=FakeSource.with_text("reference CASE-4821"),
        redactor=redactor,
    ).collect("https://example.test", SnapshotLimits())

    assert "CASE-4821" not in snapshot.model_dump_json()
    assert snapshot.frames[0].redaction_categories == ["CASE_REFERENCE"]
    assert snapshot.statistics.redaction_categories == ["CASE_REFERENCE"]


def test_collector_rejects_navigation_after_global_deadline() -> None:
    clock_values = iter([0.0, 2.0])
    source = FakeSource.with_text("Visible page text")
    collector = SnapshotCollector(
        source=source,
        monotonic_clock=lambda: next(clock_values),
    )

    with pytest.raises(CollectionFailedError, match="deadline"):
        collector.collect("https://example.test", SnapshotLimits(total_timeout_ms=1_000))

    assert source.collect_calls == 0


def test_collector_preserves_valid_deadline_partial_returned_by_source() -> None:
    clock = [0.0]
    source = FakeSource.with_deadline_partial()
    source.on_collect = lambda: clock.__setitem__(0, 2.0)
    collector = SnapshotCollector(source=source, monotonic_clock=lambda: clock[0])

    snapshot = collector.collect(
        "https://example.test", SnapshotLimits(total_timeout_ms=1_000)
    )

    assert snapshot.status == "partial"
    assert snapshot.frames[0].status == "partial"
    assert snapshot.frames[0].stop_reason == "deadline"
    assert snapshot.frames[0].scroll_results[0].stop_reason == "deadline"
    assert snapshot.errors[0].recoverable is True


def test_collector_counts_redactions_in_page_fields() -> None:
    snapshot = SnapshotCollector(
        source=FakeSource.with_page_fields(
            frame_id="token=frame-secret",
            language="token=language-secret",
        )
    ).collect("https://example.test", SnapshotLimits())

    assert "frame-secret" not in snapshot.model_dump_json()
    assert "language-secret" not in snapshot.model_dump_json()
    assert snapshot.statistics.redaction_count == 5


def test_collector_wraps_invalid_root_frame_as_collection_failure() -> None:
    with pytest.raises(CollectionFailedError, match="root"):
        SnapshotCollector(source=FakeSource.with_invalid_root()).collect(
            "https://example.test", SnapshotLimits()
        )


def test_collector_keeps_valid_root_when_child_frame_modeling_fails() -> None:
    snapshot = SnapshotCollector(
        source=FakeSource.with_one_success_and_one_invalid_child()
    ).collect("https://example.test", SnapshotLimits())

    assert snapshot.status == "partial"
    assert [frame.status for frame in snapshot.frames] == ["completed", "failed"]
    assert snapshot.frames[1].errors[0].recoverable is True
    assert snapshot.frames[1].redaction_count == 0
    assert snapshot.statistics.redaction_count == 2
    assert snapshot.statistics.redaction_categories == ["TOKEN"]
    assert "EMAIL" not in snapshot.statistics.redaction_categories
    assert snapshot.errors[-1].recoverable is True


@pytest.mark.parametrize(
    "source",
    [
        FakeSource.with_invalid_viewport(),
        FakeSource.with_invalid_page_error_timestamp(),
    ],
    ids=["invalid-viewport", "invalid-page-error-timestamp"],
)
def test_collector_wraps_top_level_validation_failures(
    source: FakeSource,
) -> None:
    with pytest.raises(CollectionFailedError) as exc_info:
        SnapshotCollector(source=source).collect(
            "https://example.test",
            SnapshotLimits(),
        )

    assert exc_info.value.__cause__ is not None
