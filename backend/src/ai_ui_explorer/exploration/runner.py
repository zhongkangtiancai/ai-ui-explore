"""Bounded exploration runner with injectable collection and candidate extraction."""

from collections.abc import Callable
from threading import Event
from typing import Literal, Protocol

from pydantic import Field

from ai_ui_explorer.exploration.candidates import extract_navigation_candidates
from ai_ui_explorer.exploration.collector_adapter import (
    _session_collector_matches_task,
)
from ai_ui_explorer.exploration.interactions import (
    ReadonlyInteractionCandidate,
    ReadonlyInteractionExecution,
    ReadonlyInteractionGate,
)
from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.exploration.queue import (
    BoundedExplorationQueue,
    EnqueueDecision,
    ExplorationBudget,
    ExplorationTarget,
    ModuleEntry,
    NavigationCandidate,
    SnapshotVisitResult,
)
from ai_ui_explorer.exploration.state import StateFingerprint
from ai_ui_explorer.exploration.task import ExplorationTask
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.models import PageEvidence
from ai_ui_explorer.snapshot.models import SnapshotDocument


class SnapshotCollectorPort(Protocol):
    def collect(self, url: str) -> SnapshotDocument:
        """Collect one already policy-approved URL into a Snapshot document."""


class ExplorationEvidenceSink(Protocol):
    """Receive successful, validated Snapshots without browser runtime objects."""

    def record(
        self,
        target: "ExplorationTarget",
        snapshot: SnapshotDocument,
    ) -> PageEvidence | None:
        """Record one successful Snapshot visit."""

    def complete(self, result: "ExplorationRunResult") -> None:
        """Observe the final completed or partial run."""


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
InteractionCandidateExtractor = Callable[[PageEvidence], list[ReadonlyInteractionCandidate]]
InteractionExecutor = Callable[[ReadonlyInteractionCandidate], ReadonlyInteractionExecution]
InteractionSnapshotCollector = Callable[[], SnapshotDocument]


class ExplorationRunError(DeepFrozenModel):
    url: str
    reason_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)


class ReadonlyInteractionStep(DeepFrozenModel):
    """One bounded interaction attempt and its observed page-state transition."""

    candidate: ReadonlyInteractionCandidate
    execution: ReadonlyInteractionExecution
    before_state: StateFingerprint
    after_state: StateFingerprint | None = None


class ExplorationRunResult(DeepFrozenModel):
    status: Literal["completed", "partial"]
    visits: list[SnapshotVisitResult]
    enqueue_decisions: list[EnqueueDecision]
    errors: list[ExplorationRunError]
    stop_reasons: list[str]
    interaction_steps: list[ReadonlyInteractionStep] = Field(default_factory=list)


class ExplorationRunner:
    def __init__(
        self,
        *,
        policy: NavigationPolicy,
        budget: ExplorationBudget,
        collector: SnapshotCollectorPort,
        candidate_extractor: CandidateExtractor = extract_navigation_candidates,
        interaction_candidate_extractor: InteractionCandidateExtractor | None = None,
        interaction_executor: InteractionExecutor | None = None,
        interaction_snapshot_collector: InteractionSnapshotCollector | None = None,
        task: ExplorationTask | None = None,
        cancellation_token: ExplorationCancellationToken | None = None,
        evidence_sink: ExplorationEvidenceSink | None = None,
    ) -> None:
        if task is not None and not _session_collector_matches_task(
            collector,
            task,
        ):
            raise ValueError("Exploration collector is not bound to task.")
        self._queue = BoundedExplorationQueue(policy=policy, budget=budget)
        self._budget = budget
        self._policy = policy
        self._collector = collector
        self._candidate_extractor = candidate_extractor
        self._interaction_candidate_extractor = interaction_candidate_extractor
        self._interaction_executor = interaction_executor
        self._interaction_snapshot_collector = interaction_snapshot_collector
        self._task = task
        self._cancellation_token = cancellation_token or ExplorationCancellationToken()
        self._evidence_sink = evidence_sink

    def run(self, *, modules: list[ModuleEntry]) -> ExplorationRunResult:
        result: ExplorationRunResult | None = None
        try:
            result = self._run(modules=modules)
            return result
        finally:
            if result is not None and self._evidence_sink is not None:
                self._evidence_sink.complete(result)
            self._finalize_task(result)

    def _run(self, *, modules: list[ModuleEntry]) -> ExplorationRunResult:
        enqueue_decisions = self._queue.seed_modules(modules)
        visits: list[SnapshotVisitResult] = []
        errors: list[ExplorationRunError] = []
        stop_reasons: list[str] = []
        interaction_steps: list[ReadonlyInteractionStep] = []
        remaining_interaction_steps = self._budget.max_interaction_steps

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
            if self._evidence_sink is not None:
                page_evidence = self._evidence_sink.record(target, snapshot)
                if visit.seen_before:
                    stop_reasons.append("duplicate_state")
                    continue
                if page_evidence is not None and self._interaction_candidate_extractor is not None:
                    interaction_candidates = self._interaction_candidate_extractor(page_evidence)
                    if (
                        interaction_candidates
                        and self._interaction_executor is not None
                        and self._interaction_snapshot_collector is not None
                    ):
                        for candidate in interaction_candidates[
                            : self._budget.max_interactions_per_page
                        ]:
                            if remaining_interaction_steps == 0:
                                stop_reasons.append("interaction_budget_exhausted")
                                break
                            decision = ReadonlyInteractionGate().evaluate(
                                candidate,
                                self._policy,
                            )
                            if not decision.allowed:
                                interaction_steps.append(
                                    ReadonlyInteractionStep(
                                        candidate=candidate,
                                        execution=ReadonlyInteractionExecution(
                                            status="paused",
                                            reason_code=decision.reason_code,
                                            safe_message="Interaction paused by policy.",
                                            url_before=target.url,
                                        ),
                                        before_state=visit.state_fingerprint,
                                    )
                                )
                                stop_reasons.append("interaction_denied")
                                break
                            execution = self._interaction_executor(candidate)
                            remaining_interaction_steps -= 1
                            if execution.status != "executed":
                                interaction_steps.append(
                                    ReadonlyInteractionStep(
                                        candidate=candidate,
                                        execution=execution,
                                        before_state=visit.state_fingerprint,
                                    )
                                )
                                stop_reasons.append("interaction_execution_failed")
                                break
                            if (
                                execution.url_after is None
                                or not self._policy.evaluate(execution.url_after).allowed
                            ):
                                interaction_steps.append(
                                    ReadonlyInteractionStep(
                                        candidate=candidate,
                                        execution=execution.model_copy(
                                            update={
                                                "status": "failed",
                                                "reason_code": "post_interaction_origin_denied",
                                                "safe_message": (
                                                    "Interaction navigation denied by policy."
                                                ),
                                            }
                                        ),
                                        before_state=visit.state_fingerprint,
                                    )
                                )
                                stop_reasons.append("interaction_origin_denied")
                                break
                            try:
                                after_snapshot = self._interaction_snapshot_collector()
                            except Exception:
                                interaction_steps.append(
                                    ReadonlyInteractionStep(
                                        candidate=candidate,
                                        execution=execution.model_copy(
                                            update={
                                                "status": "failed",
                                                "reason_code": "post_interaction_collection_failed",
                                                "safe_message": (
                                                    "Post-interaction collection failed."
                                                ),
                                            }
                                        ),
                                        before_state=visit.state_fingerprint,
                                    )
                                )
                                stop_reasons.append("interaction_collection_failed")
                                break
                            after_visit = self._queue.record_snapshot_result(
                                target,
                                after_snapshot,
                            )
                            visits.append(after_visit)
                            self._evidence_sink.record(target, after_snapshot)
                            interaction_steps.append(
                                ReadonlyInteractionStep(
                                    candidate=candidate,
                                    execution=execution,
                                    before_state=visit.state_fingerprint,
                                    after_state=after_visit.state_fingerprint,
                                )
                            )
                            if after_visit.seen_before:
                                stop_reasons.append("interaction_state_unchanged")
                                break
            elif visit.seen_before:
                stop_reasons.append("duplicate_state")
                continue
            enqueue_decisions.extend(
                self._queue.enqueue_candidates(
                    source=target,
                    candidates=self._candidate_extractor(snapshot),
                )
            )

        return ExplorationRunResult(
            status=(
                "partial"
                if errors
                or "cancelled" in stop_reasons
                or any(reason.startswith("interaction_") for reason in stop_reasons)
                else "completed"
            ),
            visits=visits,
            enqueue_decisions=enqueue_decisions,
            errors=errors,
            stop_reasons=sorted(set(stop_reasons)),
            interaction_steps=interaction_steps,
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
