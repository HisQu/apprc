"""Read-only installation diagnostics and explicit saved recovery commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Callable

import typer

from apprc.definition.installation import (
    CleanupInventory,
    InstallationInspection,
    InstallationRecord,
    MigrationPlan,
)

from apprc.definition.paths import ResourceKind
from apprc.interfaces.cli.context import (
    InstallationCommandContext,
    installation_command_context_from,
)

if TYPE_CHECKING:
    from apprc.distribution.runtime.controllers import UninstallPreparation

_CATEGORIES: tuple[ResourceKind, ...] = ("config", "appdata", "cache", "state")


def mount_installation_group(
    app: typer.Typer,
    *,
    maintenance_help_panel: str = "Maintenance",
    installation_inventory: Callable[
        [InstallationInspection, frozenset[ResourceKind], bool],
        CleanupInventory,
    ]
    | None = None,
) -> typer.Typer:
    """Mount installation recovery under the existing maintenance panel."""
    child = typer.Typer(help="Inspect and recover the saved installation.")

    @child.command("show")
    def show(
        ctx: typer.Context,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show saved installation authority without initializing paths."""
        _emit(_inspection_payload(_inspection(ctx).inspection), json_output)

    @child.command("doctor")
    def doctor(
        ctx: typer.Context,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Diagnose saved installation authority without resolving business settings."""
        inspection = _inspection(ctx).inspection
        _emit(_inspection_payload(inspection), json_output)
        if inspection.status in {"invalid", "provisional", "incomplete"}:
            raise typer.Exit(code=1)

    @child.command("migrate")
    def migrate(
        ctx: typer.Context,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        assume_yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Preview or explicitly execute recognized AppRC placement migration."""
        manager = _inspection(ctx).manager
        try:
            plan = manager.preview_migration()
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
            result = manager.migrate(plan, quiescent=True)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        _emit(_inspection_payload(result), json_output)

    @child.command("repair")
    def repair(
        ctx: typer.Context,
        installer: Annotated[Path | None, typer.Option("--installer")] = None,
    ) -> None:
        """Run the matching saved installer or an explicitly validated installer."""
        directory = _inspection(ctx).inspection.directory
        try:
            from apprc.distribution.runtime import controllers

            argv = controllers.repair_saved(directory, installer=installer)
            completed = subprocess.run(argv, check=False)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        if completed.returncode:
            raise typer.Exit(code=completed.returncode)

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
        inspection = _inspection(ctx).inspection
        directory = inspection.directory
        record = inspection.record
        if complete and not requested and record is not None:
            selected = record.placement.capabilities
        pending = (
            record.operation
            if record is not None
            and record.operation is not None
            and record.operation.kind == "uninstall"
            else None
        )
        inventory = None
        try:
            if (
                complete
                and bool(selected)
                and installation_inventory is not None
                and pending is None
                and record is not None
                and inspection.status in {"ready", "removed-retained"}
                and selected
                <= (
                    record.placement.capabilities
                    | frozenset(
                        resource.kind for resource in record.placement.retired
                    )
                )
            ):
                inventory = installation_inventory(
                    inspection, selected, forget_retained
                )
            from apprc.distribution.runtime import controllers

            preparation = controllers.prepare_uninstall(
                directory,
                categories=selected,
                complete=complete,
                forget_retained=forget_retained,
                inventory=inventory,
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

        inventory_path: Path | None = None
        try:
            if inventory is not None:
                descriptor, name = tempfile.mkstemp(prefix="apprc-cleanup-")
                inventory_path = Path(name)
                with os.fdopen(descriptor, "wb") as stream:
                    if os.name != "nt":
                        os.fchmod(stream.fileno(), 0o600)
                    from apprc.user_files.installation.codec import (
                        encode_cleanup_inventory,
                    )

                    stream.write(
                        encode_cleanup_inventory(preparation.plan.inventory)
                    )
            argv = controllers.uninstall_saved(
                directory,
                original_pid=os.getpid(),
                expected_revision=preparation.plan.expected_revision,
                categories=selected,
                complete=complete,
                forget_retained=forget_retained,
                inventory_file=inventory_path,
            )
            completed = subprocess.run(argv, check=False)
            if completed.returncode:
                raise typer.Exit(code=completed.returncode)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        finally:
            if inventory_path is not None:
                inventory_path.unlink(missing_ok=True)
        raise SystemExit(0)

    app.add_typer(
        child, name="installation", rich_help_panel=maintenance_help_panel
    )
    return child


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
        "status": record.status,
        "layout": placement.layout.mode,
        "root": str(placement.layout.root) if placement.layout.root else None,
        "capabilities": sorted(placement.capabilities),
        "current": record.current.identity.distribution
        if record.current
        else None,
        "last_successful": (
            record.last_successful.identity.distribution
            if record.last_successful
            else None
        ),
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
