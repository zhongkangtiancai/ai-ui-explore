"""Safe discovery and gating for bounded read-only UI interactions."""

from typing import Literal

from pydantic import Field

from ai_ui_explorer.exploration.policy import NavigationPolicy
from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.permission_comparison.models import (
    ElementEvidence,
    LocatorCandidateEvidence,
    PageEvidence,
)

ReadonlyInteractionKind = Literal[
    "expand",
    "collapse",
    "switch_tab",
    "open_menu",
    "paginate",
    "view_details",
]

_KIND_ORDER: dict[ReadonlyInteractionKind, int] = {
    "expand": 0,
    "collapse": 1,
    "switch_tab": 2,
    "open_menu": 3,
    "paginate": 4,
    "view_details": 5,
}
_DANGEROUS_TERMS = frozenset(
    {
        "delete",
        "remove",
        "submit",
        "approve",
        "publish",
        "pay",
        "grant",
        "upload",
        "download",
        "删除",
        "移除",
        "提交",
        "审批",
        "发布",
        "支付",
        "授权",
        "上传",
        "下载",
    }
)
_DETAIL_TERMS = frozenset({"detail", "details", "查看详情", "详情"})
_PAGE_TERMS = frozenset({"next", "previous", "page", "下一页", "上一页", "分页"})
_MENU_TERMS = frozenset({"menu", "菜单"})


class ReadonlyInteractionCandidate(DeepFrozenModel):
    """One safely projected, non-mutating UI interaction candidate."""

    kind: ReadonlyInteractionKind
    element_key: str = Field(min_length=1, max_length=300)
    frame_path: str = Field(min_length=1, max_length=500)
    locator: LocatorCandidateEvidence
    target_summary: str = Field(min_length=1, max_length=500)
    target_url: str | None = Field(default=None, max_length=2_048)


class InteractionDecision(DeepFrozenModel):
    allowed: bool
    reason_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)


class ReadonlyInteractionExecution(DeepFrozenModel):
    """Fixed, non-sensitive outcome of one browser interaction attempt."""

    status: Literal["executed", "skipped", "paused", "failed"]
    reason_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)
    url_before: str = Field(min_length=1)
    url_after: str | None = Field(default=None, min_length=1)


class ReadonlyInteractionGate:
    """Default-deny policy for candidates already projected from page evidence."""

    def evaluate(
        self,
        candidate: ReadonlyInteractionCandidate,
        navigation_policy: NavigationPolicy,
    ) -> InteractionDecision:
        if _contains_dangerous_term(candidate.target_summary):
            return _deny("dangerous_semantics")
        if candidate.locator.uniqueness != "unique" or not candidate.locator.recommended:
            return _deny("locator_not_unique")
        if candidate.target_url is not None:
            navigation = navigation_policy.evaluate(candidate.target_url)
            if not navigation.allowed:
                return InteractionDecision(
                    allowed=False,
                    reason_code=navigation.reason_code,
                    safe_message="Interaction denied by policy.",
                )
        return InteractionDecision(
            allowed=True,
            reason_code="readonly_interaction_allowed",
            safe_message="Interaction allowed.",
        )


def extract_readonly_interaction_candidates(
    page: PageEvidence,
) -> list[ReadonlyInteractionCandidate]:
    """Return ordered candidates that meet the structural read-only allowlist."""

    candidates: list[ReadonlyInteractionCandidate] = []
    for element in page.elements:
        kind = _classify_element(element)
        locator = _unique_recommended_locator(element.locator_candidates)
        target_summary = element.accessible_name or element.text
        if kind is None or locator is None or target_summary is None:
            continue
        candidates.append(
            ReadonlyInteractionCandidate(
                kind=kind,
                element_key=element.element_key,
                frame_path=element.frame_path,
                locator=locator,
                target_summary=target_summary,
                target_url=element.href if kind in {"paginate", "view_details"} else None,
            )
        )
    return sorted(
        candidates,
        key=lambda item: (_KIND_ORDER[item.kind], item.element_key, item.locator.rank),
    )


def _classify_element(element: ElementEvidence) -> ReadonlyInteractionKind | None:
    role = element.role
    tag = element.tag
    attributes = element.attributes
    target_summary = element.accessible_name or element.text or ""
    href = element.href
    lowered = target_summary.casefold()
    if _contains_dangerous_term(target_summary) or tag in {"input", "textarea", "select"}:
        return None
    if role == "tab":
        return "switch_tab"
    if attributes.get("aria-expanded") == "true":
        return "collapse"
    if attributes.get("aria-expanded") == "false":
        return "expand"
    if attributes.get("aria-haspopup") == "true" or any(term in lowered for term in _MENU_TERMS):
        return "open_menu"
    if href is not None and any(term in lowered for term in _PAGE_TERMS):
        return "paginate"
    if href is not None and any(term in lowered for term in _DETAIL_TERMS):
        return "view_details"
    return None


def _unique_recommended_locator(
    candidates: list[LocatorCandidateEvidence],
) -> LocatorCandidateEvidence | None:
    for candidate in sorted(candidates, key=lambda item: (item.rank, item.locator_id)):
        if candidate.recommended and candidate.uniqueness == "unique":
            return candidate
    return None


def _contains_dangerous_term(value: str) -> bool:
    lowered = value.casefold()
    return any(term in lowered for term in _DANGEROUS_TERMS)


def _deny(reason_code: str) -> InteractionDecision:
    return InteractionDecision(
        allowed=False,
        reason_code=reason_code,
        safe_message="Interaction denied by policy.",
    )
