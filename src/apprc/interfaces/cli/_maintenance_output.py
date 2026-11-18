"""Human reports for resource maintenance and workspace inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from apprc.interfaces._terminal_console import cli_console, cli_line
from apprc.interfaces._terminal_styles import (
    ERROR_STYLE,
    SUCCESS_STYLE,
    path_text,
)

if TYPE_CHECKING:
    from typer import Context

    from apprc.definition.maintenance import RemovalPlan, RemovalResult
    from apprc.user_files.workspace_roots._loading import (
        WorkspaceRegistryInspection,
    )


def print_resource_preview(
    ctx: Context, kind: str, operation: str, plans: tuple[RemovalPlan, ...]
) -> None:
    """Show captured removal targets before confirmation or a dry run."""
    cli_line(ctx, f"{kind.title()} {operation} preview", style="stage")
    if not any(plan.targets for plan in plans):
        cli_line(ctx, "No targets to remove.", style="detail")
    console = cli_console(ctx)
    for plan in plans:
        cli_line(ctx, plan.category, path=plan.root)
        for target in plan.targets:
            console.print(
                Text.assemble(("  Delete ", ERROR_STYLE), path_text(target))
            )
        for warning in plan.warnings:
            cli_line(ctx, f"Warning: {warning}", style="warning")


def print_resource_result(
    ctx: Context,
    kind: str,
    operation: str,
    results: tuple[RemovalResult, ...],
    *,
    failed: bool = False,
) -> None:
    """Report actual removals without marking a partial operation successful."""
    for result in results:
        for path in result.removed:
            cli_line(ctx, "Removed", path=path, style="success")
        for path in result.skipped:
            cli_line(ctx, "Skipped", path=path, style="warning")
        for warning in result.warnings:
            cli_line(ctx, f"Warning: {warning}", style="warning")
    if failed:
        return
    if any(result.skipped or result.warnings for result in results):
        cli_line(
            ctx,
            f"{kind.title()} {operation} finished with warnings.",
            style="warning",
        )
    elif results:
        cli_line(ctx, f"{kind.title()} {operation} complete.", style="success")


def print_workspace_registry(
    ctx: Context, inspection: WorkspaceRegistryInspection
) -> None:
    """List registered and archived roots together with registry issues."""
    cli_line(ctx, "Workspaces", style="stage")
    cli_line(ctx, "Registry", path=inspection.path)
    if inspection.error:
        cli_line(ctx, inspection.error, style="error", error=True)
    for issue in inspection.issues:
        if issue != inspection.error:
            cli_line(ctx, issue, style="error", error=True)
    for warning in inspection.warnings:
        cli_line(ctx, f"Warning: {warning}", style="warning")
    registry = inspection.registry
    if registry is None or not registry.workspaces:
        cli_line(ctx, "No registered workspaces.", style="detail")
    if registry is None:
        return
    console = cli_console(ctx)
    for name, record in sorted(registry.workspaces.items()):
        row = Text.assemble((name, "bold"), ": ", path_text(record.root))
        if name == registry.selected_workspace:
            row.append(" (selected)", style=SUCCESS_STYLE)
        console.print(row)
    if registry.archived_workspaces:
        cli_line(ctx, "Archived workspaces", style="stage")
        for name, record in sorted(registry.archived_workspaces.items()):
            cli_line(ctx, name, path=record.archive)
            cli_line(ctx, "  Previous root", path=record.source_root)
