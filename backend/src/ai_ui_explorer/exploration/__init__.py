"""Sprint 4 controlled exploration foundations."""

from ai_ui_explorer.exploration.policy import (
    ActionDecision,
    ActionGate,
    CandidateAction,
    NavigationDecision,
    NavigationPolicy,
    NavigationPolicyViolation,
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
    "CandidateAction",
    "ExplorationTask",
    "ExplorationTaskError",
    "ExplorationTaskState",
    "NavigationDecision",
    "NavigationPolicy",
    "NavigationPolicyViolation",
    "StateDeduplicator",
    "StateFingerprint",
    "fingerprint_snapshot",
]
