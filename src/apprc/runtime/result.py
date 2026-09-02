"""Bootstrap result objects shared by CLI and runtime config setup."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class BootstrapLogger(Protocol):
    """Logger interface needed for bootstrap status messages."""

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> Any:
        """Emit one informational message."""


@dataclass(frozen=True, slots=True)
class EnvBootstrapResult:
    """Files and storage selected during CLI env bootstrap.

    :param defaults_env: Packaged defaults dotenv path loaded into the process, or
        ``None`` when dotenv layers were skipped.
    :param storage_env: Active storage dotenv candidate considered during
        loading, or ``None`` when dotenv layers were skipped or no storage root
        is known. The path may not exist because missing storage files are
        optional.
    :param config_home: AppRC-managed per-user config directory.
    :param app_env: Per-user app dotenv override file considered during
        loading, or ``None`` when dotenv layers were skipped.
    :param env_files: Explicit dotenv files passed through the CLI or Python API.
    :param apprc_toml: AppRC TOML path.
    :param storage_selector_source: Source that selected the active storage,
        such as ``--storage`` or the app-specific storage env key.
    :param storage_selector_value: Selector value before it was resolved to a
        concrete storage root.
    :param storage_name: Named storage selected for this bootstrap when the
        selector matched an AppRC TOML entry.
    :param storage_root: Active storage root, when known.
    :param storage_count: Number of loaded named storages.
    """

    defaults_env: Path | None
    storage_env: Path | None
    env_files: tuple[Path, ...]
    apprc_toml: Path | None
    storage_selector_source: str | None
    storage_selector_value: str | None
    storage_name: str | None
    storage_root: Path | None
    storage_count: int
    config_home: Path | None = None
    app_env: Path | None = None

    @property
    def shared_env(self) -> Path | None:
        """Return ``defaults_env`` through the deprecated 0.19 name."""
        return self.defaults_env

    @property
    def index_path(self) -> Path | None:
        """Return ``apprc_toml`` through the deprecated 0.19 name."""
        return self.apprc_toml

    @property
    def app_wide_env(self) -> Path | None:
        """Return ``app_env`` through the deprecated 0.19 name."""
        return self.app_env
