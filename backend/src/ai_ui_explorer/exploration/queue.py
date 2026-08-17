"""Bounded queue primitives for controlled exploration."""

from collections import deque

from pydantic import Field

from ai_ui_explorer.exploration.policy import (
    ActionGate,
    ActionType,
    CandidateAction,
    NavigationPolicy,
)
from ai_ui_explorer.exploration.state import StateDeduplicator, StateFingerprint
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.snapshot.models import AnySnapshotDocument


class ExplorationBudget(DeepFrozenModel):
    max_pages: int = Field(default=20, ge=1, le=1_000)
    max_depth: int = Field(default=2, ge=0, le=20)
    max_queue_size: int = Field(default=100, ge=1, le=10_000)
    max_interaction_steps: int = Field(default=20, ge=0, le=1_000)
    max_interactions_per_page: int = Field(default=5, ge=0, le=100)


class ModuleEntry(DeepFrozenModel):
    module_id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=200)


class NavigationCandidate(DeepFrozenModel):
    url: str = Field(min_length=1)
    action_type: ActionType
    label: str | None = Field(default=None, max_length=200)


class ExplorationTarget(DeepFrozenModel):
    url: str = Field(min_length=1)
    depth: int = Field(ge=0)
    source_url: str | None
    module_id: str | None
    action_type: ActionType
    label: str | None


class EnqueueDecision(DeepFrozenModel):
    accepted: bool
    url: str | None
    reason_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)


class SnapshotVisitResult(DeepFrozenModel):
    """One internal visit plus bounded counts derived from its snapshot."""

    target: ExplorationTarget
    state_fingerprint: StateFingerprint
    element_count: int = Field(default=0, ge=0)
    link_count: int = Field(default=0, ge=0)

    @property
    def seen_before(self) -> bool:
        return self.state_fingerprint.seen_before


class BoundedExplorationQueue:
    def __init__(
        self,
        *,
        policy: NavigationPolicy,
        budget: ExplorationBudget,
        action_gate: ActionGate | None = None,
        state_deduplicator: StateDeduplicator | None = None,
    ) -> None:
        self._policy = policy
        self._budget = budget
        self._action_gate = action_gate or ActionGate()
        self._state_deduplicator = state_deduplicator or StateDeduplicator()
        self._pending: deque[ExplorationTarget] = deque()
        self._known_urls: set[str] = set()
        self._visited_count = 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def visited_count(self) -> int:
        return self._visited_count

    def seed_modules(self, entries: list[ModuleEntry]) -> list[EnqueueDecision]:
        decisions: list[EnqueueDecision] = []
        for entry in entries:
            decisions.append(
                self._enqueue(
                    url=entry.url,
                    depth=0,
                    source_url=None,
                    module_id=entry.module_id,
                    action_type="module_entry",
                    label=entry.label,
                )
            )
        return decisions

    def enqueue_candidates(
        self,
        *,
        source: ExplorationTarget | None,
        candidates: list[NavigationCandidate],
    ) -> list[EnqueueDecision]:
        if source is None:
            return [_reject("missing_source") for _candidate in candidates]
        decisions: list[EnqueueDecision] = []
        for candidate in candidates:
            decisions.append(
                self._enqueue(
                    url=candidate.url,
                    depth=source.depth + 1,
                    source_url=source.url,
                    module_id=source.module_id,
                    action_type=candidate.action_type,
                    label=candidate.label,
                )
            )
        return decisions

    def next_target(self) -> ExplorationTarget | None:
        if not self._pending:
            return None
        return self._pending.popleft()

    def record_snapshot_result(
        self,
        target: ExplorationTarget,
        snapshot: AnySnapshotDocument,
    ) -> SnapshotVisitResult:
        self._visited_count += 1
        return SnapshotVisitResult(
            target=target,
            state_fingerprint=self._state_deduplicator.observe(snapshot),
            element_count=sum(len(frame.elements) for frame in snapshot.frames),
            link_count=sum(
                getattr(element, "href", None) is not None
                for frame in snapshot.frames
                for element in frame.elements
            ),
        )

    def _enqueue(
        self,
        *,
        url: str,
        depth: int,
        source_url: str | None,
        module_id: str | None,
        action_type: ActionType,
        label: str | None,
    ) -> EnqueueDecision:
        action_decision = self._action_gate.evaluate(
            CandidateAction(
                action_type=action_type,
                label=label,
                target_url=url,
            )
        )
        if not action_decision.allowed:
            return EnqueueDecision(
                accepted=False,
                url=None,
                reason_code=action_decision.reason_code,
                safe_message=action_decision.safe_message,
            )
        navigation_decision = self._policy.evaluate(url)
        if not navigation_decision.allowed:
            return EnqueueDecision(
                accepted=False,
                url=None,
                reason_code=navigation_decision.reason_code,
                safe_message=navigation_decision.safe_message,
            )
        assert navigation_decision.normalized_url is not None
        normalized_url = navigation_decision.normalized_url
        if normalized_url in self._known_urls:
            return _reject("duplicate_url")
        if depth > self._budget.max_depth:
            return _reject("max_depth")
        if len(self._known_urls) >= self._budget.max_pages:
            return _reject("max_pages")
        if len(self._pending) >= self._budget.max_queue_size:
            return _reject("queue_limit")
        target = ExplorationTarget(
            url=normalized_url,
            depth=depth,
            source_url=source_url,
            module_id=module_id,
            action_type=action_type,
            label=label,
        )
        self._known_urls.add(normalized_url)
        self._pending.append(target)
        return EnqueueDecision(
            accepted=True,
            url=normalized_url,
            reason_code="enqueued",
            safe_message="Navigation target enqueued.",
        )


def _reject(reason_code: str) -> EnqueueDecision:
    return EnqueueDecision(
        accepted=False,
        url=None,
        reason_code=reason_code,
        safe_message="Navigation target rejected.",
    )
