"""Fixed application-owned operations for logical resource maintenance."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from apprc.definition.paths import ResourceKind


@dataclass(frozen=True, slots=True)
class RemovalPlan:
    """An exact, revision-bound inventory; never recursive deletion authority."""

    category: ResourceKind
    root: Path
    targets: tuple[Path, ...]
    revision: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RemovalResult:
    """Report actual removals and explicitly retained payloads."""

    removed: tuple[Path, ...]
    skipped: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RemovalOperation:
    """Pair planning with apply-time application locking and freshness checks."""

    plan: Callable[[Path], RemovalPlan]
    apply: Callable[[RemovalPlan], RemovalResult]


@dataclass(frozen=True, slots=True)
class AppDataOperations:
    """Durable data operations explicitly supported by the application.

    Restore must refuse existing payload under application coordination before
    writing. Known retained lock metadata is not payload.
    """

    info: Callable[[Path], Mapping[str, object]] | None = None
    backup: Callable[[Path, Path], Path] | None = None
    restore: Callable[[Path, Path], None] | None = None
    purge: RemovalOperation | None = None


@dataclass(frozen=True, slots=True)
class CacheOperations:
    """Disposable cache operations explicitly supported by the application."""

    info: Callable[[Path], Mapping[str, object]] | None = None
    prune: RemovalOperation | None = None
    clear: RemovalOperation | None = None
    purge: RemovalOperation | None = None


@dataclass(frozen=True, slots=True)
class StateOperations:
    """Operational state operations, including subordinate log roots."""

    info: Callable[[Path], Mapping[str, object]] | None = None
    prune: RemovalOperation | None = None
    reset: RemovalOperation | None = None
    purge: RemovalOperation | None = None


@dataclass(frozen=True, slots=True)
class MaintenanceHandlers:
    """Optional semantic operations, independent of path declarations."""

    appdata: AppDataOperations | None = None
    cache: CacheOperations | None = None
    state: StateOperations | None = None
