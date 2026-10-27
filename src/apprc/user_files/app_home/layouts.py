"""Resolve declared application locations without touching the filesystem."""

from __future__ import annotations

import os
import sys
from collections.abc import Collection, Mapping
from pathlib import Path

from platformdirs import PlatformDirs

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.paths import AppPaths, Layout
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
    :param allow_unready: Skip unreadable explicit files for diagnostic inspection.
    :return: Absolute paths for enabled components only.
    """
    layout_key, root_key = spec.layout_env_key, spec.root_env_key
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
        dirs = PlatformDirs(
            appname=spec.app_id,
            appauthor=False,
            roaming=False,
            ensure_exists=False,
        )
        config_base = dirs.user_config_path if enabled.config else None
        appdata_base = dirs.user_data_path if enabled.appdata else None
        cache_base = dirs.user_cache_path if enabled.cache else None
        state_base = dirs.user_state_path if enabled.state else None
        logs_base = dirs.user_log_path if enabled.state else None
        if sys.platform in {"win32", "darwin"}:
            config_dir = (
                Path(os.path.abspath(Path(config_base) / "config"))
                if config_base is not None
                else None
            )
            appdata_dir = (
                Path(os.path.abspath(Path(appdata_base) / "appdata"))
                if appdata_base is not None
                else None
            )
            state_dir = (
                Path(os.path.abspath(Path(state_base) / "state"))
                if state_base is not None
                else None
            )
        else:
            config_dir = (
                Path(os.path.abspath(config_base))
                if config_base is not None
                else None
            )
            appdata_dir = (
                Path(os.path.abspath(appdata_base))
                if appdata_base is not None
                else None
            )
            state_dir = (
                Path(os.path.abspath(state_base))
                if state_base is not None
                else None
            )
        cache_dir = (
            Path(os.path.abspath(cache_base))
            if cache_base is not None
            else None
        )
        logs_dir = (
            Path(os.path.abspath(logs_base)) if logs_base is not None else None
        )

    return AppPaths(
        layout=layout,
        source=source,
        config_dir=config_dir,
        appdata_dir=appdata_dir,
        cache_dir=cache_dir,
        state_dir=state_dir,
        logs_dir=logs_dir,
    )
