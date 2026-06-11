"""Output helpers for storage registry CLI commands."""

from __future__ import annotations

# == Standard Library ========================
from typing import TypedDict

# == 3rd Party ===============================
import typer
from rich.console import Console
from rich.text import Text
from rich.tree import Tree

# == Internal ================================
from apprc.config.storage.registry import StorageRegistry, ordered_storage_names


class StorageListRowPayload(TypedDict):
    """Machine-readable data for one registered storage row."""

    name: str
    default: bool
    root: str
    root_exists: bool
    local_env: str
    local_env_exists: bool


class StorageListPayload(TypedDict):
    """Machine-readable data emitted by ``config list --json``."""

    apprc_toml_path: str
    default_storage: str | None
    storages: list[StorageListRowPayload]


def storage_list_payload(
    registry: StorageRegistry,
    *,
    local_env_filename: str,
) -> StorageListPayload:
    """Return JSON-friendly registry rows for ``config list``.

    :param registry: User storage registry to serialize.
    :param local_env_filename: Dotenv filename expected inside each root.
    :return: Machine-readable registry summary.
    """
    storages: list[StorageListRowPayload] = []
    for name in ordered_storage_names(registry):
        record = registry.selected(name)
        local_env = record.root / local_env_filename
        storages.append(
            {
                "name": record.name,
                "default": record.name == registry.default_storage,
                "root": str(record.root),
                "root_exists": record.root.is_dir(),
                "local_env": str(local_env),
                "local_env_exists": local_env.is_file(),
            }
        )
    return {
        "apprc_toml_path": str(registry.path),
        "default_storage": registry.default_storage,
        "storages": storages,
    }


def print_storage_list(payload: StorageListPayload) -> None:
    """Print storage registry rows in a readable text format.

    :param payload: Registry payload from :func:`storage_list_payload`.
    """
    console = Console(soft_wrap=True)
    console.print(
        _storage_detail_text("apprc_toml_path", payload["apprc_toml_path"])
    )
    console.print(
        _storage_detail_text(
            "default_storage",
            payload["default_storage"] or "<none>",
        )
    )
    storages = payload["storages"]
    if not storages:
        typer.echo("storages: <none>")
        return
    tree = Tree(Text("storages:", style="dim cyan"))
    for storage in storages:
        branch = tree.add(_storage_name_text(storage))
        branch.add(_storage_detail_text("root", storage["root"]))
        branch.add(
            _storage_bool_text(
                "root_exists",
                bool(storage["root_exists"]),
            )
        )
        branch.add(_storage_detail_text("local_env", storage["local_env"]))
        branch.add(
            _storage_bool_text(
                "local_env_exists",
                bool(storage["local_env_exists"]),
            )
        )
    console.print(tree)


def _storage_detail_text(key: str, value: object) -> Text:
    """Return one colored key/value line for config list output.

    :param key: Display field name.
    :param value: Display field value.
    :return: Rich text with a styled key and plain value.
    """
    return Text.assemble((key, "dim cyan"), ": ", str(value))


def _storage_bool_text(key: str, value: bool) -> Text:
    """Return one colored boolean line for config list output.

    :param key: Display field name.
    :param value: Boolean value to show as ``true`` or ``false``.
    :return: Rich text with a styled key and colored boolean value.
    """
    style = "green" if value else "red"
    return Text.assemble(
        (key, "dim cyan"),
        ": ",
        (str(value).lower(), style),
    )


def _storage_name_text(storage: StorageListRowPayload) -> Text:
    """Return the display label for one storage tree branch.

    :param storage: JSON-friendly storage payload row.
    :return: Rich text with the storage name and optional default marker.
    """
    label = Text(str(storage["name"]), style="bold")
    if storage["default"]:
        label.append(" [setup/editor default]", style="green")
    return label
