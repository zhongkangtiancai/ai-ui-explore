"""Deterministic, redacted projections for observed readonly workflows."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Literal

from pydantic import Field

from ai_ui_explorer.exploration.interactions import ReadonlyInteractionKind
from ai_ui_explorer.exploration.runner import ReadonlyInteractionStep
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.models import EvidenceReference


class InteractionStepView(DeepFrozenModel):
    step_id: str = Field(pattern=r"^step-[0-9a-f]{16}$")
    kind: ReadonlyInteractionKind
    target_summary: str = Field(min_length=1, max_length=500)
    before_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_state: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal["executed", "skipped", "paused", "failed"]
    reason_code: str = Field(min_length=1, max_length=100)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=12)


class WorkflowNodeView(DeepFrozenModel):
    state: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkflowEdgeView(DeepFrozenModel):
    edge_id: str = Field(pattern=r"^edge-[0-9a-f]{16}$")
    source_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_state: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: ReadonlyInteractionKind
    observation_count: int = Field(ge=1)
    evidence_refs: list[EvidenceReference] = Field(min_length=1, max_length=12)


class TaskWorkflowExport(DeepFrozenModel):
    task_id: str = Field(pattern=r"^task-[0-9]{1,20}$")
    state: Literal["completed", "partial", "failed", "cancelled"]
    steps: list[InteractionStepView] = Field(default_factory=list, max_length=1_000)
    nodes: list[WorkflowNodeView] = Field(default_factory=list, max_length=1_000)
    edges: list[WorkflowEdgeView] = Field(default_factory=list, max_length=1_000)


def project_interaction_steps(steps: list[ReadonlyInteractionStep]) -> list[InteractionStepView]:
    return [
        InteractionStepView(
            step_id=f"step-{_stable_id(index, step.candidate.element_key)}",
            kind=step.candidate.kind,
            target_summary=step.candidate.target_summary,
            before_state=step.before_state.fingerprint,
            after_state=(step.after_state.fingerprint if step.after_state is not None else None),
            status=step.execution.status,
            reason_code=step.execution.reason_code,
            evidence_refs=list(step.candidate.locator.evidence_refs),
        )
        for index, step in enumerate(steps, start=1)
    ]


def build_workflow_graph(
    steps: list[InteractionStepView],
) -> tuple[list[WorkflowNodeView], list[WorkflowEdgeView]]:
    grouped: dict[tuple[str, str, ReadonlyInteractionKind, str], list[InteractionStepView]] = (
        defaultdict(list)
    )
    states: set[str] = set()
    for step in steps:
        if (
            step.status != "executed"
            or step.after_state is None
            or step.after_state == step.before_state
        ):
            continue
        states.update({step.before_state, step.after_state})
        grouped[(step.before_state, step.after_state, step.kind, step.target_summary)].append(step)
    nodes = [WorkflowNodeView(state=state) for state in sorted(states)]
    edges = [
        WorkflowEdgeView(
            edge_id=f"edge-{_stable_id(*key)}",
            source_state=key[0],
            target_state=key[1],
            kind=key[2],
            observation_count=len(group),
            evidence_refs=_bounded_evidence_refs(group),
        )
        for key, group in sorted(grouped.items())
    ]
    return nodes, edges


def build_task_workflow(
    *,
    task_id: str,
    state: Literal["completed", "partial", "failed", "cancelled"],
    steps: list[ReadonlyInteractionStep],
) -> TaskWorkflowExport:
    projected_steps = project_interaction_steps(steps)
    nodes, edges = build_workflow_graph(projected_steps)
    return TaskWorkflowExport(
        task_id=task_id,
        state=state,
        steps=projected_steps,
        nodes=nodes,
        edges=edges,
    )


def _bounded_evidence_refs(steps: list[InteractionStepView]) -> list[EvidenceReference]:
    refs: dict[str, EvidenceReference] = {}
    for step in steps:
        for reference in step.evidence_refs:
            refs.setdefault(reference.evidence_id, reference)
    return [refs[key] for key in sorted(refs)[:12]]


def _stable_id(*values: object) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
