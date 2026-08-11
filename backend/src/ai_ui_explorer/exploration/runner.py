"""Bounded exploration runner with injectable collection and candidate extraction."""

from collections.abc import Callable
from threading import Event
from typing import Literal, Protocol

from pydantic import Field

from ai_ui_explorer.exploration.candidates import extract_navigation_candidates
from ai_ui_explorer.exploration.collector_adapter import (
    _session_collector_matches_task,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import (
    BoundedExplorationQueue,
    EnqueueDecision,
    ExplorationBudget,
    ModuleEntry,
    NavigationCandidate,
    SnapshotVisitResult,
)
from ai_ui_explorer.exploration.task import ExplorationTask
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.snapshot.models import SnapshotDocument


class SnapshotCollectorPort(Protocol):
    def collect(self, url: str) -> SnapshotDocument:
        """Collect one already policy-approved URL into a Snapshot document."""


class ExplorationCancellationToken:
    """Thread-safe, one-way cancellation signal for bounded exploration."""

    def __init__(self) -> None:
        self._cancelled = Event()

    def cancel(self) -> None:
        """Request cooperative cancellation without exposing thread handles."""
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        """Return whether the runner must stop before its next target."""
        return self._cancelled.is_set()


CandidateExtractor = Callable[[SnapshotDocument], list[NavigationCandidate]]


class ExplorationRunError(DeepFrozenModel):
    url: str
    reason_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)


class ExplorationRunResult(DeepFrozenModel):
    status: Literal["completed", "partial"]
    visits: list[SnapshotVisitResult]
    enqueue_decisions: list[EnqueueDecision]
    errors: list[ExplorationRunError]
    stop_reasons: list[str]


class ExplorationRunner:
    def __init__(
        self,
        *,
        policy: NavigationPolicy,
        budget: ExplorationBudget,
        collector: SnapshotCollectorPort,
        candidate_extractor: CandidateExtractor = extract_navigation_candidates,
        task: ExplorationTask | None = None,
        cancellation_token: ExplorationCancellationToken | None = None,
    ) -> None:
        if task is not None and not _session_collector_matches_task(
            collector,
            task,
        ):
            raise ValueError("Exploration collector is not bound to task.")
        self._queue = BoundedExplorationQueue(policy=policy, budget=budget)
        self._collector = collector
        self._candidate_extractor = candidate_extractor
        self._task = task
        self._cancellation_token = cancellation_token or ExplorationCancellationToken()

    def run(self, *, modules: list[ModuleEntry]) -> ExplorationRunResult:
        result: ExplorationRunResult | None = None
        try:
            result = self._run(modules=modules)
            return result
        finally:
            self._finalize_task(result)

    def _run(self, *, modules: list[ModuleEntry]) -> ExplorationRunResult:
        enqueue_decisions = self._queue.seed_modules(modules)
        visits: list[SnapshotVisitResult] = []
        errors: list[ExplorationRunError] = []
        stop_reasons: list[str] = []

        while True:
            if self._cancellation_token.is_cancelled:
                stop_reasons.append("cancelled")
                break
            target = self._queue.next_target()
            if target is None:
                break
            try:
                snapshot = self._collector.collect(target.url)
            except Exception:
                errors.append(
                    ExplorationRunError(
                        url=target.url,
                        reason_code="collector_failure",
                        safe_message="Snapshot collection failed.",
                    )
                )
                stop_reasons.append("collector_failure")
                continue
            visit = self._queue.record_snapshot_result(target, snapshot)
            visits.append(visit)
            if visit.seen_before:
                stop_reasons.append("duplicate_state")
                continue
            enqueue_decisions.extend(
                self._queue.enqueue_candidates(
                    source=target,
                    candidates=self._candidate_extractor(snapshot),
                )
            )

        return ExplorationRunResult(
            status="partial" if errors or "cancelled" in stop_reasons else "completed",
            visits=visits,
            enqueue_decisions=enqueue_decisions,
            errors=errors,
            stop_reasons=sorted(set(stop_reasons)),
        )

    def _finalize_task(self, result: ExplorationRunResult | None) -> None:
        if self._task is None:
            return
        if self._task.state in {
            "completed",
            "partial",
            "failed",
            "cancelled",
        }:
            return
        if result is None:
            self._task.fail(reason_code="runner_failure")
        elif result.status == "completed":
            self._task.complete()
        else:
            self._task.mark_partial(reason_code="collector_failure")
