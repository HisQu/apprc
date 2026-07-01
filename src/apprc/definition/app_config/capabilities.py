"""Capability state enums for AppRC application contracts."""

from __future__ import annotations

from enum import StrEnum


class CapabilityState(StrEnum):
    """Activation policy for an optional persistence capability."""

    DISABLED = "disabled"
    OPTIONAL = "optional"
    DEFAULT = "default"


class StorageLayerState(StrEnum):
    """Whether this integration needs an active storage root."""

    DISABLED = "disabled"
    REQUIRED = "required"


__all__ = [
    "CapabilityState",
    "StorageLayerState",
]
