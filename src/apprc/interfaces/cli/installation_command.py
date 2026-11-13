"""Read-only installation diagnostics and explicit saved recovery commands."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit
from urllib.request import url2pathname

import typer

from apprc.definition.installation import (
    EditableCheckout,
    InstallationHooks,
    InstallationInspection,
    InstallationRecord,
    RuntimeSlot,
)
from apprc.definition.paths import ResourceKind
from apprc.interfaces.cli.context import (
    InstallationCommandContext,
    _cli_runtime_options_payload,
    installation_command_context_from,
)

if TYPE_CHECKING:
    from apprc.distribution.runtime.controllers import UninstallPreparation

_CATEGORIES: tuple[ResourceKind, ...] = ("config", "appdata", "cache", "state")


def mount_installation_group(
    app: typer.Typer,
    *,
    maintenance_group_name: str = "app",
    installation_management: bool = False,
    installer_entrypoint: Callable[[Sequence[str]], int] | None = None,
    installation_hooks: InstallationHooks = InstallationHooks(),
) -> typer.Typer:
    """Register explicitly enabled installation actions on a maintenance group."""
    child = app
    if installer_entrypoint is not None and not callable(installer_entrypoint):
        raise TypeError("installer_entrypoint must be callable.")
    if installer_entrypoint is not None or installation_management:
        @child.command(
            "install",
            context_settings={
                "allow_extra_args": True,
                "ignore_unknown_options": True,
            },
        )
        def install(
            ctx: typer.Context,
            editable: Annotated[bool, typer.Option("--editable", "-e")] = False,
            command_directory: Annotated[
                Path | None, typer.Option("--command-directory")
            ] = None,
            assume_yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
            skip_setup: Annotated[bool, typer.Option("--skip-setup")] = False,
        ) -> None:
            """Register the existing checkout or invoke an authored installer."""
            if editable:
                if not installation_management:
                    raise typer.BadParameter(
                        "Editable installation requires AppRC installation management."
                    )
                try:
                    result = _register_editable(
                        ctx,
                        command_directory=command_directory,
                        assume_yes=assume_yes,
                    )
                    from apprc.distribution.runtime.installation import (
                        offer_configuration_setup,
                    )

                    offer_configuration_setup(result, skip=skip_setup)
                except (OSError, ValueError) as exc:
                    raise typer.BadParameter(str(exc)) from exc
                return
            if installer_entrypoint is None:
                command = (
                    _inspection(ctx).manager.spec.command_name
                    or Path(sys.argv[0]).stem
                )
                raise typer.BadParameter(
                    f"Run `uv run --locked {command} {maintenance_group_name} "
                    "install -e` from the checkout."
                )
            from apprc.interfaces.cli._typer_utils import (
                args_after_cli_command,
                args_after_command,
            )

            group_args = args_after_cli_command(
                maintenance_group_name, tokens=sys.argv[1:]
            )
            arguments = (
                args_after_command("install", tokens=group_args)
                if group_args is not None
                else None
            )
            raise typer.Exit(
                code=installer_entrypoint(
                    tuple(ctx.args if arguments is None else arguments)
                )
            )

    @child.command("migrate")
    def migrate(
        ctx: typer.Context,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        assume_yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Preview or explicitly execute recognized AppRC placement migration."""
        context = _inspection(ctx)
        manager = context.manager
        try:
            if context.native_binding is None:
                plan = manager.preview_migration()
            else:
                plan = manager.preview_migration(
                    identity=context.native_binding.identity,
                    command_name=context.native_binding.command_name,
                )
            payload = _migration_payload(plan)
            _emit(payload, json_output)
            if dry_run:
                return
            if not assume_yes and not sys.stdin.isatty():
                raise typer.BadParameter("Unattended migration requires --yes.")
            if not assume_yes and not typer.confirm(
                "Migration requires old application consumers to be stopped. Proceed?",
                default=False,
            ):
                raise typer.Abort()
            manager_executable = context._native_manager_executable
            result = manager.migrate(
                plan,
                quiescent=True,
                manager_executable=manager_executable,
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        _emit(_inspection_payload(result), json_output)

    @child.command("repair")
    def repair(ctx: typer.Context) -> None:
        """Repair a managed runtime with its authenticated native manager."""
        context = _inspection(ctx)
        if context.native_binding is None or context._native_manager_executable is None:
            record = context.inspection.record
            if (
                record is not None
                and isinstance(record.active_runtime, EditableCheckout)
            ):
                raise typer.BadParameter(
                    "This editable environment is owned by Git and uv. "
                    "Restore it with `uv sync --locked` in the recorded checkout."
                )
            raise typer.BadParameter(
                "Managed repair requires the matching native setup executable. "
                "Run that setup executable to repair the installation."
            )
        try:
            from apprc.distribution.runtime._manager import _manager_uv
            from apprc.distribution.runtime.installation import (
                _repair_managed_application,
            )

            result = _repair_managed_application(
                context.manager,
                manager_executable=context._native_manager_executable,
                uv=_manager_uv(),
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        _emit(_inspection_payload(result), False)

    @child.command("uninstall")
    def uninstall(
        ctx: typer.Context,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        complete: Annotated[bool, typer.Option("--complete")] = False,
        category: Annotated[
            list[str] | None, typer.Option("--category")
        ] = None,
        forget_retained: Annotated[
            bool, typer.Option("--forget-retained")
        ] = False,
        assume_yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Preview or remove the program and only explicitly selected owned data."""
        requested = frozenset(category or ())
        invalid = requested - set(_CATEGORIES)
        if invalid:
            raise typer.BadParameter(
                "Unknown category: " + ", ".join(sorted(invalid))
            )
        selected: frozenset[ResourceKind] = frozenset(
            kind for kind in _CATEGORIES if kind in requested
        )
        if forget_retained and not complete:
            raise typer.BadParameter("--forget-retained requires --complete.")
        command_context = _inspection(ctx)
        inspection = command_context.inspection
        directory = inspection.directory
        record = inspection.record
        if complete and not requested and record is not None:
            selected = record.placement.capabilities
        try:
            from apprc.distribution.runtime import controllers

            manager_executable = command_context._native_manager_executable
            preparation = controllers.prepare_uninstall(
                directory,
                categories=selected,
                complete=complete,
                forget_retained=forget_retained,
                manager_executable=manager_executable,
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        payload = _preparation_payload(preparation)
        _emit(payload, json_output)
        if dry_run:
            return
        if preparation.plan is None or not preparation.can_execute:
            raise typer.Exit(code=1)
        if not assume_yes and not sys.stdin.isatty():
            raise typer.BadParameter("Unattended removal requires --yes.")
        if not assume_yes and not typer.confirm(
            "Remove the program and the exact owned targets shown above?",
            default=False,
        ):
            raise typer.Abort()

        try:
            handoff = controllers.start_uninstall_handoff(
                preparation.plan,
                original_pid=os.getpid(),
                manager_executable=command_context._native_manager_executable,
            )
            handoff.wait_ready()
            handoff.signal_exit()
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        raise SystemExit(0)

    return child

def _register_editable(
    ctx: typer.Context,
    *,
    command_directory: Path | None,
    assume_yes: bool,
) -> InstallationInspection:
    """Validate the current uv checkout before recording its existing environment."""
    context = _inspection(ctx)
    command = (
        context.manager.spec.command_name
        or Path(sys.argv[0]).stem
        or "<command>"
    )
    maintenance_group = (
        context.native_binding.maintenance_group_name
        if context.native_binding is not None
        else ctx.parent.info_name
        if ctx.parent is not None and ctx.parent.info_name
        else "app"
    )
    guidance = (
        f"Run `uv run --locked {command} {maintenance_group} "
        "install -e` from the checkout."
    )
    cwd = Path.cwd().resolve()
    prefix = Path(sys.prefix).resolve()
    project_root: Path | None = None
    distribution_spec = None
    try:
        from apprc.distribution.metadata import read_distribution_spec

        for candidate in (cwd, *cwd.parents):
            environment = candidate / ".venv"
            if not environment.is_dir() or environment.resolve() != prefix:
                continue
            spec = read_distribution_spec(candidate)
            primary = spec.metadata.command_name or (
                spec.metadata.identity.commands[0]
                if len(spec.metadata.identity.commands) == 1
                else None
            )
            if (
                spec.metadata.identity.app_id == context.manager.spec.app_id
                and primary is not None
                and primary in spec.metadata.identity.commands
                and (
                    context.manager.spec.command_name is None
                    or primary == context.manager.spec.command_name
                )
            ):
                command = primary
                project_root = candidate
                distribution_spec = spec
                break
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{exc} {guidance}") from exc
    if project_root is None or distribution_spec is None:
        raise ValueError(
            "The current interpreter, checkout metadata, and declared command "
            f"do not identify one existing .venv. {guidance}"
        )
    if not prefix.is_dir() or not (project_root / "pyproject.toml").is_file():
        raise ValueError(f"The checkout or its .venv is unavailable. {guidance}")
    try:
        distribution = importlib.metadata.distribution(
            distribution_spec.metadata.identity.distribution
        )
        installed_name = re.sub(
            r"[-_.]+", "-", distribution.metadata["Name"]
        ).lower()
        if (
            installed_name != distribution_spec.metadata.identity.distribution
            or distribution.version != distribution_spec.metadata.version
        ):
            raise ValueError(
                "The installed distribution version or identity differs from "
                f"the checkout metadata. {guidance}"
            )
        direct_url = distribution.read_text("direct_url.json")
        direct = json.loads(direct_url) if direct_url is not None else None
        parsed_url = (
            urlsplit(direct["url"])
            if isinstance(direct, dict) and isinstance(direct.get("url"), str)
            else None
        )
        source_root = (
            Path(url2pathname(parsed_url.path))
            if parsed_url is not None
            and parsed_url.scheme == "file"
            and parsed_url.netloc in {"", "localhost"}
            else None
        )
        if (
            source_root is None
            or source_root.resolve() != project_root.resolve()
            or not isinstance(direct.get("dir_info"), dict)
            or direct["dir_info"].get("editable") is not True
        ):
            raise ValueError(
                "The installed distribution is not an editable installation "
                f"of this checkout. {guidance}"
            )
        with (project_root / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        scripts = project.get("scripts")
        installed_scripts = {
            entry.name: entry.value
            for entry in distribution.entry_points
            if entry.group == "console_scripts"
        }
        if (
            not isinstance(scripts, dict)
            or installed_scripts.get(command) != scripts.get(command)
        ):
            raise ValueError(
                "The installed command entry point differs from checkout "
                f"metadata. {guidance}"
            )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        importlib.metadata.PackageNotFoundError,
    ) as exc:
        raise ValueError(f"{exc} {guidance}") from exc
    executable = prefix / (
        "Scripts" if os.name == "nt" else "bin"
    ) / (command + (".exe" if os.name == "nt" else ""))
    if not executable.is_file():
        raise ValueError(
            f"Console command {command!r} is missing from the current .venv. {guidance}"
        )

    from apprc.definition.installation import EditableCheckout, InstallationPlacement
    from apprc.definition.resolution import ResolveOptions
    from apprc.distribution.runtime.installation import (
        register_editable_application,
    )
    from apprc.user_files.app_home.layouts import resolve_app_paths

    options = context.runtime_options
    paths = resolve_app_paths(
        context.manager.spec,
        ResolveOptions(
            env_files=options.env_files,
            env_file_overrides_os_environ=options.env_file_overrides_os_environ,
            load_dotenv_layers=options.load_dotenv_layers,
            workspace=options.workspace,
            layout=options.layout,
        ),
        context.environment,
    )
    capabilities: frozenset[ResourceKind] = frozenset(
        kind
        for kind, enabled in (
            ("config", context.manager.spec.paths.config),
            ("appdata", context.manager.spec.paths.appdata),
            ("cache", context.manager.spec.paths.cache),
            ("state", context.manager.spec.paths.state),
        )
        if enabled
    )
    placement = InstallationPlacement(
        layout=paths.layout,
        config_dir=paths.config_dir if "config" in capabilities else None,
        appdata_dir=paths.appdata_dir if "appdata" in capabilities else None,
        cache_dir=paths.cache_dir if "cache" in capabilities else None,
        state_dir=paths.state_dir if "state" in capabilities else None,
        logs_dir=paths.logs_dir if "state" in capabilities else None,
        capabilities=capabilities,
    )
    uv_name = shutil.which("uv", path=context.environment.get("PATH"))
    if uv_name is None:
        raise ValueError(f"uv is unavailable. {guidance}")
    uv = Path(uv_name).resolve()
    if command_directory is None:
        selected = subprocess.run(
            [str(uv), "tool", "dir", "--bin"],
            cwd=project_root,
            env=dict(context.environment),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        command_directory = Path(selected)
    if (
        not command_directory.is_absolute()
        or not command_directory.is_dir()
        or os.fspath(command_directory) not in context.environment.get("PATH", "").split(os.pathsep)
    ):
        raise ValueError(
            "The command directory must be an absolute existing directory on PATH. "
            f"{guidance}"
        )
    if command_directory.resolve().is_relative_to(project_root) or (
        command_directory.resolve().is_relative_to(prefix)
    ):
        raise ValueError(
            "The command directory must be outside the checkout and .venv. "
            f"{guidance}"
        )
    try:
        return register_editable_application(
            context.manager,
            distribution_spec.metadata.identity,
            EditableCheckout(
                project=project_root,
                environment=prefix,
                hooks=distribution_spec.hooks,
            ),
            placement,
            command_name=command,
            uv=uv,
            command_directory=command_directory,
            assume_yes=assume_yes,
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"{exc} {guidance}") from exc


def installation_context(
    ctx: typer.Context,
) -> InstallationCommandContext | None:
    """Return diagnostic installation context without fabricating runtime paths."""
    return installation_command_context_from(ctx)


def _inspection(ctx: typer.Context) -> InstallationCommandContext:
    context = installation_context(ctx)
    if context is None:
        raise RuntimeError("Installation command context is not initialized.")
    return context


def _inspection_payload(
    inspection: InstallationInspection,
) -> dict[str, object]:
    return {
        "status": inspection.status,
        "app_id": inspection.app_id,
        "directory": str(inspection.directory),
        "revision": inspection.revision,
        "record": _record_payload(inspection.record),
        "diagnostics": [
            {
                "code": item.code,
                "message": item.message,
                "recovery": item.recovery,
            }
            for item in inspection.diagnostics
        ],
    }


def _record_payload(
    record: InstallationRecord | None,
) -> dict[str, object] | None:
    if record is None:
        return None
    placement = record.placement
    return {
        "generation_id": str(record.generation_id),
        "identity": record.identity.app_id,
        "command_name": record.command_name,
        "status": record.status,
        "layout": placement.layout.mode,
        "root": str(placement.layout.root) if placement.layout.root else None,
        "capabilities": sorted(placement.capabilities),
        "active_runtime": (
            None
            if record.active_runtime is None
            else {
                "kind": (
                    "editable"
                    if isinstance(record.active_runtime, EditableCheckout)
                    else "managed"
                ),
                "distribution": record.identity.distribution,
                "version": (
                    record.active_runtime.version
                    if isinstance(record.active_runtime, RuntimeSlot)
                    else None
                ),
                "slot_id": (
                    str(record.active_runtime.slot_id)
                    if isinstance(record.active_runtime, RuntimeSlot)
                    else None
                ),
            }
        ),
        "retiring_runtime_ids": [
            str(slot_id) for slot_id in record.retiring_runtime_ids
        ],
        "operation": record.operation.kind if record.operation else None,
    }

def _migration_payload(plan: MigrationPlan) -> dict[str, object]:
    return {
        "directory": str(plan.directory),
        "source_root": str(plan.inventory.source_root),
        "destination_root": str(plan.inventory.destination_root),
        "entries": [str(item.path) for item in plan.inventory.entries],
        "unknown": [str(path) for path in plan.inventory.unknown],
        "quiescent_required": True,
    }


def _preparation_payload(
    preparation: UninstallPreparation,
) -> dict[str, object]:
    return {
        "inspection": _inspection_payload(preparation.inspection),
        "can_execute": preparation.can_execute,
        "entries": [
            {
                "path": str(entry.path),
                "kind": entry.kind,
                "resource": entry.resource,
            }
            for entry in preparation.entries
        ],
        "diagnostics": [
            {
                "code": item.code,
                "message": item.message,
                "recovery": item.recovery,
            }
            for item in preparation.diagnostics
        ],
    }


def _emit(payload: dict[str, object], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        return
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))
