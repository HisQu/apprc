"""Bootstrap result objects shared by CLI and runtime config setup."""

from __future__ import annotations

# == Standard Library ========================
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol


class BootstrapLogger(Protocol):
    """Logger interface needed for bootstrap status messages."""

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> Any:
        """Emit one informational message."""


@dataclass(frozen=True, slots=True)
class EnvBootstrapResult:
    """Files and storage selected during CLI env bootstrap.

    :param defaults_dotenv: Packaged defaults dotenv path loaded into the
        process, or ``None`` when dotenv layers were skipped.
    :param storage_dotenv: Active storage dotenv candidate considered during
        loading, or ``None`` when dotenv layers were skipped or no storage root
        is known. Runtime bootstrap requires this file before selecting a
        storage.
    :param apprc_dir: AppRC-managed per-user config directory.
    :param user_dotenv: Per-user dotenv override file considered during
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
    :param storage_selector_kind: Whether the active selector was a name or
        filesystem path.
    """

    defaults_dotenv: Path | None
    storage_dotenv: Path | None
    env_files: tuple[Path, ...]
    apprc_toml: Path | None
    storage_selector_source: str | None
    storage_selector_value: str | None
    storage_name: str | None
    storage_root: Path | None
    storage_count: int
    apprc_dir: Path | None = None
    user_dotenv: Path | None = None
    storage_selector_kind: Literal["name", "path"] | None = None
