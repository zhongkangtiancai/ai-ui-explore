"""Runtime-deep immutable containers for validated knowledge models."""

from collections.abc import Mapping
from typing import Any, NoReturn, Self

from pydantic import BaseModel, ConfigDict, model_validator


class FrozenList[T](list[T]):
    """A list-compatible value whose mutating operations always fail."""

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        return self


class FrozenDict[K, V](dict[K, V]):
    """A dict-compatible value whose mutating operations always fail."""

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        return self


def _immutable(*args: object, **kwargs: object) -> NoReturn:
    raise TypeError("validated model containers are immutable")


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
    setattr(FrozenList, _method_name, _immutable)

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
    setattr(FrozenDict, _method_name, _immutable)


def _freeze(value: object) -> object:
    if isinstance(value, FrozenList | FrozenDict):
        return value
    if isinstance(value, list):
        return FrozenList(_freeze(item) for item in value)
    if isinstance(value, dict):
        return FrozenDict(
            (key, _freeze(item)) for key, item in value.items()
        )
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
