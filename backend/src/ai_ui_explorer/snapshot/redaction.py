"""Redact sensitive values before they enter the snapshot model."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import islice
from re import _parser  # type: ignore[attr-defined]
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True, slots=True)
class CustomRedactionRule:
    """Trusted administrator configuration for one structural regex rule."""

    name: str
    category: str
    pattern: str


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
    "access_token": "TOKEN",
    "refresh_token": "TOKEN",
    "id_token": "TOKEN",
    "cookie": "COOKIE",
    "authorization": "TOKEN",
    "api_key": "API_KEY",
}
_TEXT_SENSITIVE_KEYS = "|".join(
    re.escape(key) for key in _SENSITIVE_KEY_CATEGORIES if key != "authorization"
)
_SENSITIVE_KEY_NAME_PATTERN = rf"(?:{_TEXT_SENSITIVE_KEYS}|[A-Za-z][A-Za-z0-9-]*_token)"
_QUOTED_VALUE_PATTERN = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')'''
_AUTHORIZATION_PATTERN = re.compile(
    r"(?P<key_quote>[\"'])?(?P<key>\bauthorization\b)(?(key_quote)(?P=key_quote))"
    rf"(?P<separator>\s*:\s*)(?:{_QUOTED_VALUE_PATTERN}|(?:bearer\s+)?[^\s,;,&}}\]]+)",
    re.IGNORECASE,
)
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    rf"(?P<key_quote>[\"'])?(?P<key>{_SENSITIVE_KEY_NAME_PATTERN})"
    rf"(?(key_quote)(?P=key_quote))(?P<separator>\s*[:=]\s*)"
    rf"(?:{_QUOTED_VALUE_PATTERN}|[^\s,;,&}}\]]+)",
    re.IGNORECASE,
)
_BEARER_TOKEN_PATTERN = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_CHINESE_ID_PATTERN = re.compile(r"\b\d{17}[\dXx]\b")
_BANK_CARD_PATTERN = re.compile(r"\b\d{16,19}\b")
_MAINLAND_MOBILE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CONTENT_BEARING_SCHEMES = frozenset({"data", "javascript", "vbscript"})
_MAX_CUSTOM_RULES = 32
_MAX_CUSTOM_PATTERN_LENGTH = 512
_SAFE_RULE_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
_SAFE_CATEGORY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_BUILT_IN_RULE_NAMES = frozenset(
    {
        *_SENSITIVE_KEY_CATEGORIES.keys(),
        "authorization",
        "sensitive-key",
        "bearer-token",
        "chinese-id",
        "bank-card",
        "mainland-mobile",
        "email",
        "url",
        "url-userinfo",
    }
)
_BUILT_IN_CATEGORIES = frozenset(
    {
        *_SENSITIVE_KEY_CATEGORIES.values(),
        "CHINESE_ID",
        "BANK_CARD",
        "MOBILE",
        "EMAIL",
        "URL",
        "URL_USERINFO",
    }
)


@dataclass(frozen=True, slots=True)
class _CompiledCustomRule:
    name: str
    category: str
    pattern: re.Pattern[str]


class Redactor:
    """Apply deterministic, category-aware redaction rules."""

    def __init__(
        self,
        *,
        custom_rules: Iterable[CustomRedactionRule] = (),
    ) -> None:
        supplied_rules = tuple(islice(custom_rules, _MAX_CUSTOM_RULES + 1))
        if len(supplied_rules) > _MAX_CUSTOM_RULES:
            raise ValueError(f"custom redaction rules are limited to {_MAX_CUSTOM_RULES}")

        compiled_rules: list[_CompiledCustomRule] = []
        custom_names: set[str] = set()
        for rule in supplied_rules:
            if not isinstance(rule, CustomRedactionRule):
                raise ValueError("custom redaction rules must use CustomRedactionRule")
            if not all(
                isinstance(value, str)
                for value in (rule.name, rule.category, rule.pattern)
            ):
                raise ValueError("custom rule name, category, and pattern must be strings")
            normalized_name = rule.name.lower()
            if _SAFE_RULE_NAME_PATTERN.fullmatch(rule.name) is None:
                raise ValueError("custom rule name must be a non-empty safe identifier")
            if _SAFE_CATEGORY_PATTERN.fullmatch(rule.category) is None:
                raise ValueError("custom rule category must be a non-empty safe identifier")
            if normalized_name in _BUILT_IN_RULE_NAMES:
                raise ValueError("custom rule name cannot override a built-in rule")
            if rule.category in _BUILT_IN_CATEGORIES:
                raise ValueError("custom rule category cannot override a built-in category")
            if normalized_name in custom_names:
                raise ValueError("custom rule names must be unique")
            if not rule.pattern:
                raise ValueError("custom rule pattern must not be empty")
            if len(rule.pattern) > _MAX_CUSTOM_PATTERN_LENGTH:
                raise ValueError(
                    "custom rule pattern exceeds the configured length limit"
                )
            try:
                compiled_pattern = re.compile(rule.pattern)
            except re.error as exc:
                raise ValueError("custom rule pattern is not a valid regex") from exc
            minimum_width, _ = _parser.parse(rule.pattern, 0).getwidth()
            if minimum_width == 0:
                raise ValueError(
                    "custom rule pattern must consume at least one character"
                )
            custom_names.add(normalized_name)
            compiled_rules.append(
                _CompiledCustomRule(
                    name=rule.name,
                    category=rule.category,
                    pattern=compiled_pattern,
                )
            )

        self._custom_rules = tuple(
            sorted(
                compiled_rules,
                key=lambda rule: (rule.name.lower(), rule.category, rule.pattern.pattern),
            )
        )

    def redact_text(self, value: str) -> RedactionResult:
        categories: set[str] = set()
        count = 0

        def replace_authorization(match: re.Match[str]) -> str:
            nonlocal count
            category = "TOKEN"
            count += 1
            categories.add(category)
            return _redacted_key_value(match, category)

        def replace_sensitive_key(match: re.Match[str]) -> str:
            nonlocal count
            category = _sensitive_category(match.group("key"))
            assert category is not None
            count += 1
            categories.add(category)
            return _redacted_key_value(match, category)

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

        for rule in self._custom_rules:
            redacted, replacements = rule.pattern.subn(
                _marker(rule.category),
                redacted,
            )
            if replacements:
                count += replacements
                categories.add(rule.category)

        return RedactionResult(redacted, count, frozenset(categories))

    def redact_mapping(self, values: Mapping[str, str]) -> tuple[dict[str, str], RedactionSummary]:
        redacted_values: dict[str, str] = {}
        categories: set[str] = set()
        count = 0
        for key, value in values.items():
            category = _sensitive_category(key)
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
            if parts.scheme.lower() in _CONTENT_BEARING_SCHEMES:
                return RedactionResult(_marker("URL"), 1, frozenset({"URL"}))
            netloc = parts.hostname or ""
            if ":" in netloc:
                netloc = f"[{netloc}]"
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
            category = _sensitive_category(key)
            if category is not None:
                query_pairs.append((key, _marker(category)))
                count += 1
                categories.add(category)
                continue
            result = self.redact_text(query_value)
            query_pairs.append((key, result.value))
            count += result.count
            categories.update(result.categories)

        for key, fragment_value in parse_qsl(parts.fragment, keep_blank_values=True):
            category = _sensitive_category(key)
            if category is not None:
                count += 1
                categories.add(category)
                continue
            result = self.redact_text(fragment_value)
            count += result.count
            categories.update(result.categories)

        redacted_url = urlunsplit(
            (parts.scheme, netloc, parts.path, urlencode(query_pairs), "")
        )
        return RedactionResult(redacted_url, count, frozenset(categories))

    def redact_error(self, value: str) -> RedactionResult:
        return self.redact_text(value)


def _marker(category: str) -> str:
    return f"[REDACTED:{category}]"


def _sensitive_category(key: str) -> str | None:
    normalized_key = key.lower()
    return _SENSITIVE_KEY_CATEGORIES.get(normalized_key) or (
        "TOKEN" if normalized_key.endswith("_token") else None
    )


def _redacted_key_value(match: re.Match[str], category: str) -> str:
    key_quote = match.group("key_quote") or ""
    key = match.group("key")
    separator = match.group("separator")
    return f"{key_quote}{key}{key_quote}{separator}{_marker(category)}"
