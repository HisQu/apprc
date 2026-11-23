"""Initialization and rollback of installer-managed resource roots."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    InstallationPlacement,
    InstallationWriteAuthority,
    InstallPlan,
    OperationContext,
    RuntimeSlot,
)
from apprc.definition.paths import ResourceKind
from apprc.distribution.runtime._install_progress import report
from apprc.distribution.runtime.probe import application_bridge
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.writes import (
    file_revision,
    managed_lock_path,
    managed_write_lock,
)

if TYPE_CHECKING:
    from apprc.services.installation import InstallationManager

_OWNER_MARKER = ".apprc-owner.json"


@dataclass(frozen=True, slots=True)
class _ResourceBeforeImage:
    """The directory and ownership evidence captured before initialization."""

    root: Path
    category: ResourceKind | None
    existed: bool
    marker_revision: str | None


type ResourceSnapshot = tuple[_ResourceBeforeImage, ...]


def _resource_directories(
    placement: InstallationPlacement,
) -> dict[ResourceKind, Path | None]:
    """List primary resource directories in initialization and reporting order."""
    return {
        "config": placement.config_dir,
        "appdata": placement.appdata_dir,
        "cache": placement.cache_dir,
        "state": placement.state_dir,
    }


def _validate_selected_resource_ownership(
    identity: InstallationIdentity,
    placement: InstallationPlacement,
) -> None:
    """Require installed ownership evidence for every selected resource root."""
    from apprc.user_files.app_home.ownership import inspect_ownership

    for category, root in _resource_directories(placement).items():
        if category not in placement.capabilities:
            continue
        if root is None:
            raise InstallationError(
                f"Selected {category} resource has no recorded root."
            )
        try:
            ownership = inspect_ownership(root, identity.app_id, category)
        except (OSError, ValueError) as error:
            raise InstallationError(
                f"Selected {category} resource root is unsafe."
            ) from error
        if ownership != "owned":
            raise InstallationError(
                f"Selected {category} resource root has no valid ownership marker."
            )
    logs = placement.logs_dir
    state = placement.state_dir
    if logs is not None and (
        state is None
        or not Path(os.path.normcase(str(logs.absolute()))).is_relative_to(
            Path(os.path.normcase(str(state.absolute())))
        )
    ):
        try:
            ownership = inspect_ownership(logs, identity.app_id, "state")
        except (OSError, ValueError) as error:
            raise InstallationError(
                "Selected logs resource root is unsafe."
            ) from error
        if ownership != "owned":
            raise InstallationError(
                "Selected logs resource root has no valid ownership marker."
            )


def initialize_resources(
    manager: InstallationManager,
    identity: InstallationIdentity,
    runtime: RuntimeSlot | EditableCheckout,
    command_name: str,
    context: OperationContext,
    *,
    expected_revision: str,
    manager_executable: Path | None,
    expected_observations: dict[str, object],
) -> tuple[Path, ...]:
    """Initialize resources and verify their placement and ownership."""
    hooks = runtime.hooks
    if identity.apprc_reference is None:
        if any(
            reference is not None
            for reference in (
                hooks.initialize,
                hooks.inventory,
                hooks.cleanup,
                hooks.migrate,
            )
        ):
            raise InstallationError(
                "Lifecycle hooks require an AppRC declaration."
            )
        initialized = manager.initialize(context=context)
        _validate_selected_resource_ownership(identity, context.placement)
        return initialized.paths
    result = application_bridge(
        manager.directory,
        identity,
        runtime,
        command_name=command_name,
        action="initialize",
        environment=dict(manager.environment),
        manager_executable=manager_executable,
        expected_revision=expected_revision,
        operation_context=context,
    )
    observation_fields = {
        "distribution",
        "version",
        "prefix",
        "interpreter",
        "python_version",
        "commands",
    }
    if (
        set(expected_observations) != observation_fields
        or not isinstance(result, dict)
        or set(result) != observation_fields | {"capabilities", "paths"}
        or any(
            result[field] != expected_observations[field]
            for field in observation_fields
        )
    ):
        raise InstallationError(
            "Initialization observations differ from the validated runtime probe."
        )
    capabilities = result["capabilities"]
    capability_names = {"config", "appdata", "cache", "state"}
    if (
        not isinstance(capabilities, dict)
        or set(capabilities) != capability_names
        or any(type(enabled) is not bool for enabled in capabilities.values())
    ):
        raise InstallationError(
            "Initialization returned invalid resource capabilities."
        )
    enabled = {name for name, value in capabilities.items() if value}
    if not enabled.issubset(context.placement.capabilities):
        raise InstallationError(
            "Initialized resource capabilities exceed the selected placement."
        )
    paths = result["paths"]
    if not isinstance(paths, list) or any(
        not isinstance(path, str) for path in paths
    ):
        raise InstallationError(
            "Initialization returned invalid resource paths."
        )
    resource_paths = _resource_directories(context.placement)
    if any(
        enabled_name and resource_paths[name] is None
        for name, enabled_name in capabilities.items()
    ):
        raise InstallationError(
            "Initialized capability has no selected resource path."
        )
    expected_paths = [
        str(root) for name, root in resource_paths.items() if capabilities[name]
    ]
    if capabilities["state"] and context.placement.logs_dir is not None:
        expected_paths.append(str(context.placement.logs_dir))
    if paths != expected_paths:
        raise InstallationError(
            "Initialized resource paths differ from the selected placement."
        )
    _validate_selected_resource_ownership(identity, context.placement)
    return tuple(Path(path) for path in paths)


def capture_resource_snapshot(
    placement: InstallationPlacement,
) -> ResourceSnapshot:
    """Capture SDK resource existence before an installation initializes them.

    :param placement: Validated intended resource locations.
    :return: Roots, marker categories, prior existence and marker revisions.
    """
    roots: list[tuple[ResourceKind | None, Path | None]] = list(
        _resource_directories(placement).items()
    )
    if "state" in placement.capabilities and placement.logs_dir is not None:
        state = placement.state_dir
        logs = placement.logs_dir
        category: ResourceKind | None = (
            None
            if state is not None and logs.is_relative_to(state)
            else "state"
        )
        roots.append((category, logs))
    captured: dict[Path, _ResourceBeforeImage] = {}
    for category, root in roots:
        if root is None or (
            category is not None and category not in placement.capabilities
        ):
            continue
        assert_no_links(root)
        captured.setdefault(
            root,
            _ResourceBeforeImage(
                root=root,
                category=category,
                existed=root.exists(),
                marker_revision=file_revision(root / _OWNER_MARKER),
            ),
        )
    return tuple(captured.values())


def report_resources(
    snapshot: ResourceSnapshot, initialized: tuple[Path, ...]
) -> None:
    """Report whether each initialized resource already existed."""
    labels: dict[ResourceKind | None, str] = {
        "config": "Configuration",
        "appdata": "Application data",
        "cache": "Cache",
        "state": "State",
        None: "Logs",
    }
    for resource in snapshot:
        if resource.root in initialized:
            status = "EXISTING" if resource.existed else "CREATED"
            report("result", labels[resource.category], status, resource.root)


def rollback_resources(
    manager: InstallationManager,
    plan: InstallPlan,
    inspection: InstallationInspection,
    resources: ResourceSnapshot,
) -> None:
    """Remove only new SDK markers and empty directories, preserving payload.

    :param manager: Installation whose namespace is locked by the caller.
    :param plan: Pending operation authorizing resource lock acquisition.
    :param inspection: Current pending authority snapshot.
    :param resources: Existence captured before initialization.
    """
    from apprc.user_files.app_home.ownership import inspect_ownership

    changed = tuple(
        resource
        for resource in resources
        if (not resource.existed and resource.root.exists())
        or file_revision(resource.root / _OWNER_MARKER)
        != resource.marker_revision
    )
    if not changed:
        return
    context = OperationContext(
        manager.directory,
        plan.operation_id,
        plan.generation_id,
        plan.target.placement,
    )
    controls = {managed_lock_path(resource.root) for resource in resources}
    with managed_write_lock(
        *(resource.root for resource in changed),
        authority=InstallationWriteAuthority(
            manager.spec.app_id, inspection.snapshot, context
        ),
    ):
        for resource in sorted(
            changed, key=lambda resource: len(resource.root.parts), reverse=True
        ):
            root = resource.root
            assert_no_links(root)
            marker = root / _OWNER_MARKER
            actual_marker = file_revision(marker)
            if resource.marker_revision is not None:
                if actual_marker != resource.marker_revision:
                    raise InstallationError(
                        f"Resource ownership changed during installation: {root}."
                    )
                continue
            if actual_marker is not None:
                if (
                    resource.category is None
                    or inspect_ownership(
                        root, manager.spec.app_id, resource.category
                    )
                    != "owned"
                ):
                    raise InstallationError(
                        f"Resource ownership cannot be rolled back: {root}."
                    )
                payload = tuple(
                    path for path in root.iterdir() if path != marker
                )
                if payload and all(
                    path in controls
                    and path.is_file()
                    and not path.is_symlink()
                    for path in payload
                ):
                    # > Stable subordinate locks may still be open on Windows.
                    # > Keep their owned container so a fresh retry can reuse it.
                    continue
                if payload:
                    raise InstallationError(
                        f"New resource contains application or unknown data: {root}."
                    )
                marker.unlink()
            if not resource.existed and root.exists():
                root.rmdir()
