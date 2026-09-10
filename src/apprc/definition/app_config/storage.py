"""Storage requirements declared by an AppRC application."""

from __future__ import annotations

# == Standard Library ===========================================
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Storage:
    """Declare that an application needs one active storage directory.

    :param selector_env_key: Environment key that selects the active storage. AppRC
        derives ``<APP>_STORAGE`` when omitted.
    :param required: Whether runtime bootstrap requires an active storage by
        default. Individual runtime boundaries may override this policy.
    """

    selector_env_key: str | None = None
    required: bool = True


__all__ = ["Storage"]
