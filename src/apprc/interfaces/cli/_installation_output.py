"""Human-facing installation output built from captured uninstall authority."""

from __future__ import annotations

import os
from pathlib import Path, PurePath
from typing import TYPE_CHECKING
from collections.abc import Mapping

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


def _add_path_tree(
    root: Tree, targets: Mapping[PurePath, tuple[str, str]]
) -> None:
    """Group captured targets by filesystem ancestry, folding unbranched parents.

    :param root: Presentation parent for the filesystem paths.
    :param targets: Captured paths mapped to action and explanation.
    """
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
                action, style="bold red" if action == "Delete" else "bold green"
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
