"""Small helpers for PEP 562 package facades. This speeds up import time a lot

Once Python 3.15 hits, replace all this logic with `lazy import`
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from importlib import import_module


type LazyGetattr = Callable[[str], object]
type LazyDir = Callable[[], list[str]]


def build_lazy_facade(
    *,
    public_module: str,
    all_exports: Sequence[str],
    module_exports: Mapping[str, str],
    symbol_exports: Mapping[str, str],
) -> tuple[list[str], LazyGetattr, LazyDir]:
    """Build module-level hooks for one lazy public facade.

    The returned ``__getattr__`` resolves modules and symbols only when a caller
    first touches them. Resolved values are stored on the public module, not on
    the private ``_facade`` module, so repeated access is the same cheap global
    lookup that an eager facade would provide.

    :param public_module: Public module name that owns the lazy attributes.
    :param all_exports: Stable ``__all__`` values for the facade.
    :param module_exports: Exported submodule names to import paths.
    :param symbol_exports: Exported symbol names to the module that defines them.
    :return: ``(__all__, __getattr__, __dir__)`` for re-export by ``__init__``.
    """
    all_names = list(all_exports)
    module_map = dict(module_exports)
    symbol_map = dict(symbol_exports)
    known_names = frozenset((*module_map, *symbol_map))

    def __getattr__(name: str) -> object:
        namespace = sys.modules[public_module].__dict__
        if name in module_map:
            value = import_module(module_map[name])
        else:
            try:
                module_name = symbol_map[name]
            except KeyError as exc:
                raise AttributeError(
                    f"module {public_module!r} has no attribute {name!r}"
                ) from exc
            module = import_module(module_name)
            value = getattr(module, name)
        namespace[name] = value
        return value

    def __dir__() -> list[str]:
        namespace = sys.modules[public_module].__dict__
        return sorted(set(namespace) | known_names | set(all_names))

    return all_names, __getattr__, __dir__
