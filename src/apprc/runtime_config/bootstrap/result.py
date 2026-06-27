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

    :param shared_env: Packaged shared dotenv path loaded into the process, or
        ``None`` when dotenv layers were skipped.
    :param storage_env: Active storage dotenv candidate considered during
        loading, or ``None`` when dotenv layers were skipped or no storage root
        is known. The path may not exist because missing storage files are
        optional.
    :param config_home: AppRC-managed per-user config directory.
    :param app_wide_env: App-wide dotenv override file considered during
        loading, or ``None`` when dotenv layers were skipped.
    :param env_files: Explicit dotenv files passed through the CLI or Python API.
    :param index_path: Named-storage index path.
    :param storage_selector_source: Source that selected the active storage,
        such as ``--storage`` or the app-specific storage env key.
    :param storage_selector_value: Selector value before it was resolved to a
        concrete storage root.
    :param storage_name: Named storage selected for this bootstrap when the
        selector matched an AppRC TOML entry.
    :param storage_root: Active storage root, when known.
    :param storage_count: Number of loaded named storages.
    """

    shared_env: Path | None
    storage_env: Path | None
    env_files: tuple[Path, ...]
    index_path: Path | None
    storage_selector_source: str | None
    storage_selector_value: str | None
    storage_name: str | None
    storage_root: Path | None
    storage_count: int
    config_home: Path | None = None
    app_wide_env: Path | None = None
