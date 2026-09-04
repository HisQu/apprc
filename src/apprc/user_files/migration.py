"""Explicit migration from released AppRC 0.19 layouts."""

from __future__ import annotations

# == Standard Library ===========================================
import os
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

# == Internal ===================================================
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.runtime._dotenv_layers import read_dotenv_file
from apprc.user_files.app_home.locations import write_text_atomic
from apprc.user_files.managed_files import path_entry_exists
from apprc.user_files.storage_roots._io import (
    load_storage_registry_or_empty,
    render_storage_registry,
)
from apprc.user_files.storage_roots.model import StorageRecord, StorageRegistry
from apprc.user_files.storage_roots.paths import resolve_storage_root_path
from apprc.user_files.storage_roots.selector import (
    storage_selector_is_path_like,
)


@dataclass(frozen=True, slots=True)
class FileMigration:
    """One legacy file move.

    :param source: Existing released-0.19 file.
    :param destination: Current fixed path.
    :param label: Human-readable resource name.
    """

    source: Path
    destination: Path
    label: str


@dataclass(frozen=True, slots=True)
class TextMigration:
    """One generated or transformed managed text file.

    :param source: Legacy source removed after the destination is written.
    :param destination: Current fixed path.
    :param text: Complete UTF-8 destination contents.
    :param label: Human-readable resource name.
    """

    source: Path | None
    destination: Path
    text: str
    label: str


@dataclass(frozen=True, slots=True)
class MigrationConflict:
    """Two files that prevent an automatic migration.

    :param preferred: Current destination or selected legacy source.
    :param conflicting: Other existing file.
    :param label: Human-readable resource name.
    """

    preferred: Path
    conflicting: Path
    label: str


@dataclass(frozen=True, slots=True)
class ConfigMigrationPlan:
    """Complete released-0.19 migration preflight.

    :param moves: Files that retain their bytes while moving.
    :param writes: New or transformed text files.
    :param conflicts: Ambiguous files that need manual resolution.
    :param warnings: Environment cleanup that AppRC cannot perform.
    """

    moves: tuple[FileMigration, ...]
    writes: tuple[TextMigration, ...]
    conflicts: tuple[MigrationConflict, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConfigMigrationResult:
    """Outcome of applying a migration plan.

    :param moved: Byte-preserving moves completed.
    :param written: Generated or transformed files completed.
    """

    moved: tuple[FileMigration, ...]
    written: tuple[TextMigration, ...]


class ConfigMigrationError(ValueError):
    """A migration could not finish safely.

    :param message: Human-readable failure.
    :param completed: Byte-preserving moves completed before failure.
    """

    def __init__(
        self,
        message: str,
        *,
        completed: tuple[FileMigration, ...] = (),
    ) -> None:
        """Store the failure and completed moves."""
        super().__init__(message)
        self.completed = completed


def build_config_migration_plan(
    spec: AppConfigSpec,
    *,
    storage_roots: tuple[Path, ...] = (),
    proc_env: Mapping[str, str] | None = None,
) -> ConfigMigrationPlan:
    """Preflight every released AppRC 0.19 location and selector.

    The scan includes platformdirs-style config directories, custom
    ``<APP>_APPRC_TOML`` paths, path-valued ``<APP>_STORAGE`` selectors, and
    the released dotenv filenames. The unreleased ``apprc.app.env`` name is
    intentionally ignored.

    :param spec: Current application declaration.
    :param storage_roots: Additional registered roots already visible to CLI.
    :param proc_env: Environment mapping used instead of ``os.environ``.
    :return: Complete preflight without filesystem writes.
    """
    env = os.environ if proc_env is None else proc_env
    app_ids = (spec.app_id, *spec.legacy_app_ids)
    paths = spec.paths(proc_env=env)
    legacy_dirs = _unique_paths(
        [
            paths.root,
            *(
                legacy_platform_config_dir(app_id, proc_env=env)
                for app_id in app_ids
            ),
        ]
    )
    conflicts: list[MigrationConflict] = []
    moves: list[FileMigration] = []
    writes: list[TextMigration] = []
    warnings: list[str] = []

    user_sources = _existing_files(
        directory / ".env.apprc-app" for directory in legacy_dirs
    )
    user_source = _single_source(
        label="user dotenv",
        destination=paths.user_dotenv,
        candidates=user_sources,
        conflicts=conflicts,
    )
    user_path = user_source or (
        paths.user_dotenv if paths.user_dotenv.is_file() else None
    )
    user_text = user_path.read_text(encoding="utf-8") if user_path else ""
    user_values = read_dotenv_file(user_path)
    structural_keys = tuple(
        dict.fromkeys(
            [
                *(spec.legacy_apprc_toml_env_keys()),
                *(
                    f"{_environment_prefix(app_id)}_STORAGE"
                    for app_id in app_ids
                ),
            ]
        )
    )
    filtered_user_text = _without_dotenv_keys(user_text, structural_keys)

    registry_source = None
    registry: StorageRegistry | None = None
    if spec.uses_storage():
        registry_candidates = _legacy_registry_candidates(
            spec,
            app_ids=app_ids,
            legacy_dirs=legacy_dirs,
            env=env,
        )
        registry_source = _single_source(
            label="AppRC TOML",
            destination=paths.apprc_toml,
            candidates=registry_candidates,
            conflicts=conflicts,
        )
        registry_path = registry_source or paths.apprc_toml
        try:
            registry = load_storage_registry_or_empty(registry_path)
        except (OSError, ValueError) as exc:
            raise ConfigMigrationError(
                f"Could not read released AppRC registry {registry_path}: {exc}"
            ) from exc
        registry = replace(registry, path=paths.apprc_toml)

        selector_key, selector_value = _legacy_selector(
            spec,
            app_ids=app_ids,
            env=env,
            user_values=user_values,
        )
        if selector_value is not None:
            registry = _apply_legacy_selector(
                registry,
                key=selector_key or spec.require_storage_selector_env_key(),
                value=selector_value,
            )
        elif registry.selected_storage is None and len(registry.storages) == 1:
            registry = replace(
                registry,
                selected_storage=next(iter(registry.storages)),
            )

        if selector_key is not None and selector_key in env:
            warnings.append(
                f"Unset exported {selector_key} after migration if it contains "
                "a path; migration records it as the named default storage."
            )
        for key in spec.legacy_apprc_toml_env_keys():
            if env.get(key, "").strip():
                warnings.append(
                    f"Unset exported {key}; use {spec.apprc_dir_env_key} to "
                    "relocate the complete AppRC directory."
                )

        roots = _unique_paths(
            [
                *storage_roots,
                *(record.root for record in registry.storages.values()),
            ]
        )
        for root in roots:
            source = root / ".env.apprc-storage"
            destination = root / spec.storage_dotenv_filename
            if source.is_file():
                _add_move_or_conflict(
                    label=f"storage dotenv ({root})",
                    source=source,
                    destination=destination,
                    moves=moves,
                    conflicts=conflicts,
                )

        rendered = render_storage_registry(registry)
        current_text = (
            paths.apprc_toml.read_text(encoding="utf-8")
            if paths.apprc_toml.is_file()
            else None
        )
        if registry_source is not None or current_text != rendered:
            writes.append(
                TextMigration(
                    source=registry_source,
                    destination=paths.apprc_toml,
                    text=rendered,
                    label="AppRC TOML",
                )
            )

    current_user_text = (
        paths.user_dotenv.read_text(encoding="utf-8")
        if paths.user_dotenv.is_file()
        else None
    )
    should_create_user = user_source is not None or (
        spec.uses_storage() and registry is not None
    )
    if should_create_user and current_user_text != filtered_user_text:
        writes.append(
            TextMigration(
                source=user_source,
                destination=paths.user_dotenv,
                text=filtered_user_text,
                label="user dotenv",
            )
        )

    return ConfigMigrationPlan(
        moves=tuple(moves),
        writes=tuple(writes),
        conflicts=tuple(conflicts),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def apply_config_migration(plan: ConfigMigrationPlan) -> ConfigMigrationResult:
    """Apply a conflict-free migration plan.

    :param plan: Preflighted migration actions.
    :return: Completed actions.
    :raises ConfigMigrationError: If conflicts exist or an action fails.
    """
    if plan.conflicts:
        raise ConfigMigrationError(
            "Migration has file conflicts. No files were changed."
        )
    completed_moves: list[FileMigration] = []
    completed_writes: list[TextMigration] = []
    try:
        for move in plan.moves:
            _move_without_replacing(move)
            completed_moves.append(move)
        for write in plan.writes:
            _write_migration(write)
            completed_writes.append(write)
    except OSError as exc:
        raise ConfigMigrationError(
            f"Migration stopped after a filesystem error: {exc}",
            completed=tuple(completed_moves),
        ) from exc
    return ConfigMigrationResult(
        moved=tuple(completed_moves),
        written=tuple(completed_writes),
    )


def legacy_platform_config_dir(
    app_id: str,
    *,
    proc_env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """Reproduce the released platformdirs config location for migration.

    This isolated locator is not used by new installs.

    :param app_id: Released application identity.
    :param proc_env: Environment mapping used for platform base directories.
    :param platform: Platform override used by tests.
    :return: Former ``platformdirs.user_config_path`` result.
    """
    env = os.environ if proc_env is None else proc_env
    active_platform = sys.platform if platform is None else platform
    if active_platform == "win32":
        base = Path(env.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif active_platform == "darwin":
        base = (
            Path(env.get("HOME", Path.home()))
            / "Library"
            / "Application Support"
        )
    else:
        base = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base.expanduser() / app_id


def _legacy_registry_candidates(
    spec: AppConfigSpec,
    *,
    app_ids: tuple[str, ...],
    legacy_dirs: tuple[Path, ...],
    env: Mapping[str, str],
) -> tuple[Path, ...]:
    """Return existing released registry locations in priority order.

    :param spec: Current declaration.
    :param app_ids: Current and former stable identities.
    :param legacy_dirs: Current and former application directories.
    :param env: Environment containing optional legacy relocation keys.
    :return: Existing candidate files.
    """
    candidates: list[Path] = []
    for key in spec.legacy_apprc_toml_env_keys():
        value = env.get(key, "").strip()
        if value:
            candidates.append(Path(value).expanduser().absolute())
    for directory in legacy_dirs:
        candidates.extend(
            directory / spec.derive_legacy_apprc_toml_filename(app_id)
            for app_id in app_ids
        )
    return _existing_files(candidates)


def _legacy_selector(
    spec: AppConfigSpec,
    *,
    app_ids: tuple[str, ...],
    env: Mapping[str, str],
    user_values: Mapping[str, str],
) -> tuple[str | None, str | None]:
    """Return the first released storage selector and its key.

    :param spec: Current declaration.
    :param app_ids: Current and former stable identities.
    :param env: Process environment.
    :param user_values: Values parsed from the released user dotenv.
    :return: Key and value, or ``(None, None)``.
    """
    keys = tuple(
        dict.fromkeys(
            [
                spec.require_storage_selector_env_key(),
                *(
                    f"{_environment_prefix(app_id)}_STORAGE"
                    for app_id in app_ids
                ),
            ]
        )
    )
    for values in (env, user_values):
        for key in keys:
            value = values.get(key, "").strip()
            if value:
                return key, value
    return None, None


def _apply_legacy_selector(
    registry: StorageRegistry,
    *,
    key: str,
    value: str,
) -> StorageRegistry:
    """Convert a released selector into ``selected_storage``.

    :param registry: Registry being migrated.
    :param key: Legacy environment key used in errors.
    :param value: Name or path from the released setup.
    :return: Updated registry.
    """
    selector = value.strip()
    if selector in registry.storages:
        return replace(registry, selected_storage=selector)
    if registry.storages and not storage_selector_is_path_like(selector):
        known = ", ".join(sorted(registry.storages))
        raise ConfigMigrationError(
            f"{key} contains unknown storage name {selector!r}. Known "
            f"storages: {known}. Resolve it before migration."
        )
    root = resolve_storage_root_path(selector, base=registry.path.parent)
    existing = registry.storages.get("default")
    if existing is not None and existing.root != root:
        raise ConfigMigrationError(
            "Cannot convert the path-valued selector because storage "
            f"'default' already points to {existing.root}, not {root}."
        )
    storages = dict(registry.storages)
    storages["default"] = StorageRecord(name="default", root=root)
    return replace(
        registry,
        storages=storages,
        selected_storage="default",
    )


def _without_dotenv_keys(text: str, keys: tuple[str, ...]) -> str:
    """Remove structural selectors while retaining unrelated dotenv text.

    :param text: Original dotenv contents.
    :param keys: Exact environment keys to remove.
    :return: Filtered text.
    """
    patterns = [
        re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=") for key in keys
    ]
    lines = [
        line
        for line in text.splitlines()
        if not any(pattern.match(line) for pattern in patterns)
    ]
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def _single_source(
    *,
    label: str,
    destination: Path,
    candidates: tuple[Path, ...],
    conflicts: list[MigrationConflict],
) -> Path | None:
    """Choose one legacy source and record every ambiguity.

    :param label: Human-readable resource name.
    :param destination: Current fixed file path.
    :param candidates: Existing legacy files.
    :param conflicts: Conflict accumulator.
    :return: Selected source, if unambiguous.
    """
    filtered = tuple(path for path in candidates if path != destination)
    if not filtered:
        return None
    preferred = destination if path_entry_exists(destination) else filtered[0]
    conflict_candidates = filtered if preferred == destination else filtered[1:]
    conflicts.extend(
        MigrationConflict(
            preferred=preferred,
            conflicting=path,
            label=label,
        )
        for path in conflict_candidates
    )
    return filtered[0] if not path_entry_exists(destination) else None


def _add_move_or_conflict(
    *,
    label: str,
    source: Path,
    destination: Path,
    moves: list[FileMigration],
    conflicts: list[MigrationConflict],
) -> None:
    """Append one safe move or destination conflict.

    :param label: Human-readable resource name.
    :param source: Existing legacy file.
    :param destination: Current fixed path.
    :param moves: Move accumulator.
    :param conflicts: Conflict accumulator.
    """
    if path_entry_exists(destination):
        conflicts.append(
            MigrationConflict(
                preferred=destination,
                conflicting=source,
                label=label,
            )
        )
    else:
        moves.append(
            FileMigration(
                source=source,
                destination=destination,
                label=label,
            )
        )


def _write_migration(write: TextMigration) -> None:
    """Write transformed text and remove its distinct legacy source.

    :param write: Preflighted text action.
    """
    source = write.source
    if source is not None and source != write.destination:
        if path_entry_exists(write.destination):
            raise FileExistsError(
                f"migration destination now exists: {write.destination}"
            )
        write.destination.parent.mkdir(parents=True, exist_ok=True)
        with write.destination.open("x", encoding="utf-8") as file:
            file.write(write.text)
        try:
            source.unlink()
        except OSError:
            write.destination.unlink(missing_ok=True)
            raise
        return
    write_text_atomic(write.destination, write.text)


def _move_without_replacing(move: FileMigration) -> None:
    """Move one managed file without replacing a late destination.

    :param move: Preflighted source and destination.
    """
    if not move.source.is_file() or move.source.is_symlink():
        raise FileNotFoundError(
            f"migration source is no longer a regular file: {move.source}"
        )
    if path_entry_exists(move.destination):
        raise FileExistsError(
            f"migration destination now exists: {move.destination}"
        )
    move.destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(move.source, move.destination, follow_symlinks=False)
    except OSError:
        try:
            with move.source.open("rb") as source_file:
                with move.destination.open("xb") as destination_file:
                    destination_file.write(source_file.read())
        except OSError:
            move.destination.unlink(missing_ok=True)
            raise
    try:
        move.source.unlink()
    except OSError:
        move.destination.unlink(missing_ok=True)
        raise


def _existing_files(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return unique existing regular files from an iterable.

    :param paths: Iterable of path-like values.
    :return: Existing files in first-seen order.
    """
    return tuple(
        path
        for path in _unique_paths(list(paths))
        if path.is_file() and not path.is_symlink()
    )


def _unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    """Return absolute paths in first-seen order.

    :param paths: Path sequence.
    :return: Deduplicated tuple.
    """
    return tuple(dict.fromkeys(path.expanduser().absolute() for path in paths))


def _environment_prefix(app_id: str) -> str:
    """Return the released normalized environment prefix.

    :param app_id: Application identity.
    :return: Uppercase environment prefix.
    """
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", app_id).strip("_").upper()
    return normalized or "APP"
