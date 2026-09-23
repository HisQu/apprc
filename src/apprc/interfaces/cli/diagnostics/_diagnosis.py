"""Read-only AppRC diagnosis behind the public doctor payload."""

from __future__ import annotations

from apprc.user_files.app_home.application import AppFiles

# == Standard Library ===========================================
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

# == Internal ===================================================
from apprc.user_files.env_files.layers import read_dotenv_file
from apprc.runtime.resolution import ResolvedConfig
from apprc.interfaces.cli.diagnostics.status import ConfigDoctorStatus
from apprc.user_files.app_home.locations import AppRCDirectoryPaths
from apprc.user_files.storage_roots._loading import (
    StorageRegistryInspection,
)
from apprc.user_files.storage_roots.selector import (
    StorageSelection,
)

if TYPE_CHECKING:
    from apprc.public.app_rc import AppRC
    from apprc.definition.app_config.spec import AppConfigSpec


@dataclass(frozen=True, slots=True)
class StorageDiagnosis:
    """Active storage state discovered for one doctor run."""

    required: bool
    selection: StorageSelection | None
    storage_root_exists: bool | None
    storage_dotenv: Path | None
    storage_dotenv_exists: bool | None
    selection_missing: bool
    selector_error: bool
    issues: list[str]
    registry: StorageRegistryInspection


@dataclass(frozen=True, slots=True)
class UserDotenvDiagnosis:
    """Per-user dotenv state discovered for one doctor run."""

    active: bool
    issues: list[str]
    warnings: list[str]


def diagnose_user_dotenv(
    apprc: "AppRC",
    *,
    paths: AppRCDirectoryPaths,
) -> UserDotenvDiagnosis:
    """Return per-user dotenv readiness without creating files.

    :param apprc: Application config facade.
    :param paths: Fixed paths below the selected AppRC directory.
    :return: Per-user dotenv diagnosis.
    """
    if not apprc.schema.uses_user_dotenv():
        warnings = (
            [
                "Ignored stale user dotenv because the application does not "
                f"declare user-dotenv support: {paths.user_dotenv}"
            ]
            if paths.user_dotenv.is_file()
            else []
        )
        return UserDotenvDiagnosis(
            active=False,
            issues=[],
            warnings=warnings,
        )
    if not paths.user_dotenv.is_file():
        return UserDotenvDiagnosis(active=True, issues=[], warnings=[])
    try:
        read_dotenv_file(paths.user_dotenv)
    except OSError as exc:
        return UserDotenvDiagnosis(
            active=True,
            issues=[
                f"User dotenv file could not be read: {paths.user_dotenv}: {exc}"
            ],
            warnings=[],
        )
    return UserDotenvDiagnosis(active=True, issues=[], warnings=[])


def diagnose_storage(
    apprc: "AppRC",
    *,
    resolved: ResolvedConfig,
    registry: StorageRegistryInspection,
) -> StorageDiagnosis:
    """Translate shared runtime readiness into terminal report metadata.

    :param apprc: Application declaration.
    :param resolved: Shared inspection resolution, including readiness findings.
    :param registry: Shared inspection of the registry and directory selection.
    :return: Storage status for CLI rendering; no separate selector policy.
    """
    selection = resolved.selection
    if not apprc.schema.uses_storage():
        registry = replace(
            registry, issues=[], warnings=[*registry.warnings, *registry.issues]
        )
    elif not registry.exists or (
        selection is not None and selection.selector_kind == "path"
    ):
        registry = replace(
            registry, issues=[], warnings=[*registry.warnings, *registry.issues]
        )
    root = selection.root if selection is not None else None
    dotenv = (
        AppFiles(apprc.schema).storage_dotenv_path(root)
        if root is not None
        else None
    )
    key = apprc.schema.storage_selector_env_key
    selector_requested = resolved.options.storage is not None or any(
        layer.source.values.get(key or "", "").strip()
        for layer in resolved.layers
        if layer.origin in {"shell_export_variable", "shell_dotenv_explicit"}
    )
    return StorageDiagnosis(
        required=resolved.options.storage_required,
        selection=selection,
        storage_root_exists=root.is_dir() if root is not None else None,
        storage_dotenv=dotenv,
        storage_dotenv_exists=dotenv.is_file() if dotenv is not None else None,
        selection_missing=selection is None and not selector_requested,
        selector_error=selection is None and selector_requested,
        issues=list(resolved.storage_issues),
        registry=registry,
    )


def doctor_status(
    *,
    user_dotenv: UserDotenvDiagnosis,
    registry: StorageRegistryInspection,
    storage: StorageDiagnosis,
) -> ConfigDoctorStatus:
    """Return the overall readiness status.

    :param user_dotenv: User dotenv diagnosis.
    :param registry: Storage registry diagnosis.
    :param storage: Active storage diagnosis.
    :return: Public status value.
    """
    if user_dotenv.issues:
        return ConfigDoctorStatus.USER_DOTENV_NOT_READY
    if registry.issues:
        return ConfigDoctorStatus.STORAGE_REGISTRY_NOT_READY
    if storage.required and storage.selection_missing:
        return ConfigDoctorStatus.STORAGE_NOT_SELECTED
    if storage.issues:
        return ConfigDoctorStatus.STORAGE_NOT_READY
    return ConfigDoctorStatus.RUNNABLE


def legacy_file_warnings(
    spec: "AppConfigSpec",
    *,
    storage_root: Path | None,
    paths: AppRCDirectoryPaths,
) -> list[str]:
    """Return warnings for released 0.19 filenames in current locations.

    Full cross-directory discovery belongs to ``config migrate``. Doctor keeps
    this check cheap and warns about immediately adjacent legacy files.

    :param spec: Current application declaration.
    :param storage_root: Selected storage root, if any.
    :param paths: Invocation-selected managed directory.
    :return: Human-readable migration warnings.
    """
    candidates = []
    if spec.uses_user_dotenv():
        candidates.append(paths.root / ".env.apprc-app")
    if storage_root is not None:
        candidates.append(storage_root / ".env.apprc-storage")
    return [
        f"Legacy AppRC file exists: {path}. Run `config migrate`."
        for path in candidates
        if path.is_file()
    ]
