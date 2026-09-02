"""Resolve preferred and legacy AppRC-managed filenames."""

from __future__ import annotations

# == Standard Library ============================================
import warnings
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ManagedFileResolution:
    """Selected path for one managed file.

    :param preferred: Path defined by the current AppRC convention.
    :param selected: Path used for reads and writes.
    :param legacy_candidates: Older paths considered in priority order.
    :param conflicts: Existing older paths ignored because ``preferred`` wins.
    """

    preferred: Path
    selected: Path
    legacy_candidates: tuple[Path, ...]
    conflicts: tuple[Path, ...]

    @property
    def uses_legacy_path(self) -> bool:
        """Return whether the selected path uses an older convention."""
        return self.selected != self.preferred


def resolve_managed_file(
    *,
    preferred: Path,
    legacy_candidates: tuple[Path, ...] = (),
    label: str,
) -> ManagedFileResolution:
    """Choose one file without merging competing configurations.

    The current filename wins when it exists. Otherwise, the first existing
    legacy path stays active until the user runs explicit migration.

    :param preferred: Path defined by the current convention.
    :param legacy_candidates: Older paths ordered from newest to oldest.
    :param label: Human-readable resource name used in conflict warnings.
    :return: Deterministic read/write selection and conflict information.
    """
    existing_legacy = tuple(
        candidate for candidate in legacy_candidates if candidate.is_file()
    )
    if path_entry_exists(preferred):
        if existing_legacy:
            joined = ", ".join(str(path) for path in existing_legacy)
            warnings.warn(
                f"Both current and legacy {label} files exist. AppRC uses "
                f"{preferred} and ignores: {joined}. Run `config migrate` "
                "after resolving the conflict.",
                RuntimeWarning,
                stacklevel=2,
            )
        return ManagedFileResolution(
            preferred=preferred,
            selected=preferred,
            legacy_candidates=legacy_candidates,
            conflicts=existing_legacy,
        )
    selected = existing_legacy[0] if existing_legacy else preferred
    conflicts = existing_legacy[1:]
    if conflicts:
        joined = ", ".join(str(path) for path in conflicts)
        warnings.warn(
            f"Multiple legacy {label} files exist. AppRC uses {selected} "
            f"and ignores: {joined}. Run `config migrate` after resolving "
            "the conflict.",
            RuntimeWarning,
            stacklevel=2,
        )
    return ManagedFileResolution(
        preferred=preferred,
        selected=selected,
        legacy_candidates=legacy_candidates,
        conflicts=conflicts,
    )


def path_entry_exists(path: Path) -> bool:
    """Return whether a path is occupied, including by a dangling symlink.

    :param path: Filesystem entry to inspect.
    :return: Whether the path is occupied.
    """
    return path.exists() or path.is_symlink()
