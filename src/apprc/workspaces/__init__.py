"""Public workspace records and read-only registry inspection helpers."""

# ruff: noqa: F401

from apprc.user_files.workspace_roots._io import (
    load_workspace_registry_or_empty,
)
from apprc.user_files.workspace_roots._loading import (
    WorkspaceRegistryInspection,
    inspect_workspace_registry,
)
from apprc.user_files.workspace_roots.archive import (
    WorkspaceArchiveProgress,
    is_workspace_archive_path,
)
from apprc.user_files.workspace_roots.model import (
    ArchivedWorkspaceRecord,
    WorkspaceRecord,
    WorkspaceRegistry,
)
from apprc.user_files.workspace_roots.move import (
    WorkspaceMoveError,
    WorkspaceMoveResult,
)
from apprc.user_files.workspace_roots.selector import (
    MissingWorkspaceSelectorError,
    WorkspaceNotInitializedError,
    WorkspaceSelection,
    WorkspaceSelectorError,
)

from ._exports import PUBLIC_NAMES as __all__
