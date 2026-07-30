"""Strict versioned Application Manifest contract."""

from typing import Literal, Self, cast
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _split_http_url(value: str) -> SplitResult:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("origin scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("origin must not contain user information")
    if parsed.hostname is None:
        raise ValueError("origin must include a host")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("origin port is invalid") from error
    return parsed


def normalize_origin_from_url(value: str) -> str:
    """Return the canonical HTTP(S) origin for a URL."""

    parsed = _split_http_url(value)
    scheme = parsed.scheme.lower()
    host = cast(str, parsed.hostname).lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def normalize_manifest_origin(value: str) -> str:
    """Validate and canonicalize a declared exact origin."""

    parsed = _split_http_url(value)
    if parsed.path not in {"", "/"}:
        raise ValueError("origin must not contain a non-root path")
    if parsed.query:
        raise ValueError("origin must not contain a query")
    if parsed.fragment:
        raise ValueError("origin must not contain a fragment")
    return normalize_origin_from_url(value)


def normalize_origin_list(values: list[str]) -> list[str]:
    """Normalize an origin list while rejecting canonical duplicates."""

    normalized = [normalize_manifest_origin(value) for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError("origin lists must not contain normalized duplicates")
    return sorted(normalized)


class ApplicationManifest(BaseModel):
    """Versioned, non-sensitive application identity and origin boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    application_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=64)
    allowed_origins: list[str] = Field(min_length=1, max_length=100)
    authentication_origins: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("name", "environment")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("allowed_origins", "authentication_origins")
    @classmethod
    def normalize_origins(cls, value: list[str]) -> list[str]:
        return normalize_origin_list(value)

    @model_validator(mode="after")
    def validate_origin_roles(self) -> Self:
        overlap = set(self.allowed_origins) & set(self.authentication_origins)
        if overlap:
            raise ValueError(
                "target and authentication origins must not overlap"
            )
        return self

    def classify_url(
        self,
        value: str,
    ) -> Literal["target", "authentication", "outside"]:
        origin = normalize_origin_from_url(value)
        if origin in self.allowed_origins:
            return "target"
        if origin in self.authentication_origins:
            return "authentication"
        return "outside"

    @classmethod
    def to_schema(cls) -> dict[str, object]:
        return cast(dict[str, object], cls.model_json_schema())
