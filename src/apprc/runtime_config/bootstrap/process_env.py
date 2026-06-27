"""Process environment writes and shell-side provenance for bootstrap."""

from __future__ import annotations

# == Standard Library ========================
import os
from pathlib import Path
from typing import Mapping

# == Internal ================================
from apprc.runtime_config.bootstrap.dotenv_layers import ExplicitEnvLayer
from apprc.runtime_config.app_spec import AppConfigSpec
from apprc.runtime_config.provenance import (
    EnvValueOrigin,
    ShellProvenanceOrigin,
)


def write_bootstrap_environment(
    values: Mapping[str, str],
    *,
    storage_env_key: str | None = None,
    storage_root: Path | None = None,
) -> None:
    """Apply bootstrap values to this Python process only.

    :param values: Merged dotenv and inherited environment values.
    :param storage_env_key: App-owned env key that points at active storage.
    :param storage_root: Resolved active storage root written after merge.
    """
    os.environ.update(values)
    if storage_env_key is not None and storage_root is not None:
        os.environ[storage_env_key] = str(storage_root)


def app_env_keys(spec: AppConfigSpec) -> set[str]:
    """Return env keys owned by one application contract.

    :param spec: Application-specific bootstrap contract.
    :return: Full env keys that AppRC should track for this app.
    """
    keys = {spec.index_env_key}
    if spec.storage_env_key is not None:
        keys.add(spec.storage_env_key)
    for owner in spec.owners:
        keys.update(
            owner.env_key(owner_field.name) for owner_field in owner.fields
        )
    return keys


def original_env_value_origins(
    *,
    app_env_keys: set[str],
    original_env: Mapping[str, str],
) -> dict[str, EnvValueOrigin]:
    """Return shell-export origins from the pre-bootstrap process env.

    :param app_env_keys: App-owned env keys eligible for provenance tracking.
    :param original_env: Process environment captured before bootstrap writes.
    :return: Existing env values keyed by env key.
    """
    return {
        key: EnvValueOrigin(
            env_key=key,
            origin="shell_export_variable",
            value=original_env[key],
        )
        for key in app_env_keys
        if key in original_env
    }


def merged_env_value_origins(
    *,
    app_env_keys: set[str],
    shared_env_path: Path,
    shared_values: Mapping[str, str],
    app_wide_env_path: Path | None,
    app_wide_values: Mapping[str, str],
    storage_env_path: Path | None,
    storage_values: Mapping[str, str],
    explicit_layers: tuple[ExplicitEnvLayer, ...],
    original_env: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, EnvValueOrigin]:
    """Return winning env-value origins using runtime bootstrap precedence.

    :param app_env_keys: App-owned env keys eligible for provenance tracking.
    :param shared_env_path: Packaged shared dotenv path.
    :param shared_values: Parsed packaged shared dotenv values.
    :param app_wide_env_path: App-wide dotenv path.
    :param app_wide_values: Parsed app-wide dotenv values.
    :param storage_env_path: Active storage dotenv path.
    :param storage_values: Parsed storage dotenv values.
    :param explicit_layers: Parsed explicit env files in command/API order.
    :param original_env: Process environment captured before bootstrap writes.
    :param env_file_overrides_os_environ: Whether explicit dotenv values beat
        existing values in ``os.environ`` inside this process.
    :return: Winning env-value origins keyed by env key.
    """
    origins: dict[str, EnvValueOrigin] = {}

    def apply_values(
        values: Mapping[str, str],
        origin: ShellProvenanceOrigin,
        *,
        path: Path | None = None,
    ) -> None:
        for key, value in values.items():
            if key not in app_env_keys:
                continue
            origins[key] = EnvValueOrigin(
                env_key=key,
                origin=origin,
                value=value,
                path=path,
            )

    apply_values(shared_values, "shell_dotenv_shared", path=shared_env_path)
    if app_wide_env_path is not None:
        apply_values(
            app_wide_values,
            "shell_dotenv_app_wide",
            path=app_wide_env_path,
        )
    if storage_env_path is not None:
        apply_values(
            storage_values,
            "shell_dotenv_storage",
            path=storage_env_path,
        )
    if env_file_overrides_os_environ:
        apply_values(original_env, "shell_export_variable")
        for layer in explicit_layers:
            apply_values(
                layer.values,
                "shell_dotenv_explicit",
                path=layer.path,
            )
        return origins

    for layer in explicit_layers:
        apply_values(
            layer.values,
            "shell_dotenv_explicit",
            path=layer.path,
        )
    apply_values(original_env, "shell_export_variable")
    return origins


def selection_env(
    *,
    original_env: Mapping[str, str],
    explicit_values: Mapping[str, str],
    env_file_overrides_os_environ: bool,
) -> dict[str, str]:
    """Return env values used before dotenv layers mutate ``os.environ``."""
    if env_file_overrides_os_environ:
        return {**original_env, **explicit_values}
    return {**explicit_values, **original_env}
