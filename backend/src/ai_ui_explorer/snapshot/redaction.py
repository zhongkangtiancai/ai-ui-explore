"""Redact sensitive values before they enter the snapshot model."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class RedactionResult:
    value: str
    count: int
    categories: frozenset[str]


@dataclass(frozen=True)
class RedactionSummary:
    count: int
    categories: frozenset[str]


_SENSITIVE_KEY_CATEGORIES = {
    "password": "PASSWORD",
    "passwd": "PASSWORD",
    "secret": "SECRET",
    "token": "TOKEN",
    "cookie": "COOKIE",
    "authorization": "TOKEN",
    "api_key": "API_KEY",
}
_SENSITIVE_KEYS = "|".join(_SENSITIVE_KEY_CATEGORIES)
_AUTHORIZATION_PATTERN = re.compile(
    r"(?P<key>\bauthorization\b)(?P<separator>\s*:\s*)(?:bearer\s+)?(?P<value>[^\s,;,&}\]]+)",
    re.IGNORECASE,
)
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    rf"(?P<key>\b(?:{_SENSITIVE_KEYS})\b)(?P<separator>\s*[:=]\s*)(?P<value>[^\s,;,&}}\]]+)",
    re.IGNORECASE,
)
_BEARER_TOKEN_PATTERN = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_CHINESE_ID_PATTERN = re.compile(r"\b\d{17}[\dXx]\b")
_BANK_CARD_PATTERN = re.compile(r"\b\d{16,19}\b")
_MAINLAND_MOBILE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class Redactor:
    """Apply deterministic, category-aware redaction rules."""

    def redact_text(self, value: str) -> RedactionResult:
        categories: set[str] = set()
        count = 0

        def replace_authorization(match: re.Match[str]) -> str:
            nonlocal count
            category = "TOKEN"
            count += 1
            categories.add(category)
            return f"{match.group('key')}{match.group('separator')}{_marker(category)}"

        def replace_sensitive_key(match: re.Match[str]) -> str:
            nonlocal count
            category = _SENSITIVE_KEY_CATEGORIES[match.group("key").lower()]
            count += 1
            categories.add(category)
            return f"{match.group('key')}{match.group('separator')}{_marker(category)}"

        redacted = _AUTHORIZATION_PATTERN.sub(replace_authorization, value)
        redacted = _SENSITIVE_KEY_VALUE_PATTERN.sub(replace_sensitive_key, redacted)
        for pattern, category in (
            (_BEARER_TOKEN_PATTERN, "TOKEN"),
            (_CHINESE_ID_PATTERN, "CHINESE_ID"),
            (_BANK_CARD_PATTERN, "BANK_CARD"),
            (_MAINLAND_MOBILE_PATTERN, "MOBILE"),
            (_EMAIL_PATTERN, "EMAIL"),
        ):
            redacted, replacements = pattern.subn(_marker(category), redacted)
            if replacements:
                count += replacements
                categories.add(category)

        return RedactionResult(redacted, count, frozenset(categories))

    def redact_mapping(self, values: Mapping[str, str]) -> tuple[dict[str, str], RedactionSummary]:
        redacted_values: dict[str, str] = {}
        categories: set[str] = set()
        count = 0
        for key, value in values.items():
            category = _SENSITIVE_KEY_CATEGORIES.get(key.lower())
            if category is not None:
                redacted_values[key] = _marker(category)
                count += 1
                categories.add(category)
                continue
            result = self.redact_text(value)
            redacted_values[key] = result.value
            count += result.count
            categories.update(result.categories)
        return redacted_values, RedactionSummary(count, frozenset(categories))

    def redact_url(self, value: str) -> RedactionResult:
        try:
            parts = urlsplit(value)
            netloc = parts.hostname or ""
            if parts.port is not None:
                netloc = f"{netloc}:{parts.port}"
        except ValueError:
            return RedactionResult(_marker("URL"), 1, frozenset({"URL"}))

        count = 0
        categories: set[str] = set()
        if parts.username is not None or parts.password is not None:
            count += 1
            categories.add("URL_USERINFO")

        query_pairs: list[tuple[str, str]] = []
        for key, query_value in parse_qsl(parts.query, keep_blank_values=True):
            category = _SENSITIVE_KEY_CATEGORIES.get(key.lower())
            if category is not None:
                query_pairs.append((key, _marker(category)))
                count += 1
                categories.add(category)
                continue
            result = self.redact_text(query_value)
            query_pairs.append((key, result.value))
            count += result.count
            categories.update(result.categories)

        redacted_url = urlunsplit(
            (parts.scheme, netloc, parts.path, urlencode(query_pairs), parts.fragment)
        )
        return RedactionResult(redacted_url, count, frozenset(categories))

    def redact_error(self, value: str) -> RedactionResult:
        return self.redact_text(value)


def _marker(category: str) -> str:
    return f"[REDACTED:{category}]"
