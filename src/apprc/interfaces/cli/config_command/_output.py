"""Output helpers for ``config workspace list`` rows."""

from __future__ import annotations

# == Standard Library ========================
from pathlib import Path
from typing import TypedDict

# == 3rd Party ===============================
import typer
from rich.console import Console
from rich.text import Text
from rich.tree import Tree

# == Internal ================================
from apprc.user_files.workspace_roots._io import ordered_workspace_names
from apprc.user_files.workspace_roots.model import WorkspaceRegistry


class WorkspaceListRowPayload(TypedDict):
    """Machine-readable data for one registered workspace row."""

    name: str
    active: bool
    root: str
    root_exists: bool
    workspace_dotenv: str
    workspace_dotenv_exists: bool


class WorkspaceListPayload(TypedDict):
    """Machine-readable data emitted by ``config workspace list --json``."""

    config_file: str
    workspaces: list[WorkspaceListRowPayload]


def workspace_list_payload(
    registry: WorkspaceRegistry,
    *,
    workspace_dotenv_filename: str,
    active_workspace_root: Path | None = None,
) -> WorkspaceListPayload:
    """Return JSON-friendly named-workspace rows.

    :param registry: Workspace table to serialize.
    :param workspace_dotenv_filename: Dotenv filename expected in each root.
    :param active_workspace_root: Root selected for the current invocation.
    :return: Machine-readable workspace summary.
    """
    workspaces: list[WorkspaceListRowPayload] = []
    active_root = (
        Path(active_workspace_root).expanduser().resolve()
        if active_workspace_root is not None
        else None
    )
    for name in ordered_workspace_names(registry):
        record = registry.selected(name)
        workspace_dotenv = record.root / workspace_dotenv_filename
        workspaces.append(
            {
                "name": record.name,
                "active": active_root == record.root.resolve(),
                "root": str(record.root),
                "root_exists": record.root.is_dir(),
                "workspace_dotenv": str(workspace_dotenv),
                "workspace_dotenv_exists": workspace_dotenv.is_file(),
            }
        )
    return {"config_file": str(registry.path), "workspaces": workspaces}


def print_workspace_list(payload: WorkspaceListPayload) -> None:
    """Print named workspace rows in a readable text format.

    :param payload: Workspace payload from :func:`workspace_list_payload`.
    """
    console = Console(soft_wrap=True)
    console.print(_workspace_detail_text("config_file", payload["config_file"]))
    workspaces = payload["workspaces"]
    if not workspaces:
        typer.echo("workspaces: <none>")
        return
    tree = Tree(Text("workspaces:", style="dim cyan"))
    for workspace in workspaces:
        branch = tree.add(_workspace_name_text(workspace))
        branch.add(_workspace_detail_text("root", workspace["root"]))
        branch.add(
            _workspace_bool_text("root_exists", workspace["root_exists"])
        )
        branch.add(
            _workspace_detail_text(
                "workspace_dotenv", workspace["workspace_dotenv"]
            )
        )
        branch.add(
            _workspace_bool_text(
                "workspace_dotenv_exists",
                workspace["workspace_dotenv_exists"],
            )
        )
    console.print(tree)


def _workspace_detail_text(key: str, value: object) -> Text:
    """Return one colored key/value line for workspace-list output."""
    return Text.assemble((key, "dim cyan"), ": ", str(value))


def _workspace_bool_text(key: str, value: bool) -> Text:
    """Return one colored boolean line for workspace-list output."""
    return Text.assemble(
        (key, "dim cyan"),
        ": ",
        (str(value).lower(), "green" if value else "red"),
    )


def _workspace_name_text(workspace: WorkspaceListRowPayload) -> Text:
    """Return a workspace branch label with an active marker."""
    label = Text(workspace["name"], style="bold")
    if workspace["active"]:
        label.append(" [active]", style="green")
    return label
