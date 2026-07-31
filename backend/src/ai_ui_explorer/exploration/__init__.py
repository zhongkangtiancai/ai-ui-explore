"""Sprint 4 controlled exploration foundations."""

from ai_ui_explorer.exploration.candidates import extract_navigation_candidates
from ai_ui_explorer.exploration.collector_adapter import SnapshotCollectorAdapter
from ai_ui_explorer.exploration.policy import (
    ActionDecision,
    ActionGate,
    CandidateAction,
    NavigationDecision,
    NavigationPolicy,
    NavigationPolicyViolation,
)
from ai_ui_explorer.exploration.queue import (
    BoundedExplorationQueue,
    EnqueueDecision,
    ExplorationBudget,
    ExplorationTarget,
    ModuleEntry,
    NavigationCandidate,
    SnapshotVisitResult,
)
from ai_ui_explorer.exploration.runner import (
    CandidateExtractor,
    ExplorationRunError,
    ExplorationRunner,
    ExplorationRunResult,
    SnapshotCollectorPort,
)
from ai_ui_explorer.exploration.state import (
    StateDeduplicator,
    StateFingerprint,
    fingerprint_snapshot,
)
from ai_ui_explorer.exploration.task import (
    AuditEvent,
    ExplorationTask,
    ExplorationTaskError,
    ExplorationTaskState,
)

__all__ = [
    "ActionDecision",
    "ActionGate",
    "AuditEvent",
    "BoundedExplorationQueue",
    "CandidateAction",
    "CandidateExtractor",
    "EnqueueDecision",
    "ExplorationBudget",
    "ExplorationRunError",
    "ExplorationRunResult",
    "ExplorationRunner",
    "ExplorationTask",
    "ExplorationTaskError",
    "ExplorationTaskState",
    "ExplorationTarget",
    "ModuleEntry",
    "NavigationCandidate",
    "NavigationDecision",
    "NavigationPolicy",
    "NavigationPolicyViolation",
    "SnapshotCollectorPort",
    "SnapshotCollectorAdapter",
    "SnapshotVisitResult",
    "StateDeduplicator",
    "StateFingerprint",
    "fingerprint_snapshot",
    "extract_navigation_candidates",
]
