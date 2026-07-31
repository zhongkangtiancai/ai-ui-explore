"""Sprint 4 bounded exploration queue tests."""

from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import (
    BoundedExplorationQueue,
    ExplorationBudget,
    ModuleEntry,
    NavigationCandidate,
)
from tests.snapshot.factories import make_snapshot


def test_queue_seeds_only_allowed_module_entries() -> None:
    queue = BoundedExplorationQueue(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=2, max_queue_size=5),
    )

    decisions = queue.seed_modules(
        [
            ModuleEntry(module_id="dashboard", url="https://app.example.test/dashboard"),
            ModuleEntry(module_id="outside", url="https://outside.example.test/"),
        ]
    )

    assert [decision.reason_code for decision in decisions] == [
        "enqueued",
        "origin_not_allowed",
    ]
    assert queue.pending_count == 1
    assert queue.next_target().url == "https://app.example.test/dashboard"


def test_queue_deduplicates_urls_before_enqueueing() -> None:
    queue = BoundedExplorationQueue(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=2, max_queue_size=5),
    )

    first = queue.seed_modules(
        [ModuleEntry(module_id="dashboard", url="https://app.example.test/dashboard")]
    )[0]
    second = queue.seed_modules(
        [ModuleEntry(module_id="dashboard-copy", url="https://app.example.test/dashboard")]
    )[0]

    assert first.reason_code == "enqueued"
    assert second.reason_code == "duplicate_url"
    assert queue.pending_count == 1


def test_queue_deduplicates_normalized_default_ports_and_host_case() -> None:
    queue = BoundedExplorationQueue(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=2, max_queue_size=5),
    )

    decisions = queue.seed_modules(
        [
            ModuleEntry(module_id="first", url="https://APP.example.test:443/dashboard"),
            ModuleEntry(module_id="second", url="https://app.example.test/dashboard"),
        ]
    )

    assert [decision.reason_code for decision in decisions] == [
        "enqueued",
        "duplicate_url",
    ]
    assert decisions[0].url == "https://app.example.test/dashboard"


def test_queue_applies_action_gate_and_depth_to_candidates() -> None:
    queue = BoundedExplorationQueue(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=10, max_depth=1, max_queue_size=10),
    )
    queue.seed_modules(
        [ModuleEntry(module_id="root", url="https://app.example.test/root")]
    )
    target = queue.next_target()

    decisions = queue.enqueue_candidates(
        source=target,
        candidates=[
            NavigationCandidate(
                url="https://app.example.test/detail",
                action_type="link_navigation",
                label="Detail",
            ),
            NavigationCandidate(
                url="https://app.example.test/delete",
                action_type="button_click",
                label="Delete",
            ),
        ],
    )
    next_target = queue.next_target()
    too_deep = queue.enqueue_candidates(
        source=next_target,
        candidates=[
            NavigationCandidate(
                url="https://app.example.test/deeper",
                action_type="link_navigation",
                label="Deeper",
            )
        ],
    )[0]

    assert [decision.reason_code for decision in decisions] == [
        "enqueued",
        "denied",
    ]
    assert next_target.url == "https://app.example.test/detail"
    assert too_deep.reason_code == "max_depth"


def test_queue_enforces_max_pages_and_queue_size() -> None:
    queue = BoundedExplorationQueue(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=2, max_depth=2, max_queue_size=1),
    )

    decisions = queue.seed_modules(
        [
            ModuleEntry(module_id="first", url="https://app.example.test/first"),
            ModuleEntry(module_id="second", url="https://app.example.test/second"),
            ModuleEntry(module_id="third", url="https://app.example.test/third"),
        ]
    )

    assert [decision.reason_code for decision in decisions] == [
        "enqueued",
        "queue_limit",
        "queue_limit",
    ]
    assert queue.next_target().url == "https://app.example.test/first"
    assert queue.next_target() is None


def test_queue_marks_repeated_snapshot_state() -> None:
    queue = BoundedExplorationQueue(
        policy=NavigationPolicy(allowed_origins=["https://example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=2, max_queue_size=5),
    )
    queue.seed_modules(
        [
            ModuleEntry(module_id="first", url="https://example.test/first"),
            ModuleEntry(module_id="second", url="https://example.test/second"),
        ]
    )

    first = queue.next_target()
    second = queue.next_target()
    first_result = queue.record_snapshot_result(first, make_snapshot())
    second_result = queue.record_snapshot_result(second, make_snapshot())

    assert first_result.seen_before is False
    assert second_result.seen_before is True
    assert queue.visited_count == 2
