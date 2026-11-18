"""External finalization for retired namespaces and selected checkouts."""

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
    parser.add_argument("--cleanup-staging", action="store_true")
    parser.add_argument("--cleanup-only", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--retained-config", action="append", default=[])
    arguments = parser.parse_args()
    external = (
        arguments.repository_plan is not None or arguments.cleanup_staging
    )
    if external and (
        arguments.parent is None or arguments.parent_token is None
    ):
        parser.error("--parent and --parent-token are required")
    terminal = _load_peer("_uninstall_terminal") if external else None
    try:
        if arguments.repository_plan is not None:
            finalize_repository(
                arguments.repository_plan,
                arguments.parent,
                arguments.parent_token,
            )
        else:
            if arguments.plan is None or arguments.directory is None:
                parser.error("--plan and --directory are required")
            if arguments.cleanup_staging:
                process_waiter = _load_peer("_process_waiter")
                waiter = process_waiter._open_process_waiter(
                    arguments.parent, arguments.parent_token
                )
                process_waiter._wait_open_process(waiter)
            if arguments.cleanup_only:
                validate_partial_cleanup(arguments.plan, arguments.directory)
            else:
                finalize_namespace(arguments.plan, arguments.directory)
            if arguments.cleanup_staging:
                cleanup_staging(
                    arguments.plan.parent
                    if arguments.cleanup_only
                    else arguments.plan.parent.parent
                )
        if external:
            assert terminal is not None
            terminal.result_line("Uninstall completed.", style="success")
            for path in arguments.retained_config:
                terminal.result_line("Retained configuration", Path(path))
    except (OSError, ValueError) as error:
        if terminal is not None:
            terminal.result_line(
                f"Uninstall committed; finalization incomplete: {error}",
                style="warning",
            )
        raise
    finally:
        if external and arguments.wait:
            assert terminal is not None
            terminal.acknowledge()


def _load_peer(name: str):
    """Load one staged SDK module without importing the application package.

    :param name: Fixed SDK module name placed beside this leaf.
    :return: The actual loader-backed module.
    """
    import importlib.util

    path = Path(__file__).with_name(name + ".py")
    _assert_no_links(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("Staged finalization module is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _existing_namespace_directory(directory: Path) -> None:
    """Require the existing private namespace instead of recreating it.

    :param directory: Namespace or lock directory retained for this finalizer.
    """
    _assert_no_links(directory)
    metadata = directory.stat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Finalization namespace is not a directory.")
    if os.name != "nt" and (
        metadata.st_mode & 0o077 or metadata.st_uid != os.getuid()
    ):
        raise ValueError("Finalization namespace is not private.")


def finalize_repository(proof: Path, parent: int, token: str) -> None:
    """Delete an explicitly selected checkout under its installation lock.

    :param proof: Private committed deletion proof outside the checkout.
    :param parent: Exact originating helper process.
    :param token: Captured process identity protecting against PID reuse.
    """
    import hashlib
    import re
    import shutil
    import sys

    process_waiter = _load_peer("_process_waiter")
    namespace = _load_peer("_namespace_lock")
    _assert_no_links(proof)
    if proof.name != "repository.json" or proof.parent.name != "recovery":
        raise ValueError("Repository proof has an invalid recovery address.")
    if os.name != "nt" and (
        proof.parent.stat().st_mode & 0o077 or proof.stat().st_mode & 0o022
    ):
        raise ValueError("Repository proof is not private.")
    value = json.loads(proof.read_text(), object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or set(value) != {
        "directory",
        "app_id",
        "generation_id",
        "repository",
        "revision",
    }:
        raise ValueError("Repository proof has incompatible fields.")
    if (
        any(not isinstance(value[key], str) for key in value)
        or not value["app_id"]
        or str(UUID(value["generation_id"])) != value["generation_id"]
        or re.fullmatch(r"[0-9a-f]{64}", value["revision"]) is None
    ):
        raise ValueError("Repository proof has invalid identity fields.")
    repository = Path(value["repository"])
    directory = Path(value["directory"])
    if (
        not directory.is_absolute()
        or not repository.is_absolute()
        or repository in {Path(repository.anchor), Path.home()}
    ):
        raise ValueError("Repository deletion has an unsafe root.")
    for survivor in (
        directory,
        proof,
        Path(__file__),
        Path(sys.executable),
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path.cwd(),
    ):
        if survivor == repository or survivor.is_relative_to(repository):
            raise ValueError("Repository finalizer overlaps its target.")
    waiter = process_waiter._open_process_waiter(parent, token)
    process_waiter._wait_open_process(waiter)
    with namespace.namespace_lock(
        directory,
        prepare_directory=_existing_namespace_directory,
        guard_path=_assert_no_links,
    ):
        if (directory / "installation.json").exists():
            raise ValueError(
                "A new installation exists; repository deletion was cancelled."
            )
        _assert_no_links(repository)
        if repository.exists():
            metadata = repository.stat()
            identity = hashlib.sha256(
                f"{metadata.st_dev}:{metadata.st_ino}".encode()
            ).hexdigest()
            if identity != value["revision"]:
                raise ValueError("Repository directory changed after consent.")
            shutil.rmtree(repository)
        namespace.retire_held_lock(directory, guard_path=_assert_no_links)
    # > Only empty namespace cleanup follows physical lock retirement.
    if not (directory / "installation.json").exists():
        lock = directory / "locks" / "operation.lock"
        if os.name == "nt":
            lock.unlink(missing_ok=True)
        for candidate in (directory / "locks", directory):
            try:
                candidate.rmdir()
            except FileNotFoundError:
                pass
            except OSError as error:
                if error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                    raise
    terminal = _load_peer("_uninstall_terminal")
    terminal.result_line("Repository removed", repository, style="success")
    cleanup_staging(proof.parent.parent)


def validate_partial_cleanup(plan: Path, directory: Path) -> None:
    """Constrain partial-uninstall housekeeping to its exact staged envelope.

    Remaining installation authority is deliberately not retired or modified.

    :param plan: Existing private handoff envelope.
    :param directory: Recorded retained installation address.
    """
    _assert_no_links(plan)
    if (
        not plan.is_absolute()
        or plan.name != "handoff.json"
        or plan.parent != Path(__file__).parent
    ):
        raise ValueError(
            "Partial cleanup plan differs from the executing staging directory."
        )
    value = json.loads(plan.read_text(), object_pairs_hook=_unique_object)
    if (
        not isinstance(value, dict)
        or value.get("complete") is not False
        or value.get("directory") != str(directory)
    ):
        raise ValueError(
            "Partial cleanup requires its retained installation envelope."
        )
    if directory == plan.parent or directory.is_relative_to(plan.parent):
        raise ValueError("Retained installation overlaps staging cleanup.")


def cleanup_staging(staging: Path) -> None:
    """Remove only this private finalizer directory; leftover temp files warn.

    :param staging: Exact external staging directory containing this SDK leaf.
    """
    import shutil
    import sys

    _assert_no_links(staging)
    if not staging.is_absolute() or Path(__file__).parent != staging:
        raise ValueError(
            "Staging cleanup differs from the executing finalizer."
        )
    for survivor in (
        Path.cwd(),
        Path(sys.executable),
        Path(sys.prefix),
        Path(sys.base_prefix),
    ):
        if survivor == staging or survivor.is_relative_to(staging):
            raise ValueError(
                "Finalizer still depends on its staging directory."
            )
    terminal = _load_peer("_uninstall_terminal")
    try:
        shutil.rmtree(staging)
    except OSError as error:
        terminal.result_line(
            f"Warning: uninstall completed, but temporary cleanup failed ({error})",
            staging,
            style="warning",
        )


if __name__ == "__main__":
    main()
