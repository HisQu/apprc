"""Storage requirements declared by an AppRC application."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Storage:
    """Declare that an application needs one active storage directory.

    :param selector_env_key: Environment key that selects the active storage. AppRC
        derives ``<APP>_STORAGE`` when omitted.
    """

    selector_env_key: str | None = None


__all__ = ["Storage"]
