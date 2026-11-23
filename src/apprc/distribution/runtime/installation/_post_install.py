"""Optional setup and shortcuts offered after runtime installation."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from apprc.definition.installation import (
    InstallationError,
    InstallationIdentity,
    InstallationInspection,
    OwnedOutput,
    RuntimeSlot,
)
from apprc.distribution.runtime._install_progress import report, warn
from apprc.distribution.runtime._leases import (
    RuntimeLease,
    acquire_runtime_lease,
)
from apprc.distribution.runtime.backend import (
    runtime_command,
    runtime_environment,
    runtime_prefix,
)
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation

if TYPE_CHECKING:
    from apprc.definition.resolution import CliRuntimeOptionsProtocol
    from apprc.services.installation import InstallationManager

LOG = logging.getLogger(__name__)


def offer_configuration_setup(
    inspection: InstallationInspection,
    *,
    skip: bool,
    config_group_name: str = "config",
    runtime_options: CliRuntimeOptionsProtocol | None = None,
    environment: Mapping[str, str] | None = None,
    input_stream: TextIO | None = None,
    raise_on_failure: bool = False,
) -> bool:
    """Dispatch conditional configuration setup through the ready runtime.

    The application runtime owns field eligibility and user confirmation.
    Skipped and noninteractive invocations do not launch another process.

    :param inspection: Captured ready installation authority.
    :param skip: Whether the caller explicitly skipped optional setup.
    :param config_group_name: Mounted configuration command group.
    :param runtime_options: Captured selectors, using the recorded layout.
    :param environment: Captured invocation environment, or the current one.
    :param input_stream: Input whose terminal capability controls dispatch.
    :return: Whether the conditional setup command completed successfully.
    """
    record = inspection.require_usable()
    if record is None or record.active_runtime is None:
        raise InstallationError(
            "Configuration setup requires a usable runtime."
        )
    if "config" not in record.placement.capabilities:
        return False
    stream = input_stream if input_stream is not None else sys.stdin
    if skip or not stream.isatty():
        return False
    arguments: list[str] = []
    if runtime_options is not None:
        from apprc.definition.resolution import CliRuntimeOptions
        from apprc.interfaces.cli.context import cli_runtime_options_to_args

        arguments = cli_runtime_options_to_args(
            replace(
                CliRuntimeOptions.from_options(runtime_options),
                layout=record.placement.layout,
            )
        )
    command_name = record.command_name
    directory = inspection.directory
    with installation_lock(directory):
        latest = inspect_installation(directory, app_id=record.identity.app_id)
        if (
            latest.record is None
            or latest.record.active_runtime != record.active_runtime
        ):
            return False
        lease: RuntimeLease | None = None
        if isinstance(record.active_runtime, RuntimeSlot):
            lease = acquire_runtime_lease(
                directory / "runtimes" / str(record.active_runtime.slot_id)
            )
    try:
        runtime = record.active_runtime
        command = runtime_command(directory, runtime, command_name)
        child_environment = dict(
            environment if environment is not None else os.environ
        )
        if lease is not None:
            child_environment = lease.environment(child_environment)
            spawn_options = lease.subprocess_options()
        else:
            child_environment.pop("_APPRC_RUNTIME_LEASE_HANDLE", None)
            spawn_options = {}
        child_environment = runtime_environment(child_environment)
        if lease is not None:
            child_environment = lease.environment(child_environment)
        child_environment["VIRTUAL_ENV"] = str(
            runtime_prefix(directory, runtime)
        )
        binary = str(
            runtime_prefix(directory, runtime)
            / ("Scripts" if os.name == "nt" else "bin")
        )
        child_environment["PATH"] = (
            binary + os.pathsep + child_environment.get("PATH", "")
        )
        subprocess.run(
            [
                str(command),
                *arguments,
                config_group_name,
                "setup",
                "--offer-missing",
            ],
            env=child_environment,
            check=True,
            **spawn_options,
        )
    except (OSError, subprocess.CalledProcessError):
        if raise_on_failure:
            raise
        return False
    finally:
        if lease is not None:
            lease.close()
    return True


def confirm_desktop_shortcut(
    identity: InstallationIdentity, *, assume_yes: bool
) -> bool:
    """Offer a desktop shortcut only in an interactive desktop session."""
    if (
        assume_yes
        or sys.platform not in {"linux", "win32"}
        or sys.stdin is None
        or not sys.stdin.isatty()
    ):
        return False
    import typer
    from apprc.distribution.runtime._os_integration import (
        desktop_shortcut_available,
    )
    from apprc.interfaces.cli._typer_utils import cli_confirm

    if not desktop_shortcut_available(identity):
        return False
    try:
        return cli_confirm("Add Desktop shortcut?", default=False)
    except typer.Abort:
        return False


def publish_optional_shortcuts(
    manager: InstallationManager,
    command: Path,
    identity: InstallationIdentity,
    *,
    display_name: str,
    start_menu: bool,
    desktop: bool,
    launch_enabled: bool,
) -> InstallationInspection:
    """Publish shortcuts after Ready and persist only owned outputs."""
    from apprc.distribution.runtime._icons import ready_icon
    from apprc.distribution.runtime._os_integration import publish_shortcuts
    from apprc.user_files.installation.operations import record_owned_outputs

    if start_menu or desktop:
        report("stage", "Publishing Shortcuts")
    directory = manager.directory
    with installation_lock(directory):
        inspection = manager.inspect()
        record = inspection.record
        if (
            record is None
            or record.status != "ready"
            or inspection.revision is None
            or record.identity != identity
            or not any(
                item.kind == "command" and item.path == str(command)
                for item in record.owned_outputs
            )
        ):
            warn(LOG, "Optional shortcuts were not updated")
            return inspection
        previous = tuple(
            item for item in record.owned_outputs if item.kind == "shortcut"
        )
        created: tuple[OwnedOutput, ...] = ()
        try:
            _, icon, _ = ready_icon(inspection)
            created = publish_shortcuts(
                command,
                identity,
                display_name=display_name,
                start_menu=start_menu,
                desktop=desktop,
                launch_enabled=launch_enabled,
                previous=previous,
                icon=icon,
            )
            created_paths = {item.path for item in created}
            outputs = (
                tuple(
                    item
                    for item in record.owned_outputs
                    if item.kind != "shortcut" or item.path not in created_paths
                )
                + created
            )
            result = record_owned_outputs(
                directory,
                app_id=identity.app_id,
                expected_revision=inspection.revision,
                generation_id=record.generation_id,
                owned_outputs=outputs,
            )
            for output in created:
                report("result", "Shortcut", "PUBLISHED", output.path)
            return result
        except Exception as error:
            from apprc.distribution.runtime._os_integration import (
                remove_owned_command,
            )

            for output in created:
                try:
                    remove_owned_command(output)
                except InstallationError:
                    pass
            warn(LOG, "Optional shortcuts were not updated", error)
            return manager.inspect()
