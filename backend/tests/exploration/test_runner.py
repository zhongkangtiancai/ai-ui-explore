"""Bounded exploration runner tests with injected fake collectors."""

from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry, NavigationCandidate
from ai_ui_explorer.exploration.runner import ExplorationRunner, SnapshotCollectorPort
from ai_ui_explorer.snapshot.models import SnapshotDocument
from tests.snapshot.factories import make_snapshot


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
