"""Bounded exploration runner tests with injected fake collectors."""

from typing import cast
from urllib.parse import urljoin, urlsplit

import pytest

from ai_ui_explorer.exploration.collector_adapter import (
    SessionSnapshotCollectorAdapter,
    SnapshotCollectorAdapter,
)
from ai_ui_explorer.exploration.interactions import (
    ReadonlyInteractionCandidate,
    ReadonlyInteractionExecution,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import ExplorationBudget, ModuleEntry, NavigationCandidate
from ai_ui_explorer.exploration.runner import (
    ExplorationCancellationToken,
    ExplorationEvidenceSink,
    ExplorationRunner,
    SnapshotCollectorPort,
)
from ai_ui_explorer.exploration.task import ExplorationTask, ExplorationTaskState
from ai_ui_explorer.permission_comparison.models import EvidenceReference, LocatorCandidateEvidence
from ai_ui_explorer.snapshot.browser import (
    PlaywrightBrowserSession,
    PlaywrightBrowserSource,
    RawPageObservation,
)
from ai_ui_explorer.snapshot.collector import CollectionFailedError, SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotLimits
from ai_ui_explorer.task_management.evidence import TaskEvidenceCollector
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


class RecordingEvidenceSink(ExplorationEvidenceSink):
    def __init__(self) -> None:
        self.recorded: list[tuple[object, SnapshotDocument]] = []
        self.completed_with: object | None = None

    def record(self, target: object, snapshot: SnapshotDocument) -> None:
        self.recorded.append((target, snapshot))

    def complete(self, result: object) -> None:
        self.completed_with = result


class _MaliciousTaskBindingCollector(SnapshotCollectorPort):
    def __init__(self, delegate: SnapshotCollectorPort) -> None:
        self._delegate = delegate

    def collect(self, url: str) -> SnapshotDocument:
        return self._delegate.collect(url)

    def is_bound_to_task(self, _task: ExplorationTask) -> bool:
        return True


class _FailingObservationSource:
    def collect(self, url: str, limits: SnapshotLimits) -> RawPageObservation:
        raise RuntimeError("synthetic collector failure with token=secret")


def _readonly_candidate() -> ReadonlyInteractionCandidate:
    return ReadonlyInteractionCandidate(
        kind="switch_tab",
        element_key="details-tab",
        frame_path="main",
        target_summary="详情",
        locator=LocatorCandidateEvidence(
            locator_id="details-tab",
            strategy="css",
            parameters={"selector": "#details-tab"},
            source="generated",
            uniqueness="unique",
            stability="high",
            confidence=1.0,
            rank=1,
            recommended=True,
            frame_path="main",
            evidence_refs=[
                EvidenceReference(
                    evidence_id="evidence-details-tab",
                    snapshot_id="snapshot-1",
                    snapshot_schema_version="1.1",
                    snapshot_sha256="a" * 64,
                    json_pointer="/frames/0",
                    excerpt="safe",
                )
            ],
        ),
    )


def _task_bound_collector(
    task: ExplorationTask,
    *,
    source: object | None = None,
) -> SessionSnapshotCollectorAdapter:
    observation_source = source or FakeSource.with_text("Visible page text")
    return SessionSnapshotCollectorAdapter(
        session=cast(PlaywrightBrowserSession, observation_source),
        task=task,
        limits=SnapshotLimits(),
    )


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


def test_exploration_budget_limits_readonly_interaction_steps_separately() -> None:
    budget = ExplorationBudget(
        max_pages=2,
        max_depth=1,
        max_queue_size=5,
        max_interaction_steps=3,
        max_interactions_per_page=2,
    )

    assert budget.max_interaction_steps == 3
    assert budget.max_interactions_per_page == 2


def test_runner_extracts_interactions_from_redacted_evidence_projection() -> None:
    root_url = "https://app.example.test/root"
    collector = FakeCollector(
        {
            root_url: make_snapshot(
                source={"requested_url": root_url, "final_url": root_url, "title": "Root"}
            )
        }
    )
    evidence = TaskEvidenceCollector()
    received_page_keys: list[str] = []
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        collector=collector,
        evidence_sink=evidence,
        interaction_candidate_extractor=lambda page: received_page_keys.append(page.page_key)
        or [],
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert result.status == "completed"
    assert received_page_keys == [root_url]


def test_runner_does_not_execute_interactions_when_step_budget_is_zero() -> None:
    root_url = "https://app.example.test/root"
    calls: list[ReadonlyInteractionCandidate] = []
    candidate = ReadonlyInteractionCandidate(
        kind="switch_tab",
        element_key="tab",
        frame_path="main",
        target_summary="概览",
        locator=LocatorCandidateEvidence(
            locator_id="tab",
            strategy="css",
            parameters={"selector": "#tab"},
            source="generated",
            uniqueness="unique",
            stability="high",
            confidence=1.0,
            rank=1,
            recommended=True,
            frame_path="main",
            evidence_refs=[
                EvidenceReference(
                    evidence_id="evidence-tab",
                    snapshot_id="snapshot-1",
                    snapshot_schema_version="1.1",
                    snapshot_sha256="a" * 64,
                    json_pointer="/frames/0",
                    excerpt="safe",
                )
            ],
        ),
    )
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(
            max_pages=1,
            max_depth=0,
            max_queue_size=1,
            max_interaction_steps=0,
        ),
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
        evidence_sink=TaskEvidenceCollector(),
        interaction_candidate_extractor=lambda _page: [candidate],
        interaction_executor=lambda item: (
            calls.append(item)
            or ReadonlyInteractionExecution(
                status="executed",
                reason_code="executed",
                safe_message="Interaction executed.",
                url_before=root_url,
                url_after=root_url,
            )
        ),
        interaction_snapshot_collector=lambda: make_snapshot(
            source={"requested_url": root_url, "final_url": root_url, "title": "Root"}
        ),
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert calls == []
    assert "interaction_budget_exhausted" in result.stop_reasons

    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(
            max_pages=1,
            max_depth=0,
            max_queue_size=1,
            max_interaction_steps=1,
        ),
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
        evidence_sink=TaskEvidenceCollector(),
        interaction_candidate_extractor=lambda _page: [candidate],
        interaction_executor=lambda item: (
            calls.append(item)
            or ReadonlyInteractionExecution(
                status="executed",
                reason_code="executed",
                safe_message="Interaction executed.",
                url_before=root_url,
                url_after=root_url,
            )
        ),
        interaction_snapshot_collector=lambda: make_snapshot(
            source={"requested_url": root_url, "final_url": root_url, "title": "Root"}
        ),
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert calls == [candidate]
    assert "interaction_budget_exhausted" not in result.stop_reasons


def test_runner_records_executed_interaction_with_recollected_state() -> None:
    """Removing either the execution result or re-collection must fail this test."""
    root_url = "https://app.example.test/root"
    before_snapshot = make_snapshot(
        source={"requested_url": root_url, "final_url": root_url, "title": "Overview"}
    )
    after_snapshot = make_snapshot(
        source={"requested_url": root_url, "final_url": root_url, "title": "Details"}
    )
    candidate = _readonly_candidate()
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(
            max_pages=1,
            max_depth=0,
            max_queue_size=1,
            max_interaction_steps=1,
        ),
        collector=FakeCollector({root_url: before_snapshot}),
        evidence_sink=TaskEvidenceCollector(),
        interaction_candidate_extractor=lambda _page: [candidate],
        interaction_executor=lambda _candidate: ReadonlyInteractionExecution(
            status="executed",
            reason_code="executed",
            safe_message="Interaction executed.",
            url_before=root_url,
            url_after=root_url,
        ),
        interaction_snapshot_collector=lambda: after_snapshot,
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert result.status == "completed"
    assert len(result.interaction_steps) == 1
    step = result.interaction_steps[0]
    assert step.execution.status == "executed"
    assert step.before_state.fingerprint != step.after_state.fingerprint
    assert len(result.visits) == 2


def test_runner_marks_unchanged_post_interaction_state_as_partial() -> None:
    """Removing post-click state validation would incorrectly report completion."""
    root_url = "https://app.example.test/root"
    snapshot = make_snapshot(
        source={"requested_url": root_url, "final_url": root_url, "title": "Overview"}
    )
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(
            max_pages=1,
            max_depth=0,
            max_queue_size=1,
            max_interaction_steps=1,
        ),
        collector=FakeCollector({root_url: snapshot}),
        evidence_sink=TaskEvidenceCollector(),
        interaction_candidate_extractor=lambda _page: [_readonly_candidate()],
        interaction_executor=lambda _candidate: ReadonlyInteractionExecution(
            status="executed",
            reason_code="executed",
            safe_message="Interaction executed.",
            url_before=root_url,
            url_after=root_url,
        ),
        interaction_snapshot_collector=lambda: snapshot,
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert result.status == "partial"
    assert "interaction_state_unchanged" in result.stop_reasons


def test_runner_records_successful_snapshots_in_evidence_sink() -> None:
    root_url = "https://app.example.test/root"
    snapshot = make_snapshot(
        source={
            "requested_url": root_url,
            "final_url": root_url,
            "title": "Root",
        }
    )
    sink = RecordingEvidenceSink()
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        collector=FakeCollector({root_url: snapshot}),
        evidence_sink=sink,
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert [target.url for target, _snapshot in sink.recorded] == [root_url]
    assert sink.completed_with is result


def test_runner_completes_bound_task_and_notifies_terminal_callback() -> None:
    root_url = "https://app.example.test/root"
    task = ExplorationTask.create(task_id="task-1")
    observed_states: list[ExplorationTaskState] = []
    task.register_terminal_callback(lambda: observed_states.append(task.state))
    task.start_collection()
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        collector=_task_bound_collector(task),
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
        collector=_task_bound_collector(
            task,
            source=_FailingObservationSource(),
        ),
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


def test_runner_rejects_task_not_bound_to_collector() -> None:
    collector_task = ExplorationTask.create(task_id="collector-task")
    runner_task = ExplorationTask.create(task_id="runner-task")

    with pytest.raises(
        ValueError,
        match=r"^Exploration collector is not bound to task\.$",
    ):
        ExplorationRunner(
            policy=NavigationPolicy(
                allowed_origins=["https://app.example.test"]
            ),
            budget=ExplorationBudget(
                max_pages=1,
                max_depth=0,
                max_queue_size=1,
            ),
            collector=_task_bound_collector(collector_task),
            task=runner_task,
        )


def test_runner_rejects_wrapper_that_self_reports_task_binding() -> None:
    task = ExplorationTask.create(task_id="task-1")
    wrapped = _MaliciousTaskBindingCollector(
        _task_bound_collector(task)
    )

    with pytest.raises(
        ValueError,
        match=r"^Exploration collector is not bound to task\.$",
    ):
        ExplorationRunner(
            policy=NavigationPolicy(
                allowed_origins=["https://app.example.test"]
            ),
            budget=ExplorationBudget(
                max_pages=1,
                max_depth=0,
                max_queue_size=1,
            ),
            collector=wrapped,
            task=task,
        )


def test_runner_marks_bound_task_failed_when_candidate_extractor_raises() -> None:
    root_url = "https://app.example.test/root"
    task = ExplorationTask.create(task_id="task-1")
    observed_states: list[ExplorationTaskState] = []
    task.register_terminal_callback(lambda: observed_states.append(task.state))
    task.start_collection()

    def fail_candidate_extraction(
        _snapshot: SnapshotDocument,
    ) -> list[NavigationCandidate]:
        raise RuntimeError("unsafe candidate failure token=secret")

    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        collector=_task_bound_collector(task),
        candidate_extractor=fail_candidate_extraction,
        task=task,
    )

    with pytest.raises(RuntimeError, match="unsafe candidate failure"):
        runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert task.state == ExplorationTaskState.FAILED
    assert task.audit_events[-1].event_type == "task_failed"
    assert task.audit_events[-1].reason_code == "runner_failure"
    assert "secret" not in task.model_dump_json()
    assert observed_states == [ExplorationTaskState.FAILED]


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


def test_runner_stops_before_next_target_after_cancellation() -> None:
    root_url = "https://app.example.test/root"
    detail_url = "https://app.example.test/detail"
    token = ExplorationCancellationToken()

    class CancellingCollector(FakeCollector):
        def collect(self, url: str) -> SnapshotDocument:
            snapshot = super().collect(url)
            if url == root_url:
                token.cancel()
            return snapshot

    collector = CancellingCollector(
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
        budget=ExplorationBudget(max_pages=2, max_depth=1, max_queue_size=2),
        collector=collector,
        cancellation_token=token,
    )

    result = runner.run(modules=[ModuleEntry(module_id="root", url=root_url)])

    assert collector.collected_urls == [root_url]
    assert result.status == "partial"
    assert result.stop_reasons == ["cancelled"]


def test_runner_does_not_override_a_task_cancelled_during_execution() -> None:
    task = ExplorationTask.create(task_id="task-1")
    task.start_collection()
    task.cancel(reason_code="user_cancelled")
    token = ExplorationCancellationToken()
    token.cancel()
    runner = ExplorationRunner(
        policy=NavigationPolicy(allowed_origins=["https://app.example.test"]),
        budget=ExplorationBudget(max_pages=1, max_depth=0, max_queue_size=1),
        collector=_task_bound_collector(task),
        task=task,
        cancellation_token=token,
    )

    result = runner.run(
        modules=[ModuleEntry(module_id="root", url="https://app.example.test/root")]
    )

    assert result.status == "partial"
    assert task.state == ExplorationTaskState.CANCELLED


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
