"""Risk gates for controlled navigation and interaction candidates."""

from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel

ActionType = Literal[
    "link_navigation",
    "browser_back",
    "module_entry",
    "button_click",
    "form_submit",
    "input_fill",
    "file_upload",
    "dangerous_business_action",
    "unknown",
]

_READONLY_ACTIONS = frozenset(
    {"link_navigation", "browser_back", "module_entry"}
)


class NavigationPolicyViolation(RuntimeError):
    """Safe navigation denial surface."""


class NavigationDecision(DeepFrozenModel):
    allowed: bool
    normalized_url: str | None
    origin: str | None
    reason_code: str = Field(min_length=1)
    safe_message: str = Field(min_length=1)


class NavigationPolicy(DeepFrozenModel):
    allowed_origins: list[str] = Field(min_length=1)
    authentication_origins: list[str] = Field(default_factory=list)
    allow_local_http: bool = False

    @field_validator("allowed_origins", "authentication_origins")
    @classmethod
    def normalize_origins(cls, value: list[str]) -> list[str]:
        return sorted({_normalize_origin(origin) for origin in value})

    def evaluate(
        self,
        url: str,
        *,
        authentication_handoff: bool = False,
    ) -> NavigationDecision:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            return _deny("userinfo_not_allowed")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return _deny("invalid_url")
        origin = _origin_from_parts(parsed.scheme, parsed.hostname, parsed.port)
        if parsed.scheme != "https" and not (
            self.allow_local_http and _is_local_origin(origin)
        ):
            return NavigationDecision(
                allowed=False,
                normalized_url=None,
                origin=origin,
                reason_code="https_required",
                safe_message="Navigation denied by policy.",
            )
        if origin in set(self.allowed_origins):
            return NavigationDecision(
                allowed=True,
                normalized_url=url,
                origin=origin,
                reason_code="allowed_origin",
                safe_message="Navigation allowed.",
            )
        if authentication_handoff and origin in set(self.authentication_origins):
            return NavigationDecision(
                allowed=True,
                normalized_url=url,
                origin=origin,
                reason_code="authentication_origin",
                safe_message="Navigation allowed for authentication handoff.",
            )
        return NavigationDecision(
            allowed=False,
            normalized_url=None,
            origin=origin,
            reason_code="origin_not_allowed",
            safe_message="Navigation denied by policy.",
        )

    def assert_allowed(
        self,
        url: str,
        *,
        authentication_handoff: bool = False,
    ) -> NavigationDecision:
        decision = self.evaluate(
            url,
            authentication_handoff=authentication_handoff,
        )
        if not decision.allowed:
            raise NavigationPolicyViolation("Navigation denied by policy.")
        return decision


class CandidateAction(DeepFrozenModel):
    action_type: ActionType
    label: str | None = None
    target_url: str | None = None


class ActionDecision(DeepFrozenModel):
    allowed: bool
    reason_code: str
    safe_message: str


class ActionGate:
    def evaluate(self, action: CandidateAction) -> ActionDecision:
        if action.action_type in _READONLY_ACTIONS:
            return ActionDecision(
                allowed=True,
                reason_code="readonly_navigation",
                safe_message="Action allowed.",
            )
        return ActionDecision(
            allowed=False,
            reason_code="denied",
            safe_message="Action denied by default policy.",
        )


def _deny(reason_code: str) -> NavigationDecision:
    return NavigationDecision(
        allowed=False,
        normalized_url=None,
        origin=None,
        reason_code=reason_code,
        safe_message="Navigation denied by policy.",
    )


def _normalize_origin(value: str) -> str:
    parsed = urlparse(value)
    if parsed.username or parsed.password:
        raise ValueError("origins must not contain userinfo")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("origins must not contain path, query, or fragment")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("origins must include scheme and host")
    return _origin_from_parts(parsed.scheme, parsed.hostname, parsed.port)


def _origin_from_parts(scheme: str, hostname: str, port: int | None) -> str:
    host = hostname.lower()
    default_port = (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    )
    if port is None or default_port:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _is_local_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}
