"""Exact, revision-bound inventories for AppRC-owned directory removal."""

from __future__ import annotations

import stat
from hashlib import sha256
from pathlib import Path

from apprc.definition.maintenance import RemovalPlan, RemovalResult
from apprc.definition.paths import ResourceKind
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.ownership import inspect_ownership
from apprc.user_files.app_home.writes import file_revision

_MARKER = ".apprc-owner.json"


def plan_removal(
    category: ResourceKind, root: Path, app_id: str
) -> RemovalPlan:
    """Plan only empty roots and ownership markers without payload authority.

    :param category: Owned resource category.
    :param root: Category root to inspect.
    :param app_id: Expected application owner.
    :return: Exact paths and a manifest revision.
    """
    root = root.expanduser().absolute()
    ownership = inspect_ownership(root, app_id, category)
    if ownership == "missing":
        return RemovalPlan(category, root, (), _revision(root, ()))
    targets: list[Path] = []
    for path in sorted(root.iterdir()):
        assert_no_links(path)
        if ownership != "owned" or path.name != _MARKER:
            raise ValueError(
                f"Purging unsupported payload requires an application provider: {path}"
            )
        targets.append(path)
    targets.append(root)
    revision = _revision(root, targets)
    return RemovalPlan(category, root, tuple(targets), revision)


def validate_removal_plan(plan: RemovalPlan, app_id: str) -> None:
    """Reject stale plans, links, outside targets, and unknown descendants.

    :param plan: Previously captured inventory.
    :param app_id: Expected root owner.
    :raises ValueError: If the plan or filesystem changed after planning.
    """
    current = plan_removal(plan.category, plan.root, app_id)
    if current.targets != plan.targets or current.revision != plan.revision:
        raise ValueError(f"Removal plan is stale for {plan.root}")


def apply_removal(plan: RemovalPlan, app_id: str) -> RemovalResult:
    """Remove an exact complete inventory, bottom-up, after freshness checks.

    :param plan: Exact plan from :func:`plan_removal`.
    :param app_id: Expected root owner.
    :return: Paths actually removed.
    """
    validate_removal_plan(plan, app_id)
    removed: list[Path] = []
    for path in sorted(plan.targets, key=lambda p: len(p.parts), reverse=True):
        assert_no_links(path)
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()
        removed.append(path)
    return RemovalResult(tuple(removed))


def _revision(root: Path, targets: tuple[Path, ...] | list[Path]) -> str:
    digest = sha256()
    marker = root / _MARKER
    marker_rev = file_revision(marker)
    digest.update(f"marker:{marker_rev}\n".encode())
    for target in sorted(targets, key=lambda p: p.relative_to(root).as_posix()):
        relative = target.relative_to(root).as_posix()
        metadata = target.lstat()
        identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        digest.update(f"{relative}\0{identity!r}\n".encode())
        if stat.S_ISREG(metadata.st_mode) and target.stat().st_size <= 65536:
            revision = file_revision(target)
            digest.update(f"content:{revision}\n".encode())
    return digest.hexdigest()
