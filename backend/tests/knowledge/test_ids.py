"""Tests for canonical JSON, deterministic IDs, and safe JSON Pointers."""

import traceback
from hashlib import sha256

import pytest

from ai_ui_explorer.knowledge.ids import (
    CanonicalJsonError,
    JsonPointerError,
    UnsafeIdPrefixError,
    canonical_json,
    resolve_json_pointer,
    stable_id,
)


def test_canonical_json_sorts_keys_preserves_unicode_and_list_order() -> None:
    value = {
        "z": ["后", "先"],
        "中文": "保留",
        "a": {"b": 2, "a": 1},
    }

    assert canonical_json(value) == (
        '{"a":{"a":1,"b":2},"z":["后","先"],"中文":"保留"}'
    )


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        {"nested": [1, float("nan")]},
    ],
)
def test_canonical_json_rejects_non_finite_numbers(value: object) -> None:
    with pytest.raises(
        CanonicalJsonError,
        match=r"^Value cannot be encoded as canonical JSON\.$",
    ) as captured:
        canonical_json(value)

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_canonical_json_failure_does_not_echo_object_representation() -> None:
    class SensitiveObject:
        def __repr__(self) -> str:
            return "synthetic-secret-object"

    with pytest.raises(CanonicalJsonError) as captured:
        canonical_json(SensitiveObject())

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "synthetic-secret" not in _exception_surface(captured.value)


def test_stable_id_uses_canonical_parts_and_repeats_exactly() -> None:
    parts = ("元素", {"b": 2, "a": 1})
    canonical_material = '["元素",{"a":1,"b":2}]'
    expected_digest = sha256(canonical_material.encode("utf-8")).hexdigest()[:24]

    first = stable_id("element", *parts)
    second = stable_id("element", *parts)

    assert first == f"element-{expected_digest}"
    assert second == first


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "Element",
        "1element",
        "element_name",
        "element!",
        "a" * 33,
        "synthetic-secret\nprefix",
    ],
)
def test_stable_id_rejects_unsafe_prefix_without_echoing_it(prefix: str) -> None:
    with pytest.raises(
        UnsafeIdPrefixError,
        match=r"^Stable ID prefix is invalid\.$",
    ) as captured:
        stable_id(prefix, "part")

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    if prefix:
        assert prefix not in _exception_surface(captured.value)


def test_resolve_json_pointer_supports_root_objects_arrays_and_escapes() -> None:
    document = {
        "a/b": {"m~n": ["zero", {"value": "found"}]},
        "01": "object-key",
        "中文 键": "unicode-key",
    }

    assert resolve_json_pointer(document, "") is document
    assert (
        resolve_json_pointer(document, "/a~1b/m~0n/1/value")
        == "found"
    )
    assert resolve_json_pointer(document, "/01") == "object-key"
    assert resolve_json_pointer(document, "/中文 键") == "unicode-key"


@pytest.mark.parametrize(
    "pointer",
    [
        "missing-leading-slash",
        "/bad~escape",
        "/bad~",
        "/items/-",
        "/items/-1",
        "/items/01",
        "/items/+1",
        "/items/2",
        "/missing",
        "/scalar/next",
        "/token=synthetic-secret",
        "/control\ncharacter",
        "/" + ("a" * 5_000),
    ],
)
def test_resolve_json_pointer_rejects_invalid_or_unsafe_paths(
    pointer: str,
) -> None:
    document = {"items": ["zero", "one"], "scalar": 1}

    with pytest.raises(
        JsonPointerError,
        match=r"^JSON pointer is invalid\.$",
    ) as captured:
        resolve_json_pointer(document, pointer)

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert pointer not in _exception_surface(captured.value)
    assert "synthetic-secret" not in _exception_surface(captured.value)


def _exception_surface(error: BaseException) -> str:
    parts = [str(error), repr(error)]
    parts.extend(traceback.TracebackException.from_exception(error).format())
    return "\n".join(parts)
