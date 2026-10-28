"""TOML IO for AppRC workspace registries."""

from __future__ import annotations

# == Standard Library ========================
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

# == Internal ================================
from apprc.user_files.app_home.locations import write_text_atomic
from apprc.user_files.workspace_roots._naming import validate_workspace_name
from apprc.user_files.workspace_roots.model import (
    ArchivedWorkspaceRecord,
    WorkspaceRecord,
    WorkspaceRegistry,
)
from apprc.user_files.workspace_roots.paths import resolve_workspace_root_path

_REGISTRY_TOP_LEVEL_KEYS = frozenset(
    {
        "archived_workspaces",
        "schema_version",
        "selected_workspace",
        "workspaces",
    }
)

_LEGACY_REGISTRY_KEYS = frozenset(
    {"archived_storages", "selected_storage", "storages"}
)


def load_workspace_registry_or_empty(path: Path) -> WorkspaceRegistry:
    """Read a workspace registry, or return an empty one when absent."""
    registry_path = Path(path).expanduser()
    if not registry_path.is_file():
        return WorkspaceRegistry(path=registry_path, workspaces={})
    try:
        data = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Failed to parse workspace registry {registry_path}: {exc}"
        ) from exc
    return _registry_from_toml(data=data, path=registry_path)


def write_workspace_registry(registry: WorkspaceRegistry) -> Path:
    """Persist one deterministic schema-v1 workspace registry atomically.

    :param registry: Complete registry snapshot to serialize.
    :return: Written registry path.
    """
    return write_text_atomic(registry.path, render_workspace_registry(registry))


def ordered_workspace_names(registry: WorkspaceRegistry) -> list[str]:
    """Return registered workspace names in stable order."""
    return sorted(registry.workspaces)


def _registry_from_toml(
    *,
    data: Mapping[str, object],
    path: Path,
) -> WorkspaceRegistry:
    """Build a typed registry from schema-v1 TOML data."""
    if set(data) & _LEGACY_REGISTRY_KEYS:
        raise ValueError(
            f"{path}: legacy workspace schema is unsupported; "
            "workspace registries require schema_version = 1."
        )
    unknown_keys = sorted(set(data) - _REGISTRY_TOP_LEVEL_KEYS)
    if unknown_keys:
        unknown_text = ", ".join(unknown_keys)
        supported_text = ", ".join(sorted(_REGISTRY_TOP_LEVEL_KEYS))
        raise ValueError(
            f"{path}: unsupported top-level registry key(s): {unknown_text}. "
            f"Supported keys: {supported_text}."
        )
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError(f"{path}: schema_version must be integer 1.")

    selected_workspace = _optional_toml_string(
        data=data,
        key="selected_workspace",
        path=path,
    )
    raw_workspaces = _toml_table(data=data, key="workspaces", path=path)
    workspaces: dict[str, WorkspaceRecord] = {}
    for name, raw_record in raw_workspaces.items():
        validate_workspace_name(name)
        record = _toml_record_table(
            raw_record=raw_record,
            path=path,
            section="workspaces",
            name=name,
        )
        raw_root = _toml_string_field(
            record=record,
            path=path,
            section="workspaces",
            name=name,
            field="root",
        )
        workspaces[name] = WorkspaceRecord(
            name=name,
            root=resolve_workspace_root_path(raw_root, base=path.parent),
        )
    if selected_workspace is not None and selected_workspace not in workspaces:
        raise ValueError(
            f"{path}: selected_workspace {selected_workspace!r} is not registered."
        )

    raw_archived = _toml_table(
        data=data,
        key="archived_workspaces",
        path=path,
    )
    archived_workspaces: dict[str, ArchivedWorkspaceRecord] = {}
    for name, raw_record in raw_archived.items():
        validate_workspace_name(name)
        record = _toml_record_table(
            raw_record=raw_record,
            path=path,
            section="archived_workspaces",
            name=name,
        )
        raw_archive = _toml_string_field(
            record=record,
            path=path,
            section="archived_workspaces",
            name=name,
            field="archive",
        )
        raw_source_root = _toml_string_field(
            record=record,
            path=path,
            section="archived_workspaces",
            name=name,
            field="source_root",
        )
        archived_workspaces[name] = ArchivedWorkspaceRecord(
            name=name,
            archive=resolve_workspace_root_path(raw_archive, base=path.parent),
            source_root=resolve_workspace_root_path(
                raw_source_root,
                base=path.parent,
            ),
        )
    return WorkspaceRegistry(
        path=path,
        workspaces=workspaces,
        selected_workspace=selected_workspace,
        archived_workspaces=archived_workspaces,
    )


def _optional_toml_string(
    *,
    data: Mapping[str, object],
    key: str,
    path: Path,
) -> str | None:
    """Return one optional non-empty top-level string.

    :param data: Parsed TOML mapping.
    :param key: Field name to inspect.
    :param path: Registry path used in errors.
    :return: String value, or ``None`` when absent.
    :raises ValueError: If the field is not a non-empty string.
    """
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: {key} must be a non-empty string.")
    return value


def _toml_table(
    *,
    data: Mapping[str, object],
    key: str,
    path: Path,
) -> Mapping[str, object]:
    """Return one top-level TOML table or raise a registry schema error."""
    raw_table = data.get(key, {})
    if not isinstance(raw_table, Mapping):
        raise ValueError(f"{path}: {key} must be a table.")
    return cast(Mapping[str, object], raw_table)


def _toml_record_table(
    *,
    raw_record: object,
    path: Path,
    section: str,
    name: str,
) -> Mapping[str, object]:
    """Return one nested record table or raise a registry schema error."""
    if not isinstance(raw_record, Mapping):
        raise ValueError(f"{path}: {section}.{name} must be a table.")
    return cast(Mapping[str, object], raw_record)


def _toml_string_field(
    *,
    record: Mapping[str, object],
    path: Path,
    section: str,
    name: str,
    field: str,
) -> str:
    """Return one required string field or raise a registry schema error."""
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: {section}.{name}.{field} must be a string.")
    return value


def render_workspace_registry(registry: WorkspaceRegistry) -> str:
    """Return deterministic TOML text for schema v1."""
    lines = ["schema_version = 1"]
    if registry.selected_workspace is not None:
        lines.append(
            f"selected_workspace = {_toml_string(registry.selected_workspace)}"
        )
    for name in sorted(registry.workspaces):
        record = registry.workspaces[name]
        lines.extend(
            [
                "",
                f"[workspaces.{name}]",
                f"root = {_toml_string(_stored_path(record.root, registry.path))}",
            ]
        )
    for name in sorted(registry.archived_workspaces):
        record = registry.archived_workspaces[name]
        lines.extend(
            [
                "",
                f"[archived_workspaces.{name}]",
                f"archive = {_toml_string(_stored_path(record.archive, registry.path))}",
                "source_root = "
                f"{_toml_string(_stored_path(record.source_root, registry.path))}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _stored_path(path: Path, registry_path: Path) -> str:
    """Return an internal path relative to ``apprc.toml`` when possible.

    :param path: Resolved workspace or archive path.
    :param registry_path: AppRC TOML path.
    :return: Portable registry spelling.
    """
    resolved = path.expanduser().absolute()
    base = registry_path.parent.expanduser().absolute()
    try:
        return str(resolved.relative_to(base))
    except ValueError:
        return str(resolved)


def _toml_string(value: str) -> str:
    """Return a TOML-compatible basic string."""
    return json.dumps(value)
