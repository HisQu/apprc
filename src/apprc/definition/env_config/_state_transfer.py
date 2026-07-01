"""Lifecycle-neutral state transfer helpers for runtime configs."""

from __future__ import annotations

# == Standard Library ========================
from copy import deepcopy as _deepcopy
from dataclasses import dataclass
from functools import cache
from types import ModuleType
from typing import Any, Generic, TypeVar, cast

ConfigT = TypeVar("ConfigT")

_DEEPCOPY_LOG_DEPTH_KEY = (
    "apprc.definition.env_config.base",
    "deepcopy_log_depth",
)


@dataclass(frozen=True, slots=True)
class DeepCopyResult(Generic[ConfigT]):
    """Deep-copy result plus the public logging signal.

    :param clone: Deep-copied runtime object.
    :param should_log: Whether this call copied the top-level config object.
    """

    clone: ConfigT
    should_log: bool


@cache
def slot_names(obj_type: type) -> frozenset[str]:
    """Collect slot names from ``obj_type`` and all bases in MRO order.

    :param obj_type: Class to inspect for ``__slots__``.
    :return: Slot names declared across the class hierarchy.
    """
    names: set[str] = set()
    for cls in obj_type.__mro__:
        slots = cls.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            names.add(slots)
            continue
        for name in slots:
            names.add(name)
    return frozenset(names)


def has_instance_attr(instance: Any, key: str) -> bool:
    """Return whether ``key`` is already assigned on ``instance``.

    Regular instances are checked through ``__dict__``. Slotted instances are
    checked by slot membership and then by probing the actual assigned value.

    :param instance: Runtime object to inspect.
    :param key: Attribute name to locate.
    :return: ``True`` when the attribute already has instance state.
    """
    d = getattr(instance, "__dict__", None)
    if isinstance(d, dict):
        return key in d
    if key in slot_names(type(instance)):
        try:
            object.__getattribute__(instance, key)
        except AttributeError:
            return False
        return True
    return False


def assigned_state_items(instance: Any) -> tuple[tuple[str, Any], ...]:
    """Return assigned instance state for lifecycle-neutral copying.

    :param instance: Runtime object whose state should be transferred.
    :return: Assigned instance attributes as ``(name, value)`` pairs.
    """
    items: list[tuple[str, Any]] = []
    seen: set[str] = set()
    d = getattr(instance, "__dict__", None)
    if isinstance(d, dict):
        for key, value in d.items():
            items.append((key, value))
            seen.add(key)
    for slot_name in slot_names(type(instance)):
        if slot_name in {"__dict__", "__weakref__"} or slot_name in seen:
            continue
        try:
            value = object.__getattribute__(instance, slot_name)
        except AttributeError:
            continue
        items.append((slot_name, value))
    return tuple(items)


def deepcopy_state_value(value: Any, memo: dict[Any, Any]) -> Any:
    """Deep-copy one state value while preserving process singletons.

    :param value: State value to copy.
    :param memo: Active ``copy.deepcopy`` memo.
    :return: Deep-copied value or identity-preserved singleton.
    """
    if isinstance(value, ModuleType):
        return value
    return _deepcopy(value, memo)


def shallow_clone(instance: ConfigT) -> ConfigT:
    """Return a shallow clone without constructor or lifecycle side effects.

    :param instance: Runtime config object to clone.
    :return: Clone with the same assigned state as ``instance``.
    """
    clone = cast(ConfigT, object.__new__(type(instance)))
    for key, value in assigned_state_items(instance):
        object.__setattr__(clone, key, value)
    return clone


def isolated_deep_clone(
    instance: ConfigT,
    memo: dict[Any, Any] | None = None,
) -> ConfigT:
    """Return an isolated clone without constructor or logging side effects.

    :param instance: Runtime config object to clone.
    :param memo: Optional active ``copy.deepcopy`` memo.
    :return: Clone with deep-copied assigned state.
    """
    result = deepcopy_with_log_signal(instance, {} if memo is None else memo)
    return result.clone


def deepcopy_with_log_signal(
    instance: ConfigT,
    memo: dict[Any, Any],
) -> DeepCopyResult[ConfigT]:
    """Return a deep clone plus whether the caller should log the copy.

    :param instance: Runtime config object to clone.
    :param memo: Active ``copy.deepcopy`` memo.
    :return: Deep-copy result with the top-level logging signal.
    """
    obj_id = id(instance)
    if obj_id in memo:
        return DeepCopyResult(cast(ConfigT, memo[obj_id]), False)

    depth = int(memo.get(_DEEPCOPY_LOG_DEPTH_KEY, 0))
    log_this_copy = depth == 0
    memo[_DEEPCOPY_LOG_DEPTH_KEY] = depth + 1
    clone = cast(ConfigT, object.__new__(type(instance)))
    memo[obj_id] = clone
    try:
        for key, value in assigned_state_items(instance):
            object.__setattr__(
                clone,
                key,
                deepcopy_state_value(value, memo),
            )
    finally:
        next_depth = int(memo.get(_DEEPCOPY_LOG_DEPTH_KEY, 1)) - 1
        if next_depth > 0:
            memo[_DEEPCOPY_LOG_DEPTH_KEY] = next_depth
        else:
            memo.pop(_DEEPCOPY_LOG_DEPTH_KEY, None)
    return DeepCopyResult(clone, log_this_copy)
