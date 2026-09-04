"""Narrow removal of files and storage roots managed by AppRC."""

from __future__ import annotations

# == Standard Library ===========================================
import os
from dataclasses import dataclass
from pathlib import Path

# == Internal ===================================================
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.user_files.storage_roots._io import load_storage_registry_or_empty


class ConfigPurgeError(ValueError):
    """A purge could not be planned or applied safely."""


@dataclass(frozen=True, slots=True)
class ConfigPurgePlan:
    """Exact purge targets resolved before any deletion.

    :param apprc_dir: Selected AppRC directory.
    :param managed_files: Fixed AppRC and storage dotenv files.
    :param internal_storage_roots: Registered roots strictly below AppRC dir.
    :param external_storage_roots: Registered roots whose other data is kept.
    :param stale_storage: Whether records came from an unsupported capability.
    """

    apprc_dir: Path
    managed_files: tuple[Path, ...]
    internal_storage_roots: tuple[Path, ...]
    external_storage_roots: tuple[Path, ...]
    stale_storage: bool


@dataclass(frozen=True, slots=True)
class ConfigPurgeResult:
    """Completed purge details.

    :param removed: Files and directories removed.
    :param skipped: Unsafe or non-file fixed targets left in place.
    """

    removed: tuple[Path, ...]
    skipped: tuple[Path, ...]


def build_config_purge_plan(spec: AppConfigSpec) -> ConfigPurgePlan:
    """Resolve exact purge targets and validate the registry first.

    A malformed registry stops planning before any write. Files on disk never
    enable storage support, but stale records remain eligible for an explicit
    purge.

    :param spec: Application declaration.
    :return: Preflighted purge plan.
    :raises ConfigPurgeError: If an existing registry cannot be parsed.
    """
    paths = spec.paths()
    if _has_symlink_at_or_above(paths.root):
        raise ConfigPurgeError(
            "Refusing to purge through a symbolic-link component in the "
            f"AppRC directory: {paths.root}"
        )
    registry = None
    if paths.apprc_toml.exists() or paths.apprc_toml.is_symlink():
        if paths.apprc_toml.is_symlink():
            raise ConfigPurgeError(
                f"Refusing to read symbolic-link registry: {paths.apprc_toml}"
            )
        try:
            registry = load_storage_registry_or_empty(paths.apprc_toml)
        except (OSError, ValueError) as exc:
            raise ConfigPurgeError(
                f"Purge stopped before deleting files because {paths.apprc_toml} "
                f"is invalid: {exc}"
            ) from exc

    managed_files = [paths.user_dotenv, paths.apprc_toml]
    internal_roots: list[Path] = []
    external_roots: list[Path] = []
    if registry is not None:
        for record in registry.storages.values():
            root = record.root.expanduser().absolute()
            managed_files.append(root / spec.storage_dotenv_filename)
            if _is_strict_descendant(root, paths.root):
                internal_roots.append(root)
            else:
                external_roots.append(root)

    return ConfigPurgePlan(
        apprc_dir=paths.root.expanduser().absolute(),
        managed_files=_unique_paths(managed_files),
        internal_storage_roots=_unique_paths(internal_roots),
        external_storage_roots=_unique_paths(external_roots),
        stale_storage=registry is not None and not spec.uses_storage(),
    )


def apply_config_purge(plan: ConfigPurgePlan) -> ConfigPurgeResult:
    """Delete only targets named by a preflighted purge plan.

    :param plan: Exact files and registered internal roots to remove.
    :return: Removed and skipped targets.
    """
    removed: list[Path] = []
    skipped: list[Path] = []

    internal_files = {
        root / file.name
        for root in plan.internal_storage_roots
        for file in plan.managed_files
        if file.parent == root
    }
    for path in plan.managed_files:
        if path in internal_files:
            continue
        if not path.exists() and not path.is_symlink():
            continue
        if _has_symlink_at_or_above(path.parent):
            skipped.append(path)
            continue
        if path.is_symlink() or path.is_file():
            path.unlink()
            removed.append(path)
        else:
            skipped.append(path)

    for root in sorted(
        plan.internal_storage_roots,
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if not root.exists() and not root.is_symlink():
            continue
        if (
            root.is_symlink()
            or _has_symlink_component(root, boundary=plan.apprc_dir)
            or not root.is_dir()
        ):
            skipped.append(root)
            continue
        _remove_tree_without_following_symlinks(root, removed=removed)

    _remove_empty_parents(plan.apprc_dir, removed=removed)
    return ConfigPurgeResult(
        removed=tuple(removed),
        skipped=tuple(skipped),
    )


def _remove_tree_without_following_symlinks(
    root: Path,
    *,
    removed: list[Path],
) -> None:
    """Remove a known directory tree without traversing symbolic links.

    :param root: Registered internal storage root.
    :param removed: Result accumulator.
    """
    with os.scandir(root) as entries:
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                path.unlink()
                removed.append(path)
            elif entry.is_dir(follow_symlinks=False):
                _remove_tree_without_following_symlinks(path, removed=removed)
            else:
                path.unlink()
                removed.append(path)
    root.rmdir()
    removed.append(root)


def _remove_empty_parents(root: Path, *, removed: list[Path]) -> None:
    """Remove the AppRC directory only when it is an empty real directory.

    :param root: AppRC directory selected by the declaration.
    :param removed: Result accumulator.
    """
    if root.is_symlink() or not root.is_dir():
        return
    try:
        root.rmdir()
    except OSError:
        return
    removed.append(root)


def _is_strict_descendant(path: Path, parent: Path) -> bool:
    """Return whether a lexical path lies strictly below another.

    ``resolve()`` is intentionally avoided because purge must not follow
    symbolic links while classifying deletion scope.

    :param path: Candidate registered root.
    :param parent: AppRC directory boundary.
    :return: Whether the root is inside but not equal to the boundary.
    """
    absolute_path = path.expanduser().absolute()
    absolute_parent = parent.expanduser().absolute()
    return absolute_path != absolute_parent and absolute_path.is_relative_to(
        absolute_parent
    )


def _has_symlink_component(path: Path, *, boundary: Path) -> bool:
    """Return whether a managed descendant traverses a symbolic link.

    :param path: Registered internal root.
    :param boundary: AppRC directory above it.
    :return: Whether any descendant component is a link.
    """
    relative = path.relative_to(boundary)
    current = boundary
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _has_symlink_at_or_above(path: Path) -> bool:
    """Return whether a path or one of its parents is a symbolic link.

    :param path: Lexical path whose directory chain will be traversed.
    :return: Whether normal filesystem access would follow a link.
    """
    absolute = path.expanduser().absolute()
    return any(
        candidate.is_symlink() for candidate in (absolute, *absolute.parents)
    )


def _unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    """Return paths in first-seen order without duplicates.

    :param paths: Path sequence.
    :return: Deduplicated tuple.
    """
    return tuple(dict.fromkeys(path.expanduser().absolute() for path in paths))
