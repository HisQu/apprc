"""Stdlib-only final step for an already-retired installation namespace."""

from __future__ import annotations

import argparse
import errno
import json
import os
import stat
from pathlib import Path


def _assert_no_links(path: Path) -> None:
    """Reject traversal, symlinks and Windows reparse points before inspection."""
    if ".." in path.parts:
        raise ValueError(f"Finalizer refuses traversal: {path}.")
    absolute = path.expanduser().absolute()
    for candidate in (absolute, *absolute.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            os.name == "nt"
            and metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"Finalizer refuses linked path: {candidate}.")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys instead of silently choosing one authority."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate finalization plan key: {key}.")
        result[key] = value
    return result


def main() -> None:
    """Remove the exact namespace only when it is genuinely empty.

    Core retirement owns generation-aware operation-lock cleanup. This leaf
    runs afterward and attempts only an empty installation-directory removal.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    arguments = parser.parse_args()
    if (
        not arguments.plan.is_absolute()
        or ".." in arguments.plan.parts
        or not arguments.directory.is_absolute()
        or ".." in arguments.directory.parts
    ):
        raise ValueError(
            "Finalization paths must be absolute without traversal."
        )
    plan_path = arguments.plan
    if (
        plan_path.name != "finalization.json"
        or plan_path.parent.name != "recovery"
    ):
        raise ValueError(
            "Finalization plan is not at its exact recovery address."
        )
    _assert_no_links(plan_path)
    if os.name != "nt" and (
        not plan_path.is_file() or plan_path.parent.stat().st_mode & 0o077
    ):
        raise ValueError(
            "Finalization plan is not in a private recovery directory."
        )
    metadata = plan_path.stat()
    if os.name != "nt" and metadata.st_mode & 0o022:
        raise ValueError("Finalization plan is writable by another user.")
    value = json.loads(
        plan_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
    )
    if (
        not isinstance(value, dict)
        or set(value) != {"directory", "support"}
        or value["support"] != []
        or not isinstance(value["directory"], str)
    ):
        raise ValueError(
            "Finalization plan is malformed or grants support authority."
        )
    directory = Path(value["directory"])
    if not directory.is_absolute() or ".." in directory.parts:
        raise ValueError(
            "Finalization plan directory must be absolute without traversal."
        )
    if directory != arguments.directory:
        raise ValueError(
            "Finalizer may act only on the exact installation address."
        )
    _assert_no_links(directory)
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Installation address is not a real directory.")
    authority = directory / "installation.json"
    _assert_no_links(authority)
    if authority.exists():
        return
    # > Core retirement owns the lock directory; this leaf never touches it.
    try:
        directory.rmdir()
    except FileNotFoundError:
        return
    except OSError as error:
        if error.errno in {errno.ENOTEMPTY, errno.EEXIST} or getattr(
            error, "winerror", None
        ) in {145, 183}:
            return
        raise


if __name__ == "__main__":
    main()
