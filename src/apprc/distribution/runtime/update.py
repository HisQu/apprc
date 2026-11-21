"""Explicit updates for installed releases and registered source checkouts."""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import TYPE_CHECKING

import filelock

from apprc.definition.installation import (
    EditableCheckout,
    InstallationError,
    InstallationRecord,
    RuntimeSlot,
)
from apprc.definition.resolution import resolve_editable_environment
from apprc.distribution._release_assets import (
    _inspect_native_products,
    download_release_setup,
)
from apprc.distribution.runtime._process_waiter import update_process_identities
from apprc.distribution.runtime._update_handoff import (
    UpdateWork,
    _git_value,
    run_update,
)
from apprc.distribution.runtime.backend import (
    runtime_command,
    runtime_environment,
    runtime_interpreter,
)
from apprc.distribution.runtime.installation import (
    recorded_command_directory,
    require_update_record,
)
from apprc.user_files.app_home.locations import assert_no_links
from apprc.user_files.app_home.permissions import set_windows_private_acl
from apprc.user_files.installation.coordination import installation_lock

if TYPE_CHECKING:
    from apprc.distribution.models import NativeBinding
    from apprc.distribution.native import NativeTarget
    from apprc.services.installation import InstallationManager


def _tool(name: str, environment: Mapping[str, str]) -> str:
    path = shutil.which(name, path=environment.get("PATH"))
    if path is None:
        raise InstallationError(f"{name} is required for an editable update.")
    return str(Path(path).resolve(strict=True))


def _retry_command(arguments: list[str]) -> str:
    if os.name == "nt":
        return "& " + " ".join(
            "'" + argument.replace("'", "''") + "'" for argument in arguments
        )
    return shlex.join(arguments)


def _managed_update(
    record: InstallationRecord,
    active: RuntimeSlot,
    binding: NativeBinding,
    stage: Path,
    environment: Mapping[str, str],
    work: UpdateWork,
    confirm: Callable[[str], None],
    *,
    regular_app_id: str,
) -> bool:
    from packaging.version import InvalidVersion, Version

    source = binding.release_source
    if source is None:
        raise InstallationError(
            "This setup has no publisher release source. Run a newer verified "
            "setup or the publisher's one-line installer to update."
        )
    if platform.machine().casefold() not in {
        "x86_64",
        "amd64",
    } or sys.platform not in {"win32", "linux"}:
        raise InstallationError(
            "Release updates require x86-64 Linux or Windows."
        )
    target: NativeTarget = (
        "x86_64-pc-windows-msvc"
        if sys.platform == "win32"
        else "x86_64-unknown-linux-gnu"
    )
    if (
        binding.identity != record.identity
        or binding.command_name != record.command_name
    ):
        raise InstallationError(
            "The manager binding differs from the installed product."
        )
    setup, digest = download_release_setup(
        source,
        app_id=regular_app_id,
        target=target,
        directory=stage,
        environment=environment,
    )
    regular, preview = _inspect_native_products(
        setup, app_id=regular_app_id, target=target
    )
    is_preview = regular.identity != record.identity
    candidate = preview if is_preview else regular
    if (
        candidate is None
        or candidate.identity != record.identity
        or candidate.command_name != record.command_name
    ):
        raise InstallationError(
            "The downloaded setup does not match the installed product."
        )
    if active.version is None:
        raise InstallationError("The installed runtime version is unavailable.")
    try:
        current_version, next_version = (
            Version(active.version),
            Version(candidate.version),
        )
    except InvalidVersion as error:
        raise InstallationError(
            "The installed or publisher version is invalid."
        ) from error
    if next_version < current_version:
        raise InstallationError(
            f"Published version {candidate.version} is older than installed {active.version}."
        )
    if next_version == current_version:
        if candidate.source != active.source:
            raise InstallationError(
                f"The published source changed at version {active.version}. The publisher must bump the version."
            )
        print(f"Already up to date ({active.version}).")
        return False
    confirm(
        f"Update {record.command_name} from {active.version} to {candidate.version}?"
    )
    if os.name != "nt":
        setup.chmod(0o700)
    work["setup_digest"] = digest
    work["command"] = [
        str(setup),
        *(["--preview"] if is_preview else []),
        "--yes",
        "--skip-setup",
        "--apprc-update-generation",
        str(record.generation_id),
        "--apprc-update-revision",
        work["revision"],
    ]
    return True


def _editable_update(
    record: InstallationRecord,
    runtime: EditableCheckout,
    environment: dict[str, str],
    work: UpdateWork,
    maintenance_group: str,
    confirm: Callable[[str], None],
) -> None:
    project, prefix = runtime.project, runtime.environment
    assert_no_links(project)
    assert_no_links(prefix)
    if not resolve_editable_environment(project).samefile(prefix):
        raise InstallationError(
            "The recorded environment no longer matches the checkout."
        )
    git = _tool("git", environment)
    cwd = project
    if _git_value(
        git,
        cwd,
        "status",
        "--porcelain",
        "--untracked-files=normal",
        env=environment,
    ):
        raise InstallationError(
            f"The checkout is dirty. Commit or move local changes in {project} before updating."
        )
    try:
        branch = _git_value(git, cwd, "symbolic-ref", "HEAD", env=environment)
        upstream = _git_value(
            git,
            cwd,
            "rev-parse",
            "--symbolic-full-name",
            "@{upstream}",
            env=environment,
        )
    except subprocess.CalledProcessError as error:
        raise InstallationError(
            "The checkout must be on a branch with a configured upstream."
        ) from error
    head = _git_value(git, cwd, "rev-parse", "HEAD", env=environment)
    subprocess.run([git, "-C", str(cwd), "fetch"], env=environment, check=True)
    candidate = _git_value(
        git,
        cwd,
        "rev-parse",
        "--verify",
        "@{upstream}^{commit}",
        env=environment,
    )
    if subprocess.run(
        [git, "-C", str(cwd), "merge-base", "--is-ancestor", head, candidate],
        env=environment,
        check=False,
    ).returncode:
        raise InstallationError(
            "The branch cannot fast-forward to its upstream. Reconcile it in Git before updating."
        )
    uv = _tool("uv", environment)
    if os.name == "nt" and Path(uv).is_relative_to(prefix):
        raise InstallationError(
            "Use a standalone uv executable outside the editable environment."
        )
    environment["UV_PROJECT_ENVIRONMENT"] = str(prefix)
    sync = [uv, "sync", "--locked"]
    # > A current checkout and environment can still need registration.
    # > Reuse confirmed registration and its idempotent initialization.
    change = (
        f"Fast-forward {head[:12]} to {candidate[:12]} and synchronize"
        if head != candidate
        else "The checkout is current. Synchronize"
    )
    confirm(
        f"{change} the recorded environment at {prefix} using the project's default dependency selection and refresh registration?"
    )
    command_dir = recorded_command_directory(
        record, Path(work["authority"]).parent
    )
    if command_dir is None:
        raise InstallationError(
            "The editable installation has no recorded command location."
        )
    command = str(
        runtime_command(
            Path(work["authority"]).parent, runtime, record.command_name
        )
    )
    refresh = [
        command,
        maintenance_group,
        "install",
        "--editable",
        "--yes",
        "--skip-setup",
        "--command-directory",
        str(command_dir),
    ]
    retry_env = (
        f"$env:UV_PROJECT_ENVIRONMENT = '{str(prefix).replace(chr(39), chr(39) * 2)}';"
        if os.name == "nt"
        else f"UV_PROJECT_ENVIRONMENT={shlex.quote(str(prefix))}"
    )
    work.update(
        workdir=str(cwd),
        current_head=head,
        branch=branch,
        upstream=upstream,
        candidate=candidate,
        git=git,
        sync=sync,
        validate_environment=[
            str(runtime_interpreter(Path(work["authority"]).parent, runtime)),
            "-I",
            "-c",
            "from pathlib import Path; import sys; "
            "from apprc.definition.resolution import resolve_editable_environment; "
            "sys.exit(0 if resolve_editable_environment(Path(sys.argv[1])).samefile(sys.argv[2]) else 1)",
            str(project),
            str(prefix),
        ],
        sync_retry=f"{retry_env} {_retry_command(sync)}",
        registration_retry=_retry_command(refresh),
        command=[
            *refresh,
            "--apprc-update-generation",
            str(record.generation_id),
            "--apprc-update-revision",
            work["revision"],
        ],
    )


def _stage_windows_helper(stage: Path) -> Path:
    """Stage the Windows helper from an installed package or native archive."""
    from inspect import getsource

    from apprc.distribution.runtime import _process_waiter, _update_handoff
    from apprc.user_files.app_home import locations
    from apprc.user_files.installation import _namespace_lock

    script = stage / "handoff.py"
    script.write_text(getsource(_update_handoff), encoding="utf-8")
    (stage / "apprc").mkdir()
    (stage / "apprc" / "__init__.py").touch()
    for module in (_process_waiter, locations, _namespace_lock):
        destination = stage.joinpath(*module.__name__.split(".")).with_suffix(
            ".py"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(getsource(module), encoding="utf-8")
    shutil.copytree(
        Path(filelock.__file__).parent,
        stage / "filelock",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return script


def _hand_off_windows(
    stage: Path,
    work: UpdateWork,
    environment: dict[str, str],
    executables: tuple[Path, ...],
    editable_environment: Path | None,
    forbidden: tuple[Path, ...],
) -> None:
    external = (Path(sys.base_prefix) / "python.exe").resolve(strict=True)
    if any(external.is_relative_to(path) for path in forbidden):
        raise InstallationError(
            "No independent interpreter is available for the Windows update."
        )
    processes = update_process_identities(executables, editable_environment)
    script = _stage_windows_helper(stage)
    plan = stage / "update.json"
    plan.write_text(
        json.dumps({"processes": processes, "work": work}), encoding="utf-8"
    )
    process = subprocess.Popen(
        [str(external), "-I", str(script), str(plan)],
        cwd=stage.parent,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    incoming, outgoing = process.stdin, process.stdout
    assert incoming is not None and outgoing is not None
    ready: Queue[str] = Queue()
    Thread(target=lambda: ready.put(outgoing.readline()), daemon=True).start()
    try:
        if ready.get(timeout=30) != "APPRC-UPDATE-READY\n":
            raise InstallationError(
                "The Windows update helper rejected the handoff."
            )
        incoming.write("EXIT\n")
        incoming.flush()
    except (Empty, OSError, ValueError) as error:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        raise InstallationError(
            "Could not transfer the update to the Windows helper."
        ) from error
    finally:
        incoming.close()
        outgoing.close()
    print(
        "Update handed off. The update process will report the result.",
        flush=True,
    )


def update_application(
    manager: InstallationManager,
    *,
    binding: NativeBinding | None,
    regular_app_id: str | None,
    maintenance_group: str,
    confirm: Callable[[str], None],
) -> int:
    """Update the ready installation associated with this command."""
    observed = manager.inspect()
    if observed.record is None or observed.revision is None:
        raise InstallationError(
            "No ready installation is registered for this application."
        )
    with installation_lock(manager.directory):
        inspection = manager.inspect()
        record = inspection.require_usable()
        if record is None or inspection.revision is None:
            raise InstallationError(
                "No ready installation is registered for this application."
            )
        revision = inspection.revision
        require_update_record(inspection, (record.generation_id, revision))
        command_dir = recorded_command_directory(record, manager.directory)
    runtime = record.active_runtime
    editable = runtime if isinstance(runtime, EditableCheckout) else None
    executables = tuple(
        Path(item.path)
        for item in record.owned_outputs
        if item.kind == "command"
    )
    forbidden = (manager.directory, *((command_dir,) if command_dir else ()))
    if editable is not None:
        forbidden += (editable.project, editable.environment)
    forbidden = tuple(path.resolve() for path in forbidden)
    environment = runtime_environment(manager.environment)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "UV_GROUP",
        "UV_NO_GROUP",
        "UV_NO_DEFAULT_GROUPS",
        "UV_ALL_GROUPS",
        "UV_EXTRA",
        "UV_NO_EXTRA",
        "UV_ALL_EXTRAS",
        "UV_NO_DEV",
        "UV_DEV",
        "UV_ONLY_DEV",
        "UV_ONLY_GROUP",
        "UV_INEXACT",
        "UV_NO_EDITABLE",
        "UV_NO_INSTALL_PROJECT",
        "UV_NO_INSTALL_WORKSPACE",
        "UV_NO_INSTALL_PACKAGE",
    ):
        environment.pop(key, None)
    if runtime is None or (binding is None and editable is None):
        raise InstallationError(
            "Run update through the installed application command."
        )
    stage_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    if any(stage_parent.is_relative_to(path) for path in forbidden):
        raise InstallationError(
            "The temporary directory is inside the installation being updated."
        )
    stage = Path(tempfile.mkdtemp(prefix="apprc-update-", dir=stage_parent))
    handed_off = False
    try:
        if os.name == "nt":
            set_windows_private_acl(stage)
        work = UpdateWork(
            command=[],
            workdir=str(stage_parent),
            setup_digest=None,
            authority=str(manager.directory / "installation.json"),
            revision=revision,
            current_head=None,
            branch=None,
            upstream=None,
            candidate=None,
            git=None,
            sync=[],
            validate_environment=[],
            sync_retry="",
            registration_retry="",
        )
        if editable is not None:
            _editable_update(
                record, editable, environment, work, maintenance_group, confirm
            )
        else:
            assert binding is not None and isinstance(runtime, RuntimeSlot)
            if not _managed_update(
                record,
                runtime,
                binding,
                stage,
                environment,
                work,
                confirm,
                regular_app_id=regular_app_id or binding.identity.app_id,
            ):
                return 0
        if os.name == "nt":
            _hand_off_windows(
                stage,
                work,
                environment,
                executables,
                editable.environment if editable else None,
                forbidden,
            )
            handed_off = True
            return 0
        return run_update(work, environment)
    finally:
        if not handed_off:
            shutil.rmtree(stage, ignore_errors=True)
