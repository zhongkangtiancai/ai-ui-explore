"""Real Chromium tests for bounded page, frame, and nested scrolling."""

from __future__ import annotations

from time import monotonic
from urllib.parse import urljoin

import pytest
from playwright.sync_api import Error as PlaywrightError

from ai_ui_explorer.snapshot import browser as browser_module
from ai_ui_explorer.snapshot import scrolling as scrolling_module
from ai_ui_explorer.snapshot.browser import (
    PlaywrightBrowserSource,
    RawElementObservation,
    RawPageObservation,
    RawScrollResult,
)
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.snapshot.scrolling import (
    discover_scroll_containers,
    scroll_container,
)


def collect_fixture(
    url: str,
    max_scroll_rounds_per_container: int,
) -> RawPageObservation:
    return PlaywrightBrowserSource(headless=True).collect(
        url,
        SnapshotLimits(
            max_scroll_rounds_per_container=max_scroll_rounds_per_container,
        ),
    )


def all_elements(observation: RawPageObservation) -> list[RawElementObservation]:
    return [
        element
        for frame in observation.frames
        for element in frame.elements
    ]


def all_scroll_results(observation: RawPageObservation) -> list[RawScrollResult]:
    return [
        scroll_result
        for frame in observation.frames
        for scroll_result in frame.scroll_results
    ]


def test_scrolling_discovers_elements_in_nested_container(primary_url: str) -> None:
    observation = collect_fixture(primary_url, max_scroll_rounds_per_container=10)
    names = {element.accessible_name for element in all_elements(observation)}
    assert "嵌套列表末项" in names


def test_infinite_container_stops_at_budget(primary_url: str) -> None:
    observation = collect_fixture(primary_url, max_scroll_rounds_per_container=3)
    infinite = next(
        item
        for item in all_scroll_results(observation)
        if item.label == "infinite-list"
    )
    assert infinite.rounds == 3
    assert infinite.truncated is True
    assert infinite.stop_reason == "round_limit"


def test_static_container_stops_after_two_stable_rounds(primary_url: str) -> None:
    observation = collect_fixture(primary_url, max_scroll_rounds_per_container=10)
    stable = next(
        item
        for item in all_scroll_results(observation)
        if item.label == "stable-list"
    )
    assert stable.rounds == 2
    assert stable.truncated is False
    assert stable.stop_reason == "stable"


def test_deadline_stops_scroll_after_browser_is_ready(primary_url: str) -> None:
    browser_module._configure_local_browser_path()
    setup_deadline = monotonic() + 10
    with browser_module._managed_page(headless=True, deadline=setup_deadline) as page:
        page.goto(
            primary_url,
            wait_until="domcontentloaded",
            timeout=browser_module._remaining_milliseconds(setup_deadline),
        )
        infinite = next(
            item
            for item in discover_scroll_containers(page.main_frame, 10)
            if item.label == "infinite-list"
        )
        result = scroll_container(
            page.main_frame,
            infinite,
            max_rounds=500,
            deadline=monotonic() + 0.05,
        )

    assert result.stop_reason == "deadline"
    assert result.truncated is True
    assert result.rounds <= 1


def test_detached_container_is_recorded_without_stopping_other_frames(
    primary_url: str,
) -> None:
    observation = collect_fixture(primary_url, max_scroll_rounds_per_container=10)
    detached = next(
        item
        for item in all_scroll_results(observation)
        if item.label == "detaching-list"
    )
    assert detached.stop_reason == "detached"
    assert detached.truncated is False
    detached_frame = next(
        frame
        for frame in observation.frames
        if detached in frame.scroll_results
    )
    assert detached_frame.status == "partial"
    assert detached_frame.truncated is True
    assert detached_frame.stop_reason == "detached"
    assert any(frame.status == "completed" for frame in observation.frames)


def test_detached_reason_overrides_text_truncation(primary_url: str) -> None:
    observation = PlaywrightBrowserSource(headless=True).collect(
        primary_url,
        SnapshotLimits(
            max_text_chars=1,
            max_scroll_rounds_per_container=10,
        ),
    )
    detached_frame = next(
        frame
        for frame in observation.frames
        if any(result.stop_reason == "detached" for result in frame.scroll_results)
    )

    assert detached_frame.status == "partial"
    assert detached_frame.truncated is True
    assert detached_frame.stop_reason == "detached"


def test_detached_frame_during_scroll_returns_recoverable_result(
    primary_url: str,
) -> None:
    browser_module._configure_local_browser_path()
    deadline = monotonic() + 10
    with browser_module._managed_page(headless=True, deadline=deadline) as page:
        page.goto(
            primary_url,
            wait_until="domcontentloaded",
            timeout=browser_module._remaining_milliseconds(deadline),
        )
        page.wait_for_timeout(100)
        dynamic_frame = next(frame for frame in page.frames if frame.name == "dynamic")
        container = discover_scroll_containers(dynamic_frame, 1)[0]
        page.wait_for_timeout(1_600)
        assert dynamic_frame.is_detached()
        result = scroll_container(
            dynamic_frame,
            container,
            max_rounds=3,
            deadline=deadline,
        )

    assert result.stop_reason == "detached"
    assert result.truncated is False
    assert result.restored is False


def test_scroll_error_is_classified_and_restoration_is_attempted(
    primary_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_module._configure_local_browser_path()
    setup_deadline = monotonic() + 10
    with browser_module._managed_page(headless=True, deadline=setup_deadline) as page:
        page.goto(
            primary_url,
            wait_until="domcontentloaded",
            timeout=browser_module._remaining_milliseconds(setup_deadline),
        )
        container = next(
            item
            for item in discover_scroll_containers(page.main_frame, 10)
            if item.label == "stable-list"
        )
        real_request = scrolling_module._carrier_request
        restore_attempted = False

        def fail_scroll(
            frame: object,
            request: dict[str, object],
            *,
            deadline: float | None = None,
            timeout_ms: int | None = None,
        ) -> object:
            nonlocal restore_attempted
            if request["operation"] == "restore":
                restore_attempted = True
                return real_request(
                    frame,  # type: ignore[arg-type]
                    request,
                    deadline=deadline,
                    timeout_ms=timeout_ms,
                )
            raise PlaywrightError("synthetic scroll failure")

        monkeypatch.setattr(scrolling_module, "_carrier_request", fail_scroll)
        result = scroll_container(
            page.main_frame,
            container,
            max_rounds=3,
            deadline=setup_deadline,
        )

    assert result.stop_reason == "error"
    assert result.truncated is False
    assert restore_attempted is True
    assert result.restored is True


def test_surviving_containers_return_to_original_scroll_top(primary_url: str) -> None:
    browser_module._configure_local_browser_path()
    deadline = monotonic() + 10
    with browser_module._managed_page(headless=True, deadline=deadline) as page:
        page.goto(
            primary_url,
            wait_until="domcontentloaded",
            timeout=browser_module._remaining_milliseconds(deadline),
        )
        before = {
            container.container_id: container
            for container in discover_scroll_containers(page.main_frame, 20)
        }
        target = next(
            container
            for container in before.values()
            if container.label == "stable-list"
        )
        result = scroll_container(
            page.main_frame,
            target,
            max_rounds=3,
            deadline=deadline,
        )
        after = {
            container.container_id: container
            for container in discover_scroll_containers(page.main_frame, 20)
        }

    assert target.original_scroll_top == 17
    assert after[target.container_id].original_scroll_top == target.original_scroll_top
    assert result.restored is True


def test_discovery_filters_invalid_containers_and_assigns_stable_ids(
    primary_url: str,
) -> None:
    first = collect_fixture(primary_url, max_scroll_rounds_per_container=2)
    second = collect_fixture(primary_url, max_scroll_rounds_per_container=2)
    first_results = all_scroll_results(first)
    second_results = all_scroll_results(second)
    invalid_labels = {"hidden-scroll", "clipped-list", "zero-box", "not-overflowing"}

    assert invalid_labels.isdisjoint(item.label for item in first_results)
    assert all(
        frame.scroll_results[0].container_id == f"{frame.frame_id}-scroll-0"
        and frame.scroll_results[0].label == "document"
        for frame in first.frames
        if frame.scroll_results
    )
    assert [
        (item.container_id, item.label)
        for item in first_results
    ] == [
        (item.container_id, item.label)
        for item in second_results
    ]


def test_container_limit_counts_document_as_container_zero(primary_url: str) -> None:
    observation = PlaywrightBrowserSource(headless=True).collect(
        primary_url,
        SnapshotLimits(
            max_scroll_containers_per_frame=1,
            max_scroll_rounds_per_container=2,
        ),
    )
    assert all(len(frame.scroll_results) <= 1 for frame in observation.frames)
    assert all(
        not frame.scroll_results or frame.scroll_results[0].label == "document"
        for frame in observation.frames
    )


@pytest.mark.parametrize("container_limit", [0, 1])
def test_scroll_container_limit_marks_owning_frame_partial_and_truncated(
    primary_url: str,
    container_limit: int,
) -> None:
    """An omitted document or nested container must be an explicit Frame truncation."""
    observation = PlaywrightBrowserSource(headless=True).collect(
        urljoin(primary_url, "/same-frame.html"),
        SnapshotLimits(
            max_scroll_containers_per_frame=container_limit,
            max_scroll_rounds_per_container=2,
        ),
    )

    main_frame = observation.frames[0]
    assert len(main_frame.scroll_results) == container_limit
    assert main_frame.status == "partial"
    assert main_frame.truncated is True
    assert main_frame.stop_reason == "max_scroll_containers"


def test_scrolled_elements_are_deduplicated_and_never_include_sensitive_values(
    primary_url: str,
) -> None:
    observation = collect_fixture(primary_url, max_scroll_rounds_per_container=10)
    elements = all_elements(observation)
    stable_keys = [
        (
            frame.frame_id,
            element.tag,
            element.role,
            element.accessible_name,
            tuple(sorted(element.attributes.items())),
        )
        for frame in observation.frames
        for element in frame.elements
    ]

    assert len(stable_keys) == len(set(stable_keys))
    assert "fixture-scroll-secret-do-not-return" not in repr(observation)
    assert all("value" not in element.attributes for element in elements)
    assert "被错误点击" not in {element.accessible_name for element in elements}


def test_scrolling_stops_immediately_when_global_element_budget_is_exhausted(
    primary_url: str,
) -> None:
    observation = PlaywrightBrowserSource(headless=True).collect(
        f"{primary_url}&scrollFixture=budget",
        SnapshotLimits(
            max_elements=3,
            max_scroll_rounds_per_container=10,
        ),
    )
    main_frame = observation.frames[0]
    budget = next(
        result
        for result in main_frame.scroll_results
        if result.label == "budget-list"
    )

    assert len(all_elements(observation)) == 3
    assert 1 <= budget.rounds < 10
    assert budget.stop_reason == "max_elements"
    assert budget.truncated is True
    assert main_frame.status == "partial"
    assert main_frame.truncated is True
    assert main_frame.stop_reason == "max_elements"
    assert all(
        frame.elements == []
        and frame.scroll_results == []
        and frame.status == "partial"
        and frame.truncated is True
        and frame.stop_reason == "max_elements"
        for frame in observation.frames[1:]
    )


def test_distinct_same_name_nodes_are_both_kept_after_scrolling(
    primary_url: str,
) -> None:
    observation = PlaywrightBrowserSource(headless=True).collect(
        f"{primary_url}&scrollFixture=identity",
        SnapshotLimits(max_scroll_rounds_per_container=1),
    )
    matching = [
        element
        for element in observation.frames[0].elements
        if element.accessible_name == "同名操作"
    ]

    assert len(matching) == 2
    assert "snapshot-node" not in repr(observation)


def test_delayed_element_between_containers_is_emitted_not_swallowed(
    primary_url: str,
) -> None:
    observation = PlaywrightBrowserSource(headless=True).collect(
        f"{primary_url}&scrollFixture=delayed",
        SnapshotLimits(max_scroll_rounds_per_container=2),
    )
    names = {
        element.accessible_name
        for element in observation.frames[0].elements
    }

    assert "延迟跨容器末项" in names
