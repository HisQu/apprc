"""Human-facing installation progress, results and uninstall previews."""

from __future__ import annotations

from pathlib import Path, PurePath
from typing import TYPE_CHECKING
from collections.abc import Mapping

import typer

from apprc.definition.installation import EditableCheckout
from apprc.distribution.runtime._install_progress import (
    InstallProgress,
    installation_color,
)

if TYPE_CHECKING:
    from rich.console import Console
    from rich.tree import Tree
    from apprc.definition.installation import (
        InstallationInspection,
        MigrationPlan,
    )

    from apprc.distribution.runtime._uninstall_controller import (
        UninstallPreparation,
    )


def installation_console(
    ctx: typer.Context | None, *, error: bool = False
) -> Console:
    """Respect Click color overrides, terminal detection and NO_COLOR.

    :param ctx: Active command context.
    :param error: Whether to write to the error stream.
    :return: Console without implicit markup or path guessing.
    """
    from apprc.interfaces._terminal_console import terminal_console

    return terminal_console(
        typer.get_text_stream("stderr" if error else "stdout"),
        color=ctx.color if ctx is not None else installation_color.get(),
    )


class InstallationProgressOutput:
    """Render sequenced install stages with semantic colors and a plain fallback."""

    def __init__(self, ctx: typer.Context | None, name: str, mode: str) -> None:
        self._ctx = ctx
        self._name = name
        self._mode = mode
        self._stage = 0
        self.stage = ""
        self._version = ""
        if mode != "managed":
            title = (
                "Repair installation"
                if mode == "repair"
                else f"{mode.title()} installation"
            )
            self._write(f"{name} · {title}")

    def _write(
        self,
        message: str,
        *,
        style: str = "",
        prefix: str = "",
        path: str | Path | None = None,
        error: bool = False,
    ) -> None:
        from apprc.interfaces._terminal_console import write_line

        write_line(
            typer.get_text_stream("stderr" if error else "stdout"),
            message,
            style=style,
            prefix=prefix,
            path=path,
            color=self._ctx.color
            if self._ctx is not None
            else installation_color.get(),
        )

    def __call__(self, event: InstallProgress) -> None:
        if event.kind == "version":
            self._version = event.message
        elif event.kind == "summary":
            self._write(f"{self._name} · {event.message}", style="stage")
        elif event.kind == "stage":
            self._stage += 1
            self.stage = event.message
            self._write(f"\n{self._stage}. {event.message}", style="stage")
        elif event.kind == "result":
            self._write(
                event.message, prefix=f"   {event.status:<10} ", path=event.path
            )
        elif event.kind == "warning":
            self._write(
                f"Warning: {event.message}",
                style="warning",
                error=True,
                path=event.path,
            )
        else:
            self._write(f"   {event.message}", style="detail", path=event.path)

    def complete(self, *, next_step: str | None = None) -> None:
        """Confirm the usable, committed install."""
        product = (
            f"{self._name} {self._version}" if self._version else self._name
        )
        action = (
            "repair" if self._mode == "repair" else f"{self._mode} installation"
        )
        self._write(f"\n{product} {action} complete.", style="success")
        if next_step:
            self._write("\nNext step")
            for line in next_step.splitlines():
                self._write(f"  {line}")

    def failed(
        self,
        message: str,
        *,
        path: str | Path | None = None,
        notes: tuple[str, ...] = (),
    ) -> None:
        """Display the installation failure, including any recovery notes."""
        self._write(
            f"Installation failed: {message}",
            style="error",
            path=path,
            error=True,
        )
        for note in notes:
            self._write(note, style="error", error=True)


def print_installation_path(
    ctx: typer.Context, label: str, path: str | Path, *, error: bool = False
) -> None:
    """Print one explicitly identified filesystem path with canonical styling.

    :param ctx: Active command context.
    :param label: Plain description of the path.
    :param path: Captured filesystem path.
    :param error: Whether to write to stderr.
    """
    from rich.text import Text

    from apprc.interfaces._terminal_styles import path_text

    installation_console(ctx, error=error).print(
        Text.assemble(label + ": ", path_text(path))
    )


def _add_path_tree(
    root: Tree, targets: Mapping[PurePath, tuple[str, str]]
) -> None:
    """Group captured targets by filesystem ancestry, folding unbranched parents.

    :param root: Presentation parent for the filesystem paths.
    :param targets: Captured paths mapped to action and explanation.
    """
    from rich.text import Text

    from apprc.interfaces._terminal_styles import (
        ERROR_STYLE,
        SUCCESS_STYLE,
        path_text,
    )

    children: dict[PurePath, set[PurePath]] = {}
    anchors: set[PurePath] = set()
    for target in targets:
        for path in (target, *target.parents):
            children.setdefault(path, set())
            if path.parent == path:
                anchors.add(path)
            else:
                children.setdefault(path.parent, set()).add(path)

    def add(parent: Tree, path: PurePath, ancestor: PurePath | None) -> None:
        while path not in targets and len(children[path]) == 1:
            path = next(iter(children[path]))
        label = Text.assemble(
            path_text(
                str(path if ancestor is None else path.relative_to(ancestor))
            )
        )
        if path in targets:
            action, explanation = targets[path]
            label.append("  ")
            label.append(
                action,
                style="bold "
                + (ERROR_STYLE if action == "Delete" else SUCCESS_STYLE),
            )
            label.append(" — " + explanation)
        branch = parent.add(label)
        for child in sorted(
            children[path], key=lambda value: str(value).casefold()
        ):
            add(branch, child, path)

    for anchor in sorted(anchors, key=lambda value: str(value).casefold()):
        add(root, anchor, None)


def uninstall_tree(preparation: UninstallPreparation) -> Tree:
    """Show captured targets under shared parents without filesystem traversal.

    :param preparation: Exact prepared selection and recorded integrations.
    :return: A filesystem tree with actions on selected targets only.
    """
    from rich.text import Text
    from rich.tree import Tree

    root = Tree("Uninstall preview (actions apply to marked targets)")
    plan = preparation.plan
    record = preparation.inspection.record
    if plan is None:
        root.add(
            "No executable removal plan; no changes will be made. See diagnostics."
        )
        return root
    targets: dict[PurePath, tuple[str, str]] = {}
    registrations: list[str] = []
    if plan.complete:
        targets[plan.directory] = (
            "Delete",
            "installation files and managed runtimes; all contents",
        )
    labels = {
        "config": "configuration, including settings and secrets",
        "appdata": "application data",
        "cache": "cache",
        "state": "state",
    }
    for entry in plan.inventory.entries:
        if plan.complete and entry.path.is_relative_to(plan.directory):
            continue
        label = (
            "editable checkout"
            if entry.kind == "repository"
            else labels.get(entry.resource or "", "installation file")
        )
        if entry.kind in {"tree", "repository"}:
            label += "; all contents"
        elif entry.kind == "symlink":
            label += "; link only, destination preserved"
        targets[entry.path] = ("Delete", label)
    if record is not None:
        for output in record.owned_outputs:
            if output.kind == "hkcu":
                registrations.append(output.path)
            elif output.kind in {"command", "shortcut"}:
                path = Path(output.path)
                if path in targets or (
                    plan.complete and path.is_relative_to(plan.directory)
                ):
                    continue
                targets[path] = (
                    "Delete",
                    "global command"
                    if output.kind == "command"
                    else "shortcut",
                )
    for entry in plan.inventory.retained:
        targets[entry.path] = (
            "Keep",
            labels.get(entry.resource or "", "retained directory"),
        )
    if (
        record is not None
        and isinstance(record.active_runtime, EditableCheckout)
        and not any(
            entry.kind == "repository" for entry in plan.inventory.entries
        )
    ):
        targets[record.active_runtime.project] = ("Keep", "editable checkout")
        targets[record.active_runtime.environment] = (
            "Keep",
            "development environment",
        )
    _add_path_tree(root, targets)
    if registrations:
        registry = root.add("Windows registration")
        for key in registrations:
            registry.add(Text.assemble(("Delete", "bold red"), " — ", key))
    return root


def print_migration_preview(ctx: typer.Context, plan: MigrationPlan) -> None:
    """Show the exact migration inventory before asking to apply it."""
    from apprc.interfaces._terminal_console import cli_line

    cli_line(ctx, "Migration preview", style="stage")
    cli_line(ctx, "Source", path=plan.inventory.source_root)
    cli_line(ctx, "Destination", path=plan.inventory.destination_root)
    for entry in plan.inventory.entries:
        cli_line(ctx, "Move", path=entry.path)
    for path in plan.inventory.unknown:
        cli_line(ctx, "Unknown entry", path=path, style="warning")
    if not plan.inventory.entries:
        cli_line(ctx, "No files in the migration inventory.", style="detail")


def print_installation_result(
    ctx: typer.Context, inspection: InstallationInspection, *, operation: str
) -> None:
    """Show the saved placement and diagnostics from a migration or repair."""
    from apprc.interfaces._terminal_console import cli_line

    cli_line(
        ctx,
        "Installation record",
        path=inspection.directory / "installation.json",
    )
    record = inspection.record
    if record is not None:
        layout = record.placement.layout
        cli_line(ctx, f"Layout: {layout.mode}", path=layout.root)
    for diagnostic in inspection.diagnostics:
        cli_line(
            ctx,
            f"Warning: {diagnostic.message} {diagnostic.recovery}",
            style="warning",
            error=True,
        )
    if operation:
        message = (
            f"{operation} complete."
            if inspection.status == "ready"
            else f"{operation} result: {inspection.status}."
        )
        cli_line(
            ctx,
            message,
            style="success" if inspection.status == "ready" else "warning",
        )
