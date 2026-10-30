"""Resolve declared application locations without touching the filesystem."""

from __future__ import annotations
import sys

from collections.abc import Collection, Mapping


from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.paths import AppPaths, Layout
from apprc.definition.installation import InstallationError, OperationContext
from apprc.user_files.installation.discovery import (
    inspect_installation,
    installation_directory,
    native_user_directories,
)
from apprc.definition.resolution import ResolveOptions
from apprc.user_files.env_files.layers import (
    ExplicitEnvFileError,
    read_explicit_env_files,
)


def resolve_app_paths(
    spec: AppConfigSpec,
    options: ResolveOptions,
    environment: Mapping[str, str],
    *,
    excluded_env_keys: Collection[str] = frozenset(),
    excluded_env_prefixes: Collection[str] = (),
    operation_context: OperationContext | None = None,
    allow_unready: bool = False,
) -> AppPaths:
    """Capture enabled paths from one atomic layout selection.

    Invocation overrides win as a complete layout. Otherwise the highest raw
    environment layer containing either control supplies both values; a lower
    layer can never contribute the missing half of that pair.

    :param spec: Application identity, component declaration, and fallback layout.
    :param options: Invocation layout and explicit environment files.
    :param environment: Detached process environment snapshot.
    :param excluded_env_keys: Dependency-owned control and setting keys to skip.
    :param excluded_env_prefixes: Dependency-owned key prefixes to skip.
    :param operation_context: Explicit pending namespace and captured placement.
    :param allow_unready: Skip unreadable explicit files for diagnostic inspection.
    :return: Absolute paths for enabled components only.
    """
    layout_key, root_key = spec.layout_env_key, spec.root_env_key
    inspection = inspect_installation(
        operation_context.directory
        if operation_context is not None
        else installation_directory(spec.app_id, environment=environment),
        app_id=spec.app_id,
    )
    if operation_context is not None:
        if (
            options.layout is not None
            and options.layout != operation_context.placement.layout
        ):
            raise InstallationError(
                "Operation context differs from captured path inputs."
            )
        from apprc.user_files.installation.validation import validate_snapshot

        validate_snapshot(
            inspection.snapshot, app_id=spec.app_id, context=operation_context
        )
        placement = operation_context.placement
        declared = {
            kind
            for kind, enabled in (
                ("config", spec.paths.config),
                ("appdata", spec.paths.appdata),
                ("cache", spec.paths.cache),
                ("state", spec.paths.state),
            )
            if enabled
        }
        if not declared.issubset(placement.capabilities):
            raise InstallationError(
                "Pending operation lacks a declared path capability."
            )
        return AppPaths(
            layout=placement.layout,
            source="installation",
            config_dir=placement.config_dir if spec.paths.config else None,
            appdata_dir=placement.appdata_dir if spec.paths.appdata else None,
            cache_dir=placement.cache_dir if spec.paths.cache else None,
            state_dir=placement.state_dir if spec.paths.state else None,
            logs_dir=placement.logs_dir if spec.paths.state else None,
            installation=inspection.snapshot,
        )
    if options.layout is not None:
        layout, source = options.layout, "invocation"
    else:
        explicit_layers = []
        for env_file in options.env_files:
            try:
                _, layers, _ = read_explicit_env_files(
                    (env_file,),
                    environment=environment,
                    excluded_env_keys=excluded_env_keys,
                    excluded_env_prefixes=excluded_env_prefixes,
                )
            except (FileNotFoundError, ExplicitEnvFileError):
                if not allow_unready:
                    raise
            else:
                explicit_layers.extend(layers)
        process = dict(environment)
        if options.env_file_overrides_os_environ:
            highest_to_lowest: list[Mapping[str, str]] = [
                *(layer.values for layer in reversed(explicit_layers)),
                process,
            ]
        else:
            highest_to_lowest = [
                process,
                *(layer.values for layer in reversed(explicit_layers)),
            ]
        selected: Mapping[str, str] | None = None
        for layer in highest_to_lowest:
            if (
                layer.get(layout_key, "").strip()
                or layer.get(root_key, "").strip()
            ):
                selected = layer
                break
        if selected is not None:
            raw_mode = selected.get(layout_key, "").strip()
            raw_root = selected.get(root_key, "").strip()
            if raw_mode and raw_mode not in {"native", "single-root"}:
                raise ValueError(f"Invalid {layout_key} value: {raw_mode!r}.")
            if raw_mode == "native" and raw_root:
                raise ValueError(
                    f"{layout_key}=native cannot be combined with {root_key}."
                )
            if raw_root:
                layout = Layout.single_root(raw_root)
            elif raw_mode == "single-root":
                raise ValueError(
                    f"{layout_key}=single-root requires {root_key}."
                )
            else:
                layout = Layout.native()
            source = "environment"
        elif inspection.status != "missing":
            record = inspection.require_usable()
            assert record is not None
            placement = record.placement
            capabilities = {
                kind
                for kind, enabled in (
                    ("config", spec.paths.config),
                    ("appdata", spec.paths.appdata),
                    ("cache", spec.paths.cache),
                    ("state", spec.paths.state),
                )
                if enabled
            }
            if not capabilities.issubset(placement.capabilities):
                raise InstallationError(
                    "New path capabilities require explicit installation reconciliation."
                )
            return AppPaths(
                layout=placement.layout,
                source="installation",
                config_dir=placement.config_dir if spec.paths.config else None,
                appdata_dir=placement.appdata_dir
                if spec.paths.appdata
                else None,
                cache_dir=placement.cache_dir if spec.paths.cache else None,
                state_dir=placement.state_dir if spec.paths.state else None,
                logs_dir=placement.logs_dir if spec.paths.state else None,
                installation=inspection.snapshot,
            )
        elif spec.layout is not None:
            layout, source = spec.layout, "declaration"
        else:
            layout, source = Layout.native(), "default"

    enabled = spec.paths
    if layout.mode == "single-root":
        assert layout.root is not None
        root = layout.root
        config_dir = root / "config" if enabled.config else None
        appdata_dir = root / "appdata" if enabled.appdata else None
        cache_dir = root / "cache" if enabled.cache else None
        state_dir = root / "state" if enabled.state else None
        logs_dir = state_dir / "logs" if state_dir is not None else None
    else:
        config_base, data_base, cache_base, state_base, logs_base = (
            native_user_directories(spec.app_id, environment=environment)
        )
        if enabled.appdata and sys.platform not in {"win32", "darwin"}:
            from apprc.user_files.installation.validation import (
                check_native_appdata_container,
            )

            check_native_appdata_container(data_base, app_id=spec.app_id)
        config_dir = config_base if enabled.config else None
        appdata_dir = data_base / "appdata" if enabled.appdata else None
        cache_dir = cache_base if enabled.cache else None
        state_dir = state_base if enabled.state else None
        logs_dir = logs_base if enabled.state else None

    return AppPaths(
        layout=layout,
        source=source,
        config_dir=config_dir,
        appdata_dir=appdata_dir,
        cache_dir=cache_dir,
        state_dir=state_dir,
        logs_dir=logs_dir,
        installation=inspection.snapshot,
    )
