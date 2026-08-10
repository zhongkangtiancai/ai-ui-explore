"""Bounded exploration runner tests with injected fake collectors."""

from urllib.parse import urljoin, urlsplit

import pytest

from ai_ui_explorer.exploration.collector_adapter import SnapshotCollectorAdapter
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry, NavigationCandidate
from ai_ui_explorer.exploration.runner import ExplorationRunner, SnapshotCollectorPort
from ai_ui_explorer.exploration.task import ExplorationTask, ExplorationTaskState
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSource
from ai_ui_explorer.snapshot.collector import CollectionFailedError, SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotLimits
from tests.snapshot.factories import make_element, make_frame, make_snapshot
from tests.snapshot.fakes import FakeSource


class FakeCollector(SnapshotCollectorPort):
    def __init__(self, snapshots: dict[str, SnapshotDocument]) -> None:
        self.snapshots = snapshots
        self.collected_urls: list[str] = []

    def collect(self, url: str) -> SnapshotDocument:
        self.collected_urls.append(url)
        if url not in self.snapshots:
            raise RuntimeError("synthetic collector failure with token=secret")
        return self.snapshots[url]


def test_runner_collects_seed_and_readonly_candidate_until_queue_empty() -> None:
    root_url = "https://app.example.test/root"
    detail_url = "https://app.example.test/detail"
    collector = FakeCollector(
        {
            root_url: make_snapshot(
                source={
                    "requested_url": root_url,
                    "final_url": root_url,
                    "title": "Root",
                }
            ),
            detail_url: make_snapshot(
                source={
                    "requested_url": detail_url,
                    "final_url": detail_url,
                    "title": "Detail",
                }
            ),
        }
    )
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=2, max_queue_size=5),
        collector=collector,
        candidate_extractor=lambda snapshot: [
            NavigationCandidate(
                url=detail_url,
                action_type="link_navigation",
                label="Detail",
            )
        ]
        if snapshot.source.final_url == root_url
        else [],
    )

    result = runner.run(
        modules=[ModuleEntry(module_id="root", url=root_url)],
    )

    assert result.status == "completed"
    assert collector.collected_urls == [root_url, detail_url]
    assert [visit.target.url for visit in result.visits] == [root_url, detail_url]
    assert result.stop_reasons == []


def test_runner_completes_bound_task_and_notifies_terminal_callback() -> None:
    root_url = "https://app.example.test/root"
    task = ExplorationTask.create(task_id="task-1")
    observed_states: list[ExplorationTaskState] = []
    task.register_terminal_callback(lambda: observed_states.append(task.state))
    task.start_collection()
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        collector=FakeCollector(
            {
                root_url: make_snapshot(
                    source={
                        "requested_url": root_url,
                        "final_url": root_url,
                        "title": "Root",
                    }
                )
            }
        ),
        task=task,
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert result.status == "completed"
    assert task.state == ExplorationTaskState.COMPLETED
    assert observed_states == [ExplorationTaskState.COMPLETED]


def test_runner_marks_bound_task_partial_and_notifies_terminal_callback() -> None:
    task = ExplorationTask.create(task_id="task-1")
    observed_states: list[ExplorationTaskState] = []
    task.register_terminal_callback(lambda: observed_states.append(task.state))
    task.start_collection()
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        collector=FakeCollector({}),
        task=task,
    )

    result = runner.run(
        modules=[
            ModuleEntry(
                module_id="missing",
                url="https://app.example.test/missing",
            )
        ]
    )

    assert result.status == "partial"
    assert task.state == ExplorationTaskState.PARTIAL
    assert task.audit_events[-1].reason_code == "collector_failure"
    assert observed_states == [ExplorationTaskState.PARTIAL]


def test_runner_uses_snapshot_href_candidates_by_default() -> None:
    root_url = "https://app.example.test/root"
    detail_url = "https://app.example.test/detail"
    collector = FakeCollector(
        {
            root_url: make_snapshot(
                source={
                    "requested_url": root_url,
                    "final_url": root_url,
                    "title": "Root",
                },
                frames=[
                    make_frame(
                        elements=[
                            make_element(
                                tag="a",
                                role="link",
                                accessible_name="Detail",
                                href=detail_url,
                            )
                        ]
                    )
                ],
            ),
            detail_url: make_snapshot(
                source={
                    "requested_url": detail_url,
                    "final_url": detail_url,
                    "title": "Detail",
                }
            ),
        }
    )
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=2, max_queue_size=5),
        collector=collector,
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert result.status == "completed"
    assert collector.collected_urls == [root_url, detail_url]


def test_runner_explores_local_fixture_link_with_real_browser(
    primary_url: str,
) -> None:
    """The real collection path follows one same-origin observed anchor within budget."""
    parsed_url = urlsplit(primary_url)
    origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    detail_url = urljoin(primary_url, "/same-frame.html")
    runner = ExplorationRunner(
        policy=NavigationPolicy(
            allowed_origins=[origin],
            allow_local_http=True,
        ),
        budget=ExplorationBudget(max_pages=2, max_depth=1, max_queue_size=5),
        collector=SnapshotCollectorAdapter(
            collector=SnapshotCollector(source=PlaywrightBrowserSource(headless=True)),
            limits=SnapshotLimits(),
        ),
    )

    result = runner.run(modules=[ModuleEntry(module_id="fixture", url=primary_url)])

    assert result.status == "completed"
    assert result.errors == []
    assert result.stop_reasons == []
    assert [visit.target.url for visit in result.visits] == [primary_url, detail_url]
    assert [visit.seen_before for visit in result.visits] == [False, False]


def test_runner_does_not_expand_duplicate_page_states() -> None:
    first_url = "https://app.example.test/first"
    second_url = "https://app.example.test/second"
    first_leaf_url = "https://app.example.test/first-leaf"
    second_leaf_url = "https://app.example.test/second-leaf"
    first_snapshot = make_snapshot(
        source={
            "requested_url": first_url,
            "final_url": "https://app.example.test/same-state",
            "title": "Same",
        },
        frames=[
            make_frame(
                url="https://app.example.test/same-state",
                text_summary="Same page",
                elements=[
                    make_element(
                        tag="a",
                        role="link",
                        accessible_name="Same action",
                        text="Same action",
                        href=first_leaf_url,
                    )
                ],
            )
        ],
    )
    second_snapshot = make_snapshot(
        source={
            "requested_url": second_url,
            "final_url": "https://app.example.test/same-state",
            "title": "Same",
        },
        frames=[
            make_frame(
                url="https://app.example.test/same-state",
                text_summary="Same page",
                elements=[
                    make_element(
                        tag="a",
                        role="link",
                        accessible_name="Same action",
                        text="Same action",
                        href=second_leaf_url,
                    )
                ],
            )
        ],
    )
    collector = FakeCollector(
        {
            first_url: first_snapshot,
            second_url: second_snapshot,
            first_leaf_url: make_snapshot(
                source={
                    "requested_url": first_leaf_url,
                    "final_url": first_leaf_url,
                    "title": "First leaf",
                }
            ),
            second_leaf_url: make_snapshot(
                source={
                    "requested_url": second_leaf_url,
                    "final_url": second_leaf_url,
                    "title": "Second leaf",
                }
            ),
        }
    )
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=2, max_queue_size=5),
        collector=collector,
    )

    result = runner.run(
        modules=[
            ModuleEntry(module_id="first", url=first_url),
            ModuleEntry(module_id="second", url=second_url),
        ],
    )

    assert [visit.seen_before for visit in result.visits] == [False, True, False]
    assert collector.collected_urls == [first_url, second_url, first_leaf_url]
    assert "duplicate_state" in result.stop_reasons


def test_runner_respects_depth_and_action_gates() -> None:
    root_url = "https://app.example.test/root"
    collector = FakeCollector({root_url: make_snapshot()})
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=0, max_queue_size=5),
        collector=collector,
        candidate_extractor=lambda _snapshot: [
            NavigationCandidate(
                url="https://app.example.test/deeper",
                action_type="link_navigation",
            ),
            NavigationCandidate(
                url="https://app.example.test/delete",
                action_type="button_click",
            ),
        ],
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert result.status == "completed"
    assert collector.collected_urls == [root_url]
    assert {decision.reason_code for decision in result.enqueue_decisions} >= {
        "max_depth",
        "denied",
    }


def test_runner_marks_partial_on_collector_failure_without_leaking_error() -> None:
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=5, max_depth=1, max_queue_size=5),
        collector=FakeCollector({}),
        candidate_extractor=lambda _snapshot: [],
    )

    result = runner.run(
        modules=[
            ModuleEntry(
                module_id="missing",
                url="https://app.example.test/missing",
            )
        ]
    )

    assert result.status == "partial"
    assert result.stop_reasons == ["collector_failure"]
    assert result.errors[0].safe_message == "Snapshot collection failed."
    assert "secret" not in result.model_dump_json()


def test_snapshot_collector_adapter_passes_url_and_limits_to_collector() -> None:
    source = FakeSource.with_text("Visible page text")
    adapter = SnapshotCollectorAdapter(
        collector=SnapshotCollector(source=source),
        limits=SnapshotLimits(max_elements=123, max_text_chars=45),
    )

    snapshot = adapter.collect("https://example.test/dashboard")

    assert snapshot.source.requested_url == "https://example.test/dashboard"
    assert snapshot.limits.max_elements == 123
    assert snapshot.limits.max_text_chars == 45
    assert source.collect_calls == 1


def test_snapshot_collector_adapter_raises_safe_failure_surface() -> None:
    class FailingSource(FakeSource):
        def collect(self, url: str, limits: SnapshotLimits):
            raise RuntimeError("synthetic failure token=secret")

    adapter = SnapshotCollectorAdapter(
        collector=SnapshotCollector(source=FailingSource.with_text("unused")),
        limits=SnapshotLimits(),
    )

    with pytest.raises(
        CollectionFailedError,
        match="Controlled exploration snapshot collection failed",
    ):
        adapter.collect("https://example.test/?token=secret")
