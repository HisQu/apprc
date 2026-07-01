"""Storage registry records used by AppRC multi-storage mode."""

from __future__ import annotations

# == Standard Library ========================
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageRecord:
    """One named storage root from the multi-storage registry.

    :param name: Stable storage selector used by ``--storage``.
    :param root: Root directory that owns user data and ``.env.apprc-storage``.
    """

    name: str
    root: Path


@dataclass(frozen=True, slots=True)
class ArchivedStorageRecord:
    """Last known archive for one storage selector.

    Archive records are restore conveniences only. Runtime bootstrap still
    selects live :class:`StorageRecord` entries from ``storages``.

    :param name: Storage selector the archive was last associated with.
    :param archive: Archive path last written by the editor.
    :param source_root: Source directory that was compressed into the archive.
    """

    name: str
    archive: Path
    source_root: Path


@dataclass(frozen=True, slots=True)
class StorageRegistry:
    """Parsed storage registry.

    :param path: AppRC TOML location.
    :param storages: Named live storage roots by selector.
    :param archived_storages: Last known archive paths by selector.
    """

    path: Path
    storages: Mapping[str, StorageRecord]
    archived_storages: Mapping[str, ArchivedStorageRecord] = field(
        default_factory=dict
    )

    def selected(self, name: str) -> StorageRecord:
        """Return one named storage or raise a readable error.

        :param name: Storage selector requested by CLI or config.
        :return: Matching storage record.
        :raises ValueError: If the storage does not exist.
        """
        try:
            return self.storages[name]
        except KeyError as exc:
            known = ", ".join(sorted(self.storages)) or "<none>"
            raise ValueError(
                f"Unknown storage {name!r} in {self.path}. "
                f"Known storages: {known}."
            ) from exc
