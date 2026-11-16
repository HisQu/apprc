"""Stdlib-only final step for an already-retired installation namespace."""

from __future__ import annotations

import argparse
import errno
import json
import os
import stat
from pathlib import Path
from uuid import UUID


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


def finalize_namespace(
    plan_path: Path,
    directory: Path,
    *,
    expected_app_id: str | None = None,
) -> None:
    """Remove the exact namespace only when it is genuinely empty.

    Core retirement owns generation-aware operation-lock cleanup. This leaf
    runs afterward and attempts only an empty installation-directory removal.

    :param plan_path: Private exact finalization plan outside the namespace.
    :param directory: Exact installation address whose authority was retired.
    :param expected_app_id: Authenticated native product identity, when available.
    """
    if (
        not plan_path.is_absolute()
        or ".." in plan_path.parts
        or not directory.is_absolute()
        or ".." in directory.parts
    ):
        raise ValueError(
            "Finalization paths must be absolute without traversal."
        )
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
    generation_id = (
        value.get("generation_id") if isinstance(value, dict) else None
    )
    app_id = value.get("app_id") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"directory", "app_id", "generation_id", "support"}
        or value["support"] != []
        or not isinstance(value["directory"], str)
        or not isinstance(app_id, str)
        or not app_id
        or (expected_app_id is not None and app_id != expected_app_id)
        or not isinstance(generation_id, str)
    ):
        raise ValueError(
            "Finalization plan is malformed or grants support authority."
        )
    try:
        if str(UUID(generation_id)) != generation_id:
            raise ValueError(
                "Finalization generation identity is not canonical."
            )
    except ValueError as error:
        raise ValueError(
            "Finalization generation identity is malformed."
        ) from error
    saved_directory = Path(value["directory"])
    if not saved_directory.is_absolute() or ".." in saved_directory.parts:
        raise ValueError(
            "Finalization plan directory must be absolute without traversal."
        )
    if saved_directory != directory:
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


def main() -> None:
    """Run the finalizer command for compatibility with stdlib invocation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--repository-plan", type=Path)
    parser.add_argument("--parent", type=int)
    parser.add_argument("--parent-token")
    arguments = parser.parse_args()
    if arguments.repository_plan is not None:
        finalize_repository(arguments.repository_plan, arguments.parent, arguments.parent_token)
    else:
        if arguments.plan is None or arguments.directory is None:
            parser.error("--plan and --directory are required")
        finalize_namespace(arguments.plan, arguments.directory)


def finalize_repository(proof: Path, parent: int, token: str) -> None:
    """Wait for the uninstall helper and delete its explicitly selected checkout.

    :param proof: Private committed deletion proof outside the repository.
    :param parent: Exact originating helper process.
    :param token: Captured process identity protecting against PID reuse.
    """
    import hashlib
    import shutil
    import sys
    import importlib.util
    spec = importlib.util.spec_from_file_location("_apprc_process_waiter", Path(__file__).with_name("_process_waiter.py"))
    if spec is None or spec.loader is None:
        raise ValueError("Staged process waiter is unavailable.")
    process_waiter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(process_waiter)

    _assert_no_links(proof)
    if proof.name != "repository.json" or proof.parent.name != "recovery":
        raise ValueError("Repository proof has an invalid recovery address.")
    if os.name != "nt" and proof.parent.stat().st_mode & 0o077:
        raise ValueError("Repository proof is not private.")
    value = json.loads(proof.read_text(), object_pairs_hook=_unique_object)
    if set(value) != {"directory", "app_id", "generation_id", "repository", "revision"}:
        raise ValueError("Repository proof has incompatible fields.")
    repository = Path(value["repository"])
    if not repository.is_absolute() or repository in {Path(repository.anchor), Path.home()}:
        raise ValueError("Repository deletion has an unsafe root.")
    for survivor in (proof, Path(__file__), Path(sys.executable), Path(sys.prefix), Path(sys.base_prefix), Path.cwd()):
        if survivor == repository or survivor.is_relative_to(repository):
            raise ValueError("Repository finalizer overlaps its target.")
    if (Path(value["directory"]) / "installation.json").exists():
        raise ValueError("Repository removal precedes installation retirement.")
    waiter = process_waiter._open_process_waiter(parent, token)
    process_waiter._wait_open_process(waiter)
    if (Path(value["directory"]) / "installation.json").exists():
        raise ValueError("A new installation exists; repository deletion was cancelled.")
    _assert_no_links(repository)
    if repository.exists():
        metadata = repository.stat()
        identity = hashlib.sha256(f"{metadata.st_dev}:{metadata.st_ino}".encode()).hexdigest()
        if identity != value["revision"]:
            raise ValueError("Repository directory changed after consent.")
        shutil.rmtree(repository)
    print(f"Repository removed: {repository}", file=sys.stderr, flush=True)
    shutil.rmtree(proof.parent.parent)


if __name__ == "__main__":
    main()
