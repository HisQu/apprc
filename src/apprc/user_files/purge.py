"""Exact removal of AppRC-managed configuration files."""

from __future__ import annotations

import stat
from hashlib import sha256
from pathlib import Path

from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.maintenance import RemovalPlan, RemovalResult
from apprc.definition.paths import AppPaths
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.ownership import inspect_ownership
from apprc.user_files.app_home.writes import file_revision
from apprc.user_files.env_files.secrets import secret_companion_path


def plan_config_purge(spec: AppConfigSpec, paths: AppPaths) -> RemovalPlan:
    """Plan deletion of only declared, known AppRC configuration files.

    :param spec: Configuration declaration.
    :param paths: Captured component locations.
    :return: Revision-bound exact file plan.
    """
    root = paths.require("config").expanduser().absolute()
    owner = inspect_ownership(root, spec.app_id, "config")
    if owner == "missing":
        return RemovalPlan("config", root, (), _revision(root, ()))
    if owner != "owned" and any(root.iterdir()):
        raise ValueError(f"Refusing to purge unowned AppRC config: {root}")
    names = [spec.user_dotenv_filename, spec.apprc_toml_filename]
    known = tuple(
        dict.fromkeys(
            path
            for name in names
            for path in (root / name, secret_companion_path(root / name))
        )
    )
    existing: list[Path] = []
    for path in known:
        assert_no_links(path)
        if path.is_symlink():
            raise ValueError(f"Refusing to purge linked managed file: {path}")
        if path.exists():
            if not path.is_file():
                raise ValueError(f"Unsupported managed config entry: {path}")
            existing.append(path)
    marker = root / ".apprc-owner.json"
    if owner == "owned":
        existing.append(marker)
    retained = tuple(
        sorted(path for path in root.iterdir() if path not in existing)
    )
    warnings = (
        ("Unknown configuration contents retained; purge is partial.",)
        if retained
        else ()
    )
    if not retained:
        existing.append(root)
    targets = tuple(existing)
    return RemovalPlan(
        "config", root, targets, _revision(root, targets), warnings
    )


def apply_config_purge(
    plan: RemovalPlan, spec: AppConfigSpec, paths: AppPaths
) -> RemovalResult:
    """Recheck the full managed-file inventory and delete under caller lock.

    :param plan: Previously planned config removal.
    :param spec: Configuration declaration.
    :param paths: Captured component locations.
    :return: Removed paths; unknown contents remain untouched.
    """
    current = plan_config_purge(spec, paths)
    if current != plan:
        raise ValueError(f"Configuration purge plan is stale for {plan.root}")
    removed: list[Path] = []
    for path in plan.targets:
        assert_no_links(path)
        if path == plan.root:
            path.rmdir()
        else:
            path.unlink()
        removed.append(path)
    retained = tuple(sorted(plan.root.iterdir())) if plan.root.exists() else ()
    return RemovalResult(
        tuple(removed), skipped=retained, warnings=plan.warnings
    )


def _revision(root: Path, targets: tuple[Path, ...]) -> str:
    digest = sha256()
    inventory = set(targets)
    if root.exists():
        inventory.add(root)
        inventory.update(root.iterdir())
    for path in sorted(
        inventory, key=lambda item: item.relative_to(root).as_posix()
    ):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        digest.update(f"{relative}\0{identity!r}\n".encode())
        if stat.S_ISREG(metadata.st_mode) and path in targets:
            digest.update((file_revision(path) or "<missing>").encode())
    marker = root / ".apprc-owner.json"
    if marker not in targets:
        digest.update((file_revision(marker) or "<missing>").encode())
    return digest.hexdigest()
