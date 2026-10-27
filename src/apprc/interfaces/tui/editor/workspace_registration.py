"""Workspace registration workflows for the config editor TUI."""

from __future__ import annotations

# == Standard Library ========================
import asyncio
from pathlib import Path

# == 3rd Party ===============================
from rich.text import Text

from apprc.interfaces.tui._primitives import ConfirmScreen, WorkspaceNameScreen
from apprc.interfaces.tui._styles import lines_text, path_markup, path_text
from apprc.interfaces.tui.editor.workspace_base import WorkspaceWorkflowBase
from apprc.interfaces.tui.workspaces.selection import (
    ActivePathWorkspaceSelection,
)

# == Internal ================================
from apprc.user_files.env_files.files import read_env_file
from apprc.user_files.workspace_roots.paths import normalize_workspace_root_path


class WorkspaceRegistrationWorkflows(WorkspaceWorkflowBase):
    """Register directory-backed workspace roots in the editor."""

    async def register_active_workspace_flow(self) -> None:
        """Register the env-selected active workspace path by name."""
        if self.editor._require_workspace_registry() is None:
            return
        selection = self.editor.selection
        if not isinstance(selection, ActivePathWorkspaceSelection):
            self.editor.notify(
                "No active workspace path is selected.",
                severity="warning",
            )
            return
        await self.register_workspace_directory_flow(
            selection.root,
            default_name=self.editor._suggest_workspace_name(selection.root),
        )

    async def register_workspace_directory_flow(
        self,
        workspace_root: Path,
        *,
        default_name: str,
        directory_already_approved: bool = False,
    ) -> None:
        """Prompt for confirmation and register one live workspace root.

        :param workspace_root: Directory selected by the user.
        :param default_name: Suggested workspace selector.
        :param directory_already_approved: Whether a preceding setup flow
            already confirmed that this directory is safe to reuse.
        """
        registry = self.editor._require_workspace_registry()
        if registry is None:
            return
        guarded_root = (
            normalize_workspace_root_path(workspace_root).resolve()
            if directory_already_approved
            else await self.guard_workspace_directory(workspace_root)
        )
        if guarded_root is None:
            return
        name_result = await self.editor.push_screen_wait(
            WorkspaceNameScreen(
                default_name=default_name,
                message="Choose the workspace name used by --workspace.",
            )
        )
        if name_result is None:
            return
        name = name_result.name
        if name in registry.workspaces or name in registry.archived_workspaces:
            self.editor.notify(
                f"Workspace name {name!r} is already in use.",
                severity="error",
                markup=False,
            )
            return
        try:
            self.editor.workspace_registry = await asyncio.to_thread(
                self.require_workspace_manager().register_workspace,
                name=name,
                root=guarded_root,
            )
        except (TypeError, ValueError, OSError) as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            for note in _exception_notes(exc):
                self.editor.notify(note, severity="warning", markup=False)
            return
        await self.editor._refresh_workspace_list(select_name=name)
        self.editor.notify(f"Registered workspace {name!r}")

    async def guard_workspace_directory(
        self, workspace_root: Path
    ) -> Path | None:
        """Confirm the requested directory is safe to register.

        :param workspace_root: User-entered workspace path.
        :return: Safe path, or ``None`` when canceled.
        """
        try:
            root = normalize_workspace_root_path(workspace_root)
        except ValueError as exc:
            self.editor.notify(str(exc), severity="error", markup=False)
            return None
        if not root.exists():
            parent = root.parent
            if parent.exists():
                action = await self.editor.push_screen_wait(
                    ConfirmScreen(
                        title="Directory does not exist",
                        message=Text.assemble(
                            "Directory does not exist, create new directory "
                            "inside ",
                            path_text(parent),
                            "?",
                        ),
                        actions=(("create", "Create", "primary"),),
                    )
                )
                return root if action == "create" else None
            self.editor.notify(
                f"Path not found! {path_markup(parent)}",
                severity="error",
            )
            return None
        resolved_root = root.resolve()
        if not resolved_root.is_dir():
            self.editor.notify(
                "Workspace path exists but is not a directory: "
                f"{path_markup(resolved_root)}",
                severity="error",
            )
            return None
        if not any(resolved_root.iterdir()):
            return resolved_root

        dotenv_filename = self.editor.apprc.schema.workspace_dotenv_filename
        env_path = resolved_root / dotenv_filename
        if env_path.is_file():
            keys = list(read_env_file(env_path))[:10]
            preview = ", ".join(keys) if keys else "<none>"
            message = (
                f"Workspace not empty, found {dotenv_filename} with these env "
                f"vars: {preview}.\n"
                "All these workspace env vars will be exported on runtime. "
                "Proceed?"
            )
        else:
            message = lines_text(
                "Workspace not empty, but no "
                f"{dotenv_filename} found, initialize with empty "
                f"{dotenv_filename}?",
                path_text(resolved_root),
            )
        action = await self.editor.push_screen_wait(
            ConfirmScreen(
                title="Confirm workspace directory",
                message=message,
                actions=(("proceed", "Proceed", "warning"),),
            )
        )
        return resolved_root if action == "proceed" else None


def _exception_notes(exc: BaseException) -> tuple[str, ...]:
    """Return notes attached by lower-level cleanup code.

    :param exc: Exception that may carry ``BaseException.add_note()`` details.
    :return: Attached notes, or an empty tuple when none exist.
    """
    return tuple(getattr(exc, "__notes__", ()))
