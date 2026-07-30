"""Canonical JSON, deterministic IDs, and a safe RFC 6901 subset."""

import json
import re
from hashlib import sha256

_SAFE_ID_PREFIX = re.compile(r"[a-z][a-z0-9-]{0,31}")
_MAX_JSON_POINTER_CHARS = 4_096
_MAX_JSON_POINTER_TOKENS = 256
_ARRAY_INDEX = re.compile(r"(?:0|[1-9][0-9]*)")


class CanonicalJsonError(ValueError):
    """A value cannot be represented by the supported canonical JSON form."""


class UnsafeIdPrefixError(ValueError):
    """A stable ID prefix is outside the approved identifier boundary."""


class JsonPointerError(ValueError):
    """A JSON Pointer is unsafe, malformed, or cannot be resolved."""


def canonical_json(value: object) -> str:
    """Return compact, sorted, UTF-8-safe JSON with finite numbers only."""

    serialized = _try_canonical_json(value)
    if serialized is None:
        del value
        raise CanonicalJsonError("Value cannot be encoded as canonical JSON.")
    return serialized


def stable_id(prefix: str, *parts: object) -> str:
    """Build a readable deterministic ID from canonical JSON parts."""

    if (
        not isinstance(prefix, str)
        or _SAFE_ID_PREFIX.fullmatch(prefix) is None
    ):
        del prefix, parts
        raise UnsafeIdPrefixError("Stable ID prefix is invalid.")

    failed = False
    material = ""
    try:
        material = canonical_json(list(parts))
    except CanonicalJsonError:
        failed = True
    if failed:
        del prefix, parts, material
        raise CanonicalJsonError("Value cannot be encoded as canonical JSON.")
    digest = sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def resolve_json_pointer(document: object, pointer: str) -> object:
    """Resolve a bounded RFC 6901 subset over JSON object and array values."""

    resolved, value = _try_resolve_json_pointer(document, pointer)
    if not resolved:
        del document, pointer, value
        raise JsonPointerError("JSON pointer is invalid.")
    return value


def _try_canonical_json(value: object) -> str | None:
    try:
        serialized = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        serialized.encode("utf-8")
    except (OverflowError, TypeError, UnicodeError, ValueError):
        return None
    return serialized


def _try_resolve_json_pointer(
    document: object,
    pointer: object,
) -> tuple[bool, object]:
    tokens = _decode_json_pointer(pointer)
    if tokens is None:
        return False, None
    if not tokens:
        return True, document

    current = document
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
            continue
        if isinstance(current, list):
            if _ARRAY_INDEX.fullmatch(token) is None:
                return False, None
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
            continue
        return False, None
    return True, current


def _decode_json_pointer(pointer: object) -> tuple[str, ...] | None:
    if (
        not isinstance(pointer, str)
        or len(pointer) > _MAX_JSON_POINTER_CHARS
        or (pointer and not pointer.startswith("/"))
        or pointer.count("/") > _MAX_JSON_POINTER_TOKENS
    ):
        return None
    if pointer == "":
        return ()

    decoded_tokens: list[str] = []
    for encoded_token in pointer[1:].split("/"):
        decoded_characters: list[str] = []
        index = 0
        while index < len(encoded_token):
            character = encoded_token[index]
            if character != "~":
                if not character.isprintable():
                    return None
                decoded_characters.append(character)
                index += 1
                continue
            if index + 1 >= len(encoded_token):
                return None
            escape = encoded_token[index + 1]
            if escape == "0":
                decoded_characters.append("~")
            elif escape == "1":
                decoded_characters.append("/")
            else:
                return None
            index += 2
        decoded_tokens.append("".join(decoded_characters))
    return tuple(decoded_tokens)
