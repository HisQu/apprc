"""Human-facing installation output built from captured uninstall authority."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.text import Text
from rich.tree import Tree

from apprc.definition.installation import EditableCheckout
from apprc.interfaces._terminal_styles import path_text

if TYPE_CHECKING:
    from apprc.distribution.runtime._uninstall_controller import (
        UninstallPreparation,
    )


def installation_console(ctx: typer.Context) -> Console:
    """Respect Click color overrides, terminal detection and NO_COLOR.

    :param ctx: Active command context.
    :return: Console without implicit markup or path guessing.
    """
    stream = typer.get_text_stream("stdout")
    color = (
        ctx.color if ctx.color is not None else stream.isatty()
    ) and "NO_COLOR" not in os.environ
    return Console(
        file=stream,
        force_terminal=color,
        color_system="standard" if color else None,
        markup=False,
        highlight=False,
        soft_wrap=True,
    )


def print_installation_path(
    ctx: typer.Context, label: str, path: str | Path
) -> None:
    """Print one explicitly identified filesystem path with canonical styling.

    :param ctx: Active command context.
    :param label: Plain description of the path.
    :param path: Captured filesystem path.
    """
    installation_console(ctx).print(
        Text.assemble(label + ": ", path_text(path))
    )


def uninstall_tree(
    preparation: UninstallPreparation, *, remove_repository: bool
) -> Tree:
    """Describe selected deletion and retention without traversing the filesystem.

    :param preparation: Exact prepared selection and recorded integrations.
    :param remove_repository: Whether the checkout is explicitly selected.
    :return: A compact tree with full path labels.
    """
    root = Tree("Uninstall preview")
    deleting = root.add(Text("Delete", style="bold red"))
    keeping = root.add(Text("Keep", style="bold green"))
    plan = preparation.plan
    record = preparation.inspection.record
    if plan is None:
        deleting.add("No executable removal plan; see diagnostics.")
        keeping.add("No changes will be made.")
        return root
    if plan.complete:
        deleting.add(
            "Installation files and managed runtimes — including all contents"
        ).add(path_text(plan.directory))
    labels = {
        "config": "Configuration — including settings and secrets",
        "appdata": "Application data",
        "cache": "Cache",
        "state": "State",
    }
    seen: set[Path] = set()
    for entry in plan.inventory.entries:
        if plan.complete and entry.path.is_relative_to(plan.directory):
            continue
        if entry.path in seen:
            continue
        seen.add(entry.path)
        label = (
            "Editable checkout"
            if entry.kind == "repository"
            else labels.get(entry.resource or "", "Installation file")
        )
        if entry.kind in {"tree", "repository"}:
            label += " — including all contents"
        elif entry.kind == "symlink":
            label += " — link only; destination preserved"
        deleting.add(label).add(path_text(entry.path))
    if record is not None:
        for output in record.owned_outputs:
            if output.kind == "hkcu":
                deleting.add("Windows uninstall registration").add(
                    Text(output.path)
                )
            elif output.kind in {"command", "shortcut"}:
                path = Path(output.path)
                if path in seen or (
                    plan.complete and path.is_relative_to(plan.directory)
                ):
                    continue
                seen.add(path)
                deleting.add(
                    "Global command" if output.kind == "command" else "Shortcut"
                ).add(path_text(path))
    for entry in plan.inventory.retained:
        keeping.add(labels.get(entry.resource or "", "Retained directory")).add(
            path_text(entry.path)
        )
    if (
        record is not None
        and isinstance(record.active_runtime, EditableCheckout)
        and not remove_repository
    ):
        keeping.add("Editable checkout").add(
            path_text(record.active_runtime.project)
        )
        keeping.add("Development environment").add(
            path_text(record.active_runtime.environment)
        )
    if not keeping.children:
        keeping.add("No retained installation resources.")
    return root
