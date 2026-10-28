"""External workspace selection declared by an AppRC application."""

from __future__ import annotations

# -- Standard library
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Workspaces:
    """Enable direct workspace selection and optionally a named registry.

    :param selector_env_key: Override the derived ``<PREFIX>_WORKSPACE`` key.
    :param registry: Whether names and a persisted selection are supported.
    """

    selector_env_key: str | None = None
    registry: bool = True


__all__ = ["Workspaces"]
