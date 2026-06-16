"""Explicit storage selection states for the config editor."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# == Internal ================================
from apprc.config.storage.registry import (
    ArchivedStorageRecord,
    StorageRecord,
)


@dataclass(frozen=True, slots=True)
class NoStorageSelection:
    """State used when the editor has no storage target."""

    kind: Literal["none"] = "none"


@dataclass(frozen=True, slots=True)
class ActivePathStorageSelection:
    """Env-selected storage root that is not backed by a named row."""

    root: Path
    kind: Literal["active_path"] = "active_path"


@dataclass(frozen=True, slots=True)
class LiveStorageSelection:
    """Registry row whose storage root can be edited."""

    record: StorageRecord
    kind: Literal["live"] = "live"


@dataclass(frozen=True, slots=True)
class MissingStorageSelection:
    """Registry row whose storage root is missing or unusable."""

    record: StorageRecord
    kind: Literal["missing"] = "missing"


@dataclass(frozen=True, slots=True)
class ArchivedStorageSelection:
    """Archive convenience row selected from the storage list."""

    record: ArchivedStorageRecord
    kind: Literal["archived"] = "archived"


EditorStorageSelection = (
    NoStorageSelection
    | ActivePathStorageSelection
    | LiveStorageSelection
    | MissingStorageSelection
    | ArchivedStorageSelection
)
