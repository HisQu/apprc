"""Ownership markers for safely created application path components."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from apprc.definition.installation import (
    InstallationWriteAuthority,
    OperationContext,
)
from apprc.definition.paths import AppPaths, PathKind, ResourceKind
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_text_atomic,
)
from apprc.user_files.app_home.permissions import (
    create_private_directory_if_missing,
)
from apprc.user_files.app_home.writes import managed_write_lock

if TYPE_CHECKING:
    from apprc.definition.app_config.spec import AppConfigSpec

_MARKER = ".apprc-owner.json"


def inspect_ownership(root: Path, app_id: str, category: ResourceKind) -> str:
    """Classify a category root, rejecting malformed or mismatched markers.

    :param root: Captured component root.
    :param app_id: Stable owning application identity.
    :param category: Resource category expected at the root.
    :return: ``missing``, ``owned``, or ``unowned``.
    :raises ValueError: If the root traverses a link or its marker is unsafe.
    """
    root = root.expanduser().absolute()
    assert_no_links(root)
    if not root.exists():
        return "missing"
    if not root.is_dir():
        raise ValueError(f"AppRC path is not a directory: {root}")
    marker = root / _MARKER
    assert_no_links(marker)
    if not marker.exists():
        return "unowned"
    if not marker.is_file():
        raise ValueError(f"Invalid AppRC ownership marker: {marker}")
    try:
        value = json.loads(
            marker.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_marker_fields,
        )
        if (
            type(value) is not dict
            or type(value.get("schema_version")) is not int
        ):
            raise ValueError("Invalid AppRC ownership marker fields.")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Invalid AppRC ownership marker: {marker}") from exc
    expected = {"schema_version": 1, "app_id": app_id, "category": category}
    if value != expected:
        raise ValueError(f"Mismatched AppRC ownership marker: {marker}")
    return "owned"


def ensure_owned_path(
    spec: AppConfigSpec,
    paths: AppPaths,
    kind: PathKind,
    *,
    adopt: bool = False,
    context: OperationContext | None = None,
) -> Path:
    """Create and mark one captured component after strict boundary checks.

    :param spec: Application declaration owning the path.
    :param paths: Previously captured component paths.
    :param kind: Component to initialize.
    :param adopt: Explicitly allow adoption of a nonempty unowned directory.
    :return: Initialized component root.
    :raises ValueError: If roots overlap, links occur, or ownership is unsafe.
    """
    validate_category_root_boundaries(spec, paths)
    root = paths.require(kind).expanduser().absolute()
    category: ResourceKind = "state" if kind == "logs" else kind
    if kind == "logs" and paths.state_dir is not None:
        state_root = paths.state_dir.expanduser().absolute()
        if root != state_root and root.is_relative_to(state_root):
            ensure_owned_path(
                spec, paths, "state", adopt=adopt, context=context
            )
            assert_no_links(root)
            with managed_write_lock(
                root,
                authority=InstallationWriteAuthority(
                    spec.app_id, paths.installation, context
                ),
            ):
                assert_no_links(root)
                create_private_directory_if_missing(root)
            return root
    assert_no_links(root)
    with managed_write_lock(
        root,
        authority=InstallationWriteAuthority(
            spec.app_id, paths.installation, context
        ),
    ):
        assert_no_links(root)
        create_private_directory_if_missing(root)
        assert_no_links(root)
        ownership = inspect_ownership(root, spec.app_id, category)
        marker = root / _MARKER
        if ownership == "owned":
            return root
        if ownership == "unowned" and any(root.iterdir()) and not adopt:
            raise ValueError(f"Refusing nonempty unowned AppRC path: {root}")
        write_text_atomic(
            marker,
            json.dumps(
                {
                    "schema_version": 1,
                    "app_id": spec.app_id,
                    "category": category,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            private=False,
        )
    return root


def _category_roots(
    paths: AppPaths, category: ResourceKind
) -> tuple[Path, ...]:
    if category == "state":
        values = (paths.state_dir, paths.logs_dir)
    elif category == "config":
        values = (paths.config_dir,)
    elif category == "appdata":
        values = (paths.appdata_dir,)
    else:
        values = (paths.cache_dir,)
    return tuple(
        dict.fromkeys(
            p.expanduser().absolute() for p in values if p is not None
        )
    )


def validate_category_root_boundaries(
    spec: AppConfigSpec,
    paths: AppPaths,
) -> None:
    """Reject overlapping captured roots from distinct enabled categories.

    Nested state/log roots are one category and are allowed; all cross-category
    overlap is rejected before a provider can inspect or mutate either root.

    :param spec: Declaration determining which categories are enabled.
    :param paths: Captured absolute roots to validate.
    :raises ValueError: If enabled category roots overlap or traverse links.
    """
    enabled: tuple[tuple[ResourceKind, bool], ...] = (
        ("config", spec.paths.config),
        ("appdata", spec.paths.appdata),
        ("cache", spec.paths.cache),
        ("state", spec.paths.state),
    )
    roots: list[tuple[ResourceKind, Path]] = []
    for category, is_enabled in enabled:
        if not is_enabled:
            continue
        paths.require(category)
        for root in _category_roots(paths, category):
            assert_no_links(root)
            if _overlap(root, paths.installation.directory):
                raise ValueError(
                    "AppRC resource root overlaps durable installation metadata."
                )
            roots.append((category, root))
    for index, (category, root) in enumerate(roots):
        for other_category, other_root in roots[index + 1 :]:
            if category != other_category and _overlap(root, other_root):
                raise ValueError(
                    f"AppRC category roots overlap: {root} and {other_root}"
                )


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _unique_marker_fields(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject duplicate JSON object keys in ownership markers."""
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate AppRC ownership marker field.")
        values[key] = value
    return values
