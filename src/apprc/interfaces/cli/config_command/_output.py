"""Output helpers for ``config storage list`` rows."""

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
from apprc.user_files.storage_roots.registry import (
    StorageRegistry,
    ordered_storage_names,
)


class StorageListRowPayload(TypedDict):
    """Machine-readable data for one registered storage row."""

    name: str
    active: bool
    root: str
    root_exists: bool
    storage_dotenv: str
    storage_dotenv_exists: bool


class StorageListPayload(TypedDict):
    """Machine-readable data emitted by ``config storage list --json``."""

    apprc_toml: str
    storages: list[StorageListRowPayload]


def storage_list_payload(
    registry: StorageRegistry,
    *,
    storage_dotenv_filename: str,
    active_storage_root: Path | None = None,
) -> StorageListPayload:
    """Return JSON-friendly named storage rows for ``config storage list``.

    :param registry: Storage table to serialize.
    :param storage_dotenv_filename: Dotenv filename expected inside each root.
    :param active_storage_root: Root selected by ``<APP>_STORAGE``, if known.
    :return: Machine-readable storage summary.
    """
    storages: list[StorageListRowPayload] = []
    active_root = (
        Path(active_storage_root).expanduser().resolve()
        if active_storage_root is not None
        else None
    )
    for name in ordered_storage_names(registry):
        record = registry.selected(name)
        record_root = Path(record.root).expanduser().resolve()
        storage_dotenv = record.root / storage_dotenv_filename
        storages.append(
            {
                "name": record.name,
                "active": active_root == record_root,
                "root": str(record.root),
                "root_exists": record.root.is_dir(),
                "storage_dotenv": str(storage_dotenv),
                "storage_dotenv_exists": storage_dotenv.is_file(),
            }
        )
    return {
        "apprc_toml": str(registry.path),
        "storages": storages,
    }


def print_storage_list(payload: StorageListPayload) -> None:
    """Print named storage rows in a readable text format.

    :param payload: Storage payload from :func:`storage_list_payload`.
    """
    console = Console(soft_wrap=True)
    console.print(_storage_detail_text("apprc_toml", payload["apprc_toml"]))
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
        branch.add(
            _storage_detail_text("storage_dotenv", storage["storage_dotenv"])
        )
        branch.add(
            _storage_bool_text(
                "storage_dotenv_exists",
                bool(storage["storage_dotenv_exists"]),
            )
        )
    console.print(tree)


def _storage_detail_text(key: str, value: object) -> Text:
    """Return one colored key/value line for storage list output.

    :param key: Display field name.
    :param value: Display field value.
    :return: Rich text with a styled key and plain value.
    """
    return Text.assemble((key, "dim cyan"), ": ", str(value))


def _storage_bool_text(key: str, value: bool) -> Text:
    """Return one colored boolean line for storage list output.

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
    :return: Rich text with the storage name and optional active marker.
    """
    label = Text(str(storage["name"]), style="bold")
    if storage["active"]:
        label.append(" [active]", style="green")
    return label
