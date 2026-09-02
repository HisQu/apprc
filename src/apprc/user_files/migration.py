"""Explicit migration from legacy AppRC-managed filenames."""

from __future__ import annotations

# == Standard Library ============================================
import os
from dataclasses import dataclass
from pathlib import Path

# == Internal ====================================================
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.user_files.managed_files import ManagedFileResolution


@dataclass(frozen=True, slots=True)
class FileMigration:
    """One same-directory legacy filename move.

    :param source: Existing legacy file.
    :param destination: Preferred current filename.
    :param label: Human-readable resource name.
    """

    source: Path
    destination: Path
    label: str


@dataclass(frozen=True, slots=True)
class MigrationConflict:
    """Files that prevent an automatic move.

    :param preferred: Current destination or selected legacy source.
    :param conflicting: Other existing file that AppRC will not merge.
    :param label: Human-readable resource name.
    """

    preferred: Path
    conflicting: Path
    label: str


@dataclass(frozen=True, slots=True)
class ConfigMigrationPlan:
    """Preflight result for one application migration.

    :param moves: Safe filename moves that may be applied.
    :param conflicts: Ambiguous files that require manual resolution.
    """

    moves: tuple[FileMigration, ...]
    conflicts: tuple[MigrationConflict, ...]


@dataclass(frozen=True, slots=True)
class ConfigMigrationResult:
    """Outcome of applying a migration plan.

    :param moved: Moves completed before return.
    """

    moved: tuple[FileMigration, ...]


class ConfigMigrationError(ValueError):
    """A migration could not finish after preflight succeeded.

    :param message: Human-readable failure.
    :param completed: Moves completed before the failure.
    """

    def __init__(
        self,
        message: str,
        *,
        completed: tuple[FileMigration, ...] = (),
    ) -> None:
        """Store the failure and successfully completed moves."""
        super().__init__(message)
        self.completed = completed


def build_config_migration_plan(
    spec: AppConfigSpec,
    *,
    storage_roots: tuple[Path, ...] = (),
) -> ConfigMigrationPlan:
    """Preflight app, TOML, and known storage dotenv migrations.

    :param spec: Current application declaration.
    :param storage_roots: Active and registered storage directories.
    :return: Complete move and conflict inventory without filesystem writes.
    """
    if spec.uses_legacy_constructor():
        raise ConfigMigrationError(
            "config migrate requires the direct AppRC(...) declaration. "
            "Update the application integration before moving its files."
        )
    resources = [
        ("app dotenv", spec.app_env_resolution()),
        ("AppRC TOML", spec.apprc_toml_resolution()),
    ]
    resources.extend(
        (
            f"storage dotenv ({root})",
            spec.storage_env_resolution(root),
        )
        for root in _unique_roots(storage_roots)
    )
    moves: list[FileMigration] = []
    conflicts: list[MigrationConflict] = []
    for label, resolution in resources:
        moves.extend(_migration_for_resolution(label, resolution))
        conflicts.extend(_conflicts_for_resolution(label, resolution))
    return ConfigMigrationPlan(
        moves=tuple(moves),
        conflicts=tuple(conflicts),
    )


def apply_config_migration(
    plan: ConfigMigrationPlan,
) -> ConfigMigrationResult:
    """Apply a conflict-free migration plan using same-directory moves.

    :param plan: Preflighted migration plan.
    :return: Completed filename moves.
    :raises ConfigMigrationError: If conflicts exist or a move fails.
    """
    if plan.conflicts:
        raise ConfigMigrationError(
            "Migration has filename conflicts. No files were moved."
        )
    completed: list[FileMigration] = []
    for move in plan.moves:
        try:
            _move_without_replacing(move)
        except OSError as exc:
            raise ConfigMigrationError(
                f"Could not move {move.source} to {move.destination}: {exc}",
                completed=tuple(completed),
            ) from exc
        completed.append(move)
    return ConfigMigrationResult(moved=tuple(completed))


def _move_without_replacing(move: FileMigration) -> None:
    """Move one managed file without replacing a late-created destination.

    A same-directory hard link reserves the destination atomically. Removing
    the source completes the rename-equivalent operation. If source removal
    fails, AppRC removes the new link so the original path remains authoritative.

    :param move: Preflighted source and destination pair.
    :raises OSError: If the source changed, the destination exists, or the
        filesystem operation fails.
    """
    if not move.source.is_file() and not move.source.is_symlink():
        raise FileNotFoundError(
            f"migration source is no longer a file: {move.source}"
        )
    os.link(
        move.source,
        move.destination,
        follow_symlinks=False,
    )
    try:
        move.source.unlink()
    except OSError as exc:
        try:
            move.destination.unlink()
        except OSError as rollback_exc:
            exc.add_note(
                "AppRC also could not remove the newly linked destination: "
                f"{rollback_exc}"
            )
        raise


def _migration_for_resolution(
    label: str,
    resolution: ManagedFileResolution,
) -> tuple[FileMigration, ...]:
    """Return the safe move represented by one resolution."""
    if resolution.conflicts or not resolution.uses_legacy_path:
        return ()
    return (
        FileMigration(
            source=resolution.selected,
            destination=resolution.preferred,
            label=label,
        ),
    )


def _conflicts_for_resolution(
    label: str,
    resolution: ManagedFileResolution,
) -> tuple[MigrationConflict, ...]:
    """Return conflicts represented by one resolution."""
    return tuple(
        MigrationConflict(
            preferred=resolution.selected,
            conflicting=path,
            label=label,
        )
        for path in resolution.conflicts
    )


def _unique_roots(storage_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    """Return normalized storage roots in first-seen order."""
    unique: list[Path] = []
    for root in storage_roots:
        normalized = Path(root).expanduser().resolve()
        if normalized not in unique:
            unique.append(normalized)
    return tuple(unique)
