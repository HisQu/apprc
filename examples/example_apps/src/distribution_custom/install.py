"""Example repository-owned install ordering through public lifecycle primitives."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from apprc.distribution import (
    DistributionSpec,
    PreparedProject,
    build_project_snapshot,
)


def prepare_project_release(
    spec: DistributionSpec,
    *,
    revision: str,
    destination: Path,
    prepare_project: Callable[[Path], None],
) -> PreparedProject:
    """Run repository-owned build preparation only on a private committed copy.

    Runtime initialization belongs in the application's declared
    ``InstallationHooks.initialize`` callback, not in the source acquisition
    or dependency synchronization path.

    :param spec: Authored application declaration matching committed metadata.
    :param revision: Git revision resolved once by the snapshot builder.
    :param destination: New deterministic project ZIP destination.
    :param prepare_project: Build action receiving only the private stage root.
    :return: Verified project archive and immutable snapshot identity.
    """
    return build_project_snapshot(
        spec,
        revision=revision,
        destination=destination,
        prepare=prepare_project,
    )
