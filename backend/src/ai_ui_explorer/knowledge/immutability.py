"""Runtime-deep immutable containers for validated knowledge models."""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import Any, NoReturn, Self, overload

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    field_serializer,
    model_validator,
)


def _immutable(*args: object, **kwargs: object) -> NoReturn:
    raise TypeError("validated model containers are immutable")


class FrozenSequence[T](Sequence[T]):
    """A tuple-backed Sequence that cannot satisfy list mutator descriptors."""

    __slots__ = ("_items",)
    _items: tuple[T, ...]

    def __init__(self, values: Iterable[T]) -> None:
        object.__setattr__(self, "_items", tuple(values))

    def __setattr__(self, name: str, value: object) -> NoReturn:
        _immutable(name, value)

    def __delattr__(self, name: str) -> NoReturn:
        _immutable(name)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[T]: ...

    def __getitem__(self, index: int | slice) -> T | Sequence[T]:
        return self._items[index]

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Sequence):
            return False
        return tuple(self) == tuple(other)

    def __repr__(self) -> str:
        return repr(list(self._items))

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        return self


class FrozenMapping[K, V](Mapping[K, V]):
    """A proxy-backed Mapping that cannot satisfy dict mutator descriptors."""

    __slots__ = ("_items",)
    _items: Mapping[K, V]

    def __init__(self, values: Iterable[tuple[K, V]]) -> None:
        object.__setattr__(
            self,
            "_items",
            MappingProxyType(dict(values)),
        )

    def __setattr__(self, name: str, value: object) -> NoReturn:
        _immutable(name, value)

    def __delattr__(self, name: str) -> NoReturn:
        _immutable(name)

    def __getitem__(self, key: K) -> V:
        return self._items[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False
        return dict(self.items()) == dict(other.items())

    def __repr__(self) -> str:
        return repr(dict(self._items))

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        return self

for _method_name in (
    "__delitem__",
    "__iadd__",
    "__imul__",
    "__setitem__",
    "append",
    "clear",
    "extend",
    "insert",
    "pop",
    "remove",
    "reverse",
    "sort",
):
    setattr(FrozenSequence, _method_name, _immutable)

for _method_name in (
    "__delitem__",
    "__ior__",
    "__setitem__",
    "clear",
    "pop",
    "popitem",
    "setdefault",
    "update",
):
    setattr(FrozenMapping, _method_name, _immutable)


def _freeze(value: object) -> object:
    if isinstance(value, FrozenSequence | FrozenMapping):
        return value
    if isinstance(value, list):
        return FrozenSequence(_freeze(item) for item in value)
    if isinstance(value, dict):
        return FrozenMapping(
            (key, _freeze(item)) for key, item in value.items()
        )
    return value


def _thaw(value: object) -> object:
    if isinstance(value, FrozenSequence):
        return [_thaw(item) for item in value]
    if isinstance(value, FrozenMapping):
        return {key: _thaw(item) for key, item in value.items()}
    return value


class DeepFrozenModel(BaseModel):
    """Pydantic base that preserves list/dict schemas but freezes runtime values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    @model_validator(mode="after")
    def freeze_containers(self) -> Self:
        for field_name in type(self).model_fields:
            object.__setattr__(
                self,
                field_name,
                _freeze(getattr(self, field_name)),
            )
        return self

    @field_serializer("*", mode="wrap")
    def serialize_containers(
        self,
        value: object,
        handler: SerializerFunctionWrapHandler,
    ) -> object:
        return handler(_thaw(value))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python")
        values.update(update)
        return type(self).model_validate(values)
