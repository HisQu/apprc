"""Pure safety boundaries for intended placement and exact cleanup inventories."""

from pathlib import Path

from apprc.definition.installation import (
    CleanupInventory,
    InstallationError,
    InstallationPlacement,
)
from apprc.definition.paths import ResourceKind
from apprc.user_files.app_home.locations import assert_no_links


def resource_roots(
    placement: InstallationPlacement,
) -> tuple[tuple[ResourceKind, Path], ...]:
    """Enumerate enabled/retired owned addresses without assuming capabilities.

    :param placement: Saved or explicitly intended placement.
    :return: Unique category/address pairs, including subordinate logs.
    """
    roots: list[tuple[ResourceKind, Path]] = []
    resources: tuple[tuple[ResourceKind, Path | None], ...] = (
        ("config", placement.config_dir),
        ("appdata", placement.appdata_dir),
        ("cache", placement.cache_dir),
        ("state", placement.state_dir),
        ("state", placement.logs_dir),
    )
    for kind, path in resources:
        if path is not None:
            roots.append((kind, path))
    roots.extend(
        (resource.kind, resource.path) for resource in placement.retired
    )
    return tuple(dict.fromkeys(roots))


def validate_placement(
    placement: InstallationPlacement, *, directory: Path
) -> None:
    """Keep installation out of every purge root and distinct resources separate.

    :param placement: Explicit resource addresses.
    :param directory: Durable installation namespace, never a data capability.
    """
    roots = resource_roots(placement)
    for index, (kind, path) in enumerate(roots):
        assert_no_links(path)
        if (
            directory == path
            or directory.is_relative_to(path)
            or path.is_relative_to(directory)
        ):
            raise InstallationError(
                "Installation metadata overlaps a resource root."
            )
        for other_kind, other in roots[index + 1 :]:
            if kind != other_kind and (
                path == other
                or path.is_relative_to(other)
                or other.is_relative_to(path)
            ):
                raise InstallationError("Resource categories must not overlap.")


def validate_cleanup(
    inventory: CleanupInventory,
    *,
    placement: InstallationPlacement,
    directory: Path,
    categories: frozenset[ResourceKind],
    complete: bool,
    forget_retained: bool,
) -> None:
    """Reject invented ownership and silent forgetting before removal consent.

    :param inventory: Exact provider/owner enumeration.
    :param placement: Previously saved ownership roots.
    :param directory: Support namespace.
    :param categories: Expressly selected data categories.
    :param complete: Whether authority retirement is intended.
    :param forget_retained: Whether named retained roots may become unmanaged.
    """
    roots = resource_roots(placement)
    seen: set[Path] = set()
    for entry in (*inventory.entries, *inventory.retained):
        assert_no_links(entry.path)
        if not entry.path.is_absolute() or entry.path in seen:
            raise InstallationError(
                "Cleanup paths must be absolute and unique."
            )
        seen.add(entry.path)
        if entry.resource is None:
            if (
                not entry.path.is_relative_to(directory)
                or entry.path == directory
                or entry.path == directory / "installation.json"
                or entry.path.is_relative_to(directory / "locks")
            ):
                raise InstallationError(
                    "Support cleanup cannot target authority, locks or external data."
                )
        elif not any(
            kind == entry.resource
            and (entry.path == root or entry.path.is_relative_to(root))
            for kind, root in roots
        ):
            raise InstallationError(
                "Cleanup target lies outside recorded resource ownership."
            )
        if (
            entry in inventory.entries
            and entry.resource is not None
            and entry.resource not in categories
        ):
            raise InstallationError(
                "Cleanup includes a resource category not selected for removal."
            )
    if complete:
        for kind, root in roots:
            if kind not in categories:
                if not forget_retained or not any(
                    entry.path == root for entry in inventory.retained
                ):
                    raise InstallationError(
                        "Complete removal must select every tracked root or explicitly name it as forgotten."
                    )
            if (
                root.exists()
                and not any(entry.path == root for entry in inventory.entries)
                and not (
                    forget_retained
                    and any(entry.path == root for entry in inventory.retained)
                )
            ):
                raise InstallationError(
                    "Cleanup inventory omits an existing tracked resource root."
                )
