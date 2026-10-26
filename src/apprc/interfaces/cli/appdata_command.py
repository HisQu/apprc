"""Explicit Typer commands for inspecting and removing AppRC-managed data."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

import typer

from apprc.interfaces.cli._typer_utils import dump_json
from apprc.interfaces.cli.runtime import _ensure_appdata_group_name_available
from apprc.public.app_rc import AppRC
from apprc.services.manager import ConfigManager
from apprc.user_files.purge import ConfigPurgeError, ConfigPurgePlan


def mount_appdata_cli(app: typer.Typer, apprc: AppRC) -> typer.Typer:
    """Mount opt-in managed-data commands without replacing the host callback.

    The commands use a manager rather than resolving application settings. Hosts
    with runtime setup should declare ``appdata`` in ``CliRuntimePolicy`` using
    ``RuntimeIndependentCommand(action_prefixes={("paths",), ("clean",)},
    skip_empty=True)`` so options after either action also bypass runtime setup.

    :param app: Typer application, with or without an existing callback.
    :param apprc: Application declaration whose managed data is inspected.
    :return: Mounted ``appdata`` Typer application.
    :raises TypeError: If the host is not a Typer application.
    :raises RuntimeError: If the host already owns the ``appdata`` name.
    """
    if not isinstance(app, typer.Typer):
        raise TypeError(
            "mount_appdata_cli supports typer.Typer instances only."
        )
    _ensure_appdata_group_name_available(app)
    child = typer.Typer(
        no_args_is_help=True,
        help="Inspect and remove AppRC-managed application data.",
    )

    @child.command("paths")
    def appdata_paths_cmd(
        apprc_dir: Annotated[
            Path | None,
            typer.Option(
                "--apprc-dir", help="AppRC directory to inspect and clean."
            ),
        ] = None,
        json_output: Annotated[
            bool,
            typer.Option(
                "--json", help="Print the structured cleanup inventory."
            ),
        ] = False,
    ) -> None:
        """Show managed locations and retained external storage data."""
        _, plan = _manager_and_plan(apprc, apprc_dir, action="paths")
        if json_output:
            dump_json(
                {
                    "apprc_dir": str(plan.apprc_dir),
                    "managed_files": [str(path) for path in plan.managed_files],
                    "internal_storage_roots": [
                        str(root) for root in plan.internal_storage_roots
                    ],
                    "external_storage_roots": [
                        str(root) for root in plan.external_storage_roots
                    ],
                    "stale_storage": plan.stale_storage,
                    "stale_user_dotenv": plan.stale_user_dotenv,
                }
            )
            _print_plan_warnings(plan)
            return
        _print_plan(plan)

    @child.command("clean")
    def appdata_clean_cmd(
        apprc_dir: Annotated[
            Path | None,
            typer.Option(
                "--apprc-dir", help="AppRC directory to inspect and clean."
            ),
        ] = None,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Show exact removal targets without changing files.",
            ),
        ] = False,
        assume_yes: Annotated[
            bool,
            typer.Option(
                "--yes",
                "-y",
                help="Remove the listed AppRC-managed targets without prompting.",
            ),
        ] = False,
    ) -> None:
        """Remove AppRC files that package uninstall leaves behind."""
        manager, plan = _manager_and_plan(apprc, apprc_dir, action="clean")
        _print_plan(plan, removal="preview" if dry_run else "apply")
        if dry_run:
            return
        if not assume_yes and not typer.confirm(
            "Remove these AppRC-managed files and internal storage roots?"
        ):
            typer.echo("No files were changed.")
            raise typer.Exit(code=1)
        try:
            result = manager.apply_purge(plan)
        except (OSError, ConfigPurgeError) as exc:
            raise typer.BadParameter(
                str(exc), param_hint="appdata clean"
            ) from exc
        typer.echo(f"removed_entries: {len(result.removed)}")
        for path in result.skipped:
            typer.echo(f"skipped_unsafe_target: {path}", err=True)
        if plan.apprc_dir.exists():
            typer.echo(
                "remaining_unmanaged_data: "
                f"{plan.apprc_dir} was kept because it is not empty.",
                err=True,
            )

    app.add_typer(child, name="appdata")
    return child


def _manager_and_plan(
    apprc: AppRC,
    apprc_dir: Path | None,
    *,
    action: Literal["paths", "clean"],
) -> tuple[ConfigManager, ConfigPurgePlan]:
    """Select the managed directory without inheriting runtime CLI selectors.

    :param apprc: Application declaration.
    :param apprc_dir: Explicit managed-directory override, if supplied.
    :param action: Invoked command used to label planning errors.
    :return: Manager and its validated, mutation-free cleanup inventory.
    """
    try:
        manager = apprc.manage()
        if apprc_dir is not None:
            manager = apprc.manage(
                replace(manager.options, apprc_dir=apprc_dir),
                environment=manager.environment,
            )
        return manager, manager.plan_purge()
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(
            str(exc), param_hint=f"appdata {action}"
        ) from exc


def _print_plan(
    plan: ConfigPurgePlan,
    *,
    removal: Literal["preview", "apply"] | None = None,
) -> None:
    """Render one validated inventory for inspection or cleanup.

    :param plan: Exact managed targets and external retention scope.
    :param removal: Preview/apply wording, or inspection-only keys when omitted.
    """
    file_key = "managed_file"
    root_key = "internal_storage_root"
    if removal is not None:
        file_key = "would_remove" if removal == "preview" else "remove"
        root_key = (
            "would_remove_tree" if removal == "preview" else "remove_tree"
        )
    typer.echo(f"apprc_dir: {plan.apprc_dir}")
    for path in plan.managed_files:
        typer.echo(f"{file_key}: {path}")
    for root in plan.internal_storage_roots:
        typer.echo(f"{root_key}: {root}")
    for root in plan.external_storage_roots:
        typer.echo(f"keep_external_storage_data: {root}")
    _print_plan_warnings(plan)


def _print_plan_warnings(plan: ConfigPurgePlan) -> None:
    """Keep stale-capability diagnostics separate from inventory stdout.

    :param plan: Validated inventory with capability-drift flags.
    """
    if plan.stale_storage:
        typer.echo(
            "warning: apprc.toml contains stale storage configuration for "
            "an app that no longer declares storage.",
            err=True,
        )
    if plan.stale_user_dotenv:
        typer.echo(
            "warning: apprc.user.env exists for an app that no longer "
            "declares user-dotenv support.",
            err=True,
        )
