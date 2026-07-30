"""Strict versioned Application Manifest contract."""

from ipaddress import IPv4Address, IPv6Address
from typing import Literal, Self, cast
from urllib.parse import SplitResult, urlsplit

import idna
from pydantic import Field, field_validator, model_validator

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel

_JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _split_http_url(value: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise ValueError("URL is invalid") from None
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


def _parse_ipv4_number(value: str) -> int | None:
    base = 10
    digits = value
    if value.lower().startswith("0x"):
        base = 16
        digits = value[2:]
    elif len(value) >= 2 and value.startswith("0"):
        base = 8
        digits = value[1:]
    if not digits:
        return 0
    valid_digits = {
        8: "01234567",
        10: "0123456789",
        16: "0123456789abcdefABCDEF",
    }[base]
    if any(character not in valid_digits for character in digits):
        return None
    return int(digits, base)


def _normalize_whatwg_ipv4(host: str) -> str | None:
    parts = host.split(".")
    if parts[-1] == "":
        parts.pop()
    if not parts or _parse_ipv4_number(parts[-1]) is None:
        return None
    if len(parts) > 4:
        raise ValueError("IPv4 host is invalid")
    numbers = [_parse_ipv4_number(part) for part in parts]
    if any(number is None for number in numbers):
        raise ValueError("IPv4 host is invalid")
    concrete_numbers = cast(list[int], numbers)
    if any(number > 255 for number in concrete_numbers[:-1]):
        raise ValueError("IPv4 host is invalid")
    last_limit = 256 ** (5 - len(concrete_numbers))
    if concrete_numbers[-1] >= last_limit:
        raise ValueError("IPv4 host is invalid")
    address = concrete_numbers[-1]
    for index, number in enumerate(concrete_numbers[:-1]):
        address += number * (256 ** (3 - index))
    return str(IPv4Address(address))


def _normalize_host(host: str) -> str:
    if ":" in host:
        if "%" in host:
            raise ValueError("IPv6 host is invalid")
        try:
            return f"[{IPv6Address(host).compressed}]"
        except ValueError:
            raise ValueError("IPv6 host is invalid") from None
    try:
        ascii_host = idna.encode(
            host,
            uts46=True,
            std3_rules=True,
        ).decode("ascii").lower()
    except idna.IDNAError:
        raise ValueError("host is invalid") from None
    ipv4_host = _normalize_whatwg_ipv4(ascii_host)
    return ipv4_host if ipv4_host is not None else ascii_host


def _normalize_http_origin(value: str, *, exact_origin: bool) -> str:
    parsed = _split_http_url(value)
    if exact_origin:
        if "?" in value:
            raise ValueError("origin must not contain a query delimiter")
        if "#" in value:
            raise ValueError("origin must not contain a fragment delimiter")
        if parsed.path not in {"", "/"}:
            raise ValueError("origin must not contain a non-root path")

    scheme = parsed.scheme.lower()
    host = _normalize_host(cast(str, parsed.hostname))
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def normalize_origin_from_url(value: str) -> str:
    """Return the browser-equivalent HTTP(S) origin for a URL."""

    return _normalize_http_origin(value, exact_origin=False)


def normalize_manifest_origin(value: str) -> str:
    """Validate and canonicalize a declared exact origin."""

    return _normalize_http_origin(value, exact_origin=True)


def normalize_origin_list(values: list[str]) -> list[str]:
    """Normalize an origin list while rejecting canonical duplicates."""

    normalized = [normalize_manifest_origin(value) for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError("origin lists must not contain normalized duplicates")
    return sorted(normalized)


class ApplicationManifest(DeepFrozenModel):
    """Versioned, non-sensitive application identity and origin boundary."""

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
        schema = cast(dict[str, object], cls.model_json_schema())
        schema["$schema"] = _JSON_SCHEMA_DRAFT
        return schema
