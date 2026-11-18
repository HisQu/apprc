"""Human-facing installation progress, results and uninstall previews."""

from __future__ import annotations

import os
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
    from rich.console import Console

    stream = typer.get_text_stream("stderr" if error else "stdout")
    override = ctx.color if ctx is not None else installation_color.get()
    color = (
        stream.isatty() if override is None else override
    ) and "NO_COLOR" not in os.environ
    return Console(
        file=stream,
        force_terminal=color,
        color_system="standard" if color else None,
        markup=False,
        highlight=False,
        soft_wrap=True,
    )


class InstallationProgressOutput:
    """Render sequenced install stages with semantic colors and a plain fallback."""

    def __init__(self, ctx: typer.Context | None, name: str, mode: str) -> None:
        self._ctx = ctx
        self._name = name
        self._mode = mode
        self._stage = 0
        self._version = ""
        self._write(f"{name} · {mode.title()} installation")

    def _write(
        self,
        message: str,
        *,
        style: str = "",
        prefix: str = "",
        path: str | Path | None = None,
        error: bool = False,
    ) -> None:
        try:
            from rich.text import Text

            from apprc.interfaces import _terminal_styles as styles

            console = installation_console(self._ctx, error=error)
        except ImportError:
            stream = typer.get_text_stream("stderr" if error else "stdout")
            print(
                prefix + message + (f": {path}" if path is not None else ""),
                file=stream,
                flush=True,
            )
            return
        color = {
            "stage": styles.STAGE_STYLE,
            "warning": styles.WARNING_STYLE,
            "success": styles.SUCCESS_STYLE,
            "error": styles.ERROR_STYLE,
            "detail": styles.LABEL_STYLE,
        }.get(style, "")
        line = Text.assemble((prefix, styles.SUCCESS_STYLE), (message, color))
        if path is not None:
            line.append(": " if message else "")
            line.append_text(styles.path_text(path))
        console.print(line)

    def __call__(self, event: InstallProgress) -> None:
        if event.kind == "version":
            self._version = event.message
        elif event.kind == "stage":
            self._stage += 1
            self._write(f"\n{self._stage}. {event.message}", style="stage")
        elif event.kind == "result":
            self._write(
                event.message, prefix=f"   {event.status:<10} ", path=event.path
            )
        elif event.kind == "warning":
            self._write(
                f"Warning: {event.message}", style="warning", error=True
            )
        else:
            self._write(f"   {event.message}", style="detail")

    def complete(self) -> None:
        """Confirm the usable, committed install."""
        product = (
            f"{self._name} {self._version}" if self._version else self._name
        )
        self._write(
            f"\n{product} {self._mode} installation complete.", style="success"
        )

    def failed(self, message: str) -> None:
        """Display the installation failure, including any recovery notes."""
        self._write(
            f"Installation failed: {message}", style="error", error=True
        )


def print_installation_path(
    ctx: typer.Context, label: str, path: str | Path
) -> None:
    """Print one explicitly identified filesystem path with canonical styling.

    :param ctx: Active command context.
    :param label: Plain description of the path.
    :param path: Captured filesystem path.
    """
    from rich.text import Text

    from apprc.interfaces._terminal_styles import path_text

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
    from rich.text import Text

    from apprc.interfaces._terminal_styles import path_text

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
