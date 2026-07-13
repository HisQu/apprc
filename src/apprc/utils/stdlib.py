"""Small standard-library helpers shared by AppRC modules.

This module is intentionally boring. It contains generic helpers that are
useful across config, logging, and developer utilities but are not tied to a
specific AppRC domain. Domain-specific helpers should stay in their owning
package instead of growing this module into a miscellaneous toolbox.
"""

from __future__ import annotations

import time
from collections.abc import Hashable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from typing import TypeVar, cast, overload

DictKeyT = TypeVar("DictKeyT", bound=Hashable)
DefaultT = TypeVar("DefaultT")


def dataclass_slots_preserving_class_identity(
    cls: type[object],
    *,
    requested_slots: bool = True,
) -> bool:
    """Return a dataclass slots setting that keeps hook owners stable.

    ``dataclass(slots=True)`` creates a replacement class. On Python 3.12 and
    3.13 that breaks zero-argument ``super()`` in methods defined on the
    original class, including app-owned ``__post_init__`` hooks. Classes with a
    direct post-init hook therefore keep their identity.

    :param cls: Class that may be converted to a dataclass.
    :param requested_slots: Slots setting requested by the caller.
    :return: ``False`` for classes that define ``__post_init__`` directly,
        otherwise ``requested_slots``.
    """
    if "__post_init__" in cls.__dict__:
        return False
    return requested_slots


# =====================================================================
# === Dictionary / JSON conveniences
# =====================================================================


@overload
def deep_get(
    d: Mapping[DictKeyT, object],
    keypath: tuple[DictKeyT, ...],
) -> object | None: ...


@overload
def deep_get(
    d: Mapping[DictKeyT, object],
    keypath: tuple[DictKeyT, ...],
    default: DefaultT,
) -> object | DefaultT: ...


def deep_get(
    d: Mapping[DictKeyT, object],
    keypath: tuple[DictKeyT, ...],
    default: DefaultT | None = None,
) -> object | DefaultT | None:
    """Read a nested dictionary value without branching at every level.

    :param d: Mapping tree to inspect.
    :param keypath: Ordered dictionary keys from root to leaf.
    :param default: Value returned when any key is missing.
    :return: Leaf value or ``default``.
    """
    try:
        value: object = d
        for key in keypath:
            value = cast(Mapping[DictKeyT, object], value)[key]
        return value
    except (KeyError, TypeError):
        return default


def deep_set(
    d: MutableMapping[DictKeyT, object],
    keypath: tuple[DictKeyT, ...],
    value: object,
) -> None:
    """Write a nested dictionary value and create missing parent mappings.

    :param d: Mapping tree to mutate.
    :param keypath: Ordered dictionary keys from root to leaf.
    :param value: Value stored at the final key.
    """
    node = d
    for k in keypath[:-1]:
        node = cast(MutableMapping[DictKeyT, object], node.setdefault(k, {}))
    node[keypath[-1]] = value


def deep_right_merge(
    a: Mapping[DictKeyT, object],
    b: Mapping[DictKeyT, object],
) -> dict[DictKeyT, object]:
    """Merge two nested dictionaries and let ``b`` win conflicts.

    :param a: Base dictionary that should remain untouched.
    :param b: Overlay dictionary whose leaves replace matching leaves in ``a``.
    :return: New merged dictionary.
    """
    out = dict(a)
    for k, v in b.items():
        existing = out.get(k)
        if isinstance(v, Mapping) and isinstance(existing, Mapping):
            out[k] = deep_right_merge(
                cast(Mapping[DictKeyT, object], existing),
                cast(Mapping[DictKeyT, object], v),
            )
        else:
            out[k] = v
    return out


# =====================================================================
# === Custom Context Managers (with statement)
# =====================================================================


@contextmanager
def timer(name: str = "block") -> Iterator[None]:
    """Print elapsed wall time when a manual diagnostic block exits.

    The helper is intentionally simple and stdout-based. Production code should
    use stdlib ``logging`` or a host-owned logging package; this context
    manager is for quick local probes where logging setup would be noise.

    :param name: Label printed with the elapsed duration.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(f"{name} finished in {elapsed:0.4f}s")
