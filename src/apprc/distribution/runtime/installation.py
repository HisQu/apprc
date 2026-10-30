"""Composable uv-tool installation and recovery checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import subprocess
import tempfile
import shlex
from collections.abc import Callable, Collection, Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath

from apprc.definition.installation import (
    InstallationDiagnostic,
    InstallationError,
    InstallationInspection,
    InstalledSnapshot,
    InstallPlan,
    OperationContext,
    OperationStep,
    OwnedOutput,
)
from apprc.distribution.runtime.acquisition import (
    PreparedSource,
    _archive_inputs,
    _materialized_source_paths,
    _selected_project,
    _source_subdirectory,
    _sha256_file,
    _validate_content_addressed_origin,
    prepare_source,
    validate_requirement,
)
from apprc.distribution.runtime.backend import (
    external_base_python,
    inspect_uv_tools,
    install_uv_tool,
)
from apprc.distribution.runtime.probe import probe_installed_tool
from apprc.user_files.app_home.locations import (
    assert_no_links,
    write_bytes_atomic,
)
from apprc.user_files.app_home.permissions import windows_acl_is_private
from apprc.user_files.installation.codec import encode_operation_context
from apprc.user_files.installation.coordination import installation_lock
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.operations import (
    begin_operation,
    commit_installation,
    fail_operation,
    record_step,
)


def install_application(
    plan: InstallPlan,
    *,
    environment: Mapping[str, str],
    probe_path: Path,
    support_files: Mapping[PurePosixPath, bytes],
    python_requirement: str,
    after_source_acquired: Callable[[PreparedSource], None] | None = None,
    prepared_source: PreparedSource | None = None,
) -> InstallationInspection:
    """Execute one install transaction, optionally from caller-prepared source."""
    with installation_lock(plan.directory):
        return _install_application_locked(
            plan,
            environment=environment,
            probe_path=probe_path,
            support_files=support_files,
            python_requirement=python_requirement,
            after_source_acquired=after_source_acquired,
            prepared_source=prepared_source,
        )


def install_prepared_application(
    plan: InstallPlan,
    prepared: PreparedSource,
    *,
    environment: Mapping[str, str],
    probe_path: Path,
    support_files: Mapping[PurePosixPath, bytes],
    python_requirement: str,
) -> InstallationInspection:
    """Install a source acquired and prepared by the caller's explicit sequence."""
    return install_application(
        plan,
        environment=environment,
        probe_path=probe_path,
        support_files=support_files,
        python_requirement=python_requirement,
        prepared_source=prepared,
    )


def _install_application_locked(
    plan: InstallPlan,
    *,
    environment: Mapping[str, str],
    probe_path: Path,
    support_files: Mapping[PurePosixPath, bytes],
    python_requirement: str,
    after_source_acquired: Callable[[PreparedSource], None] | None = None,
    prepared_source: PreparedSource | None = None,
) -> InstallationInspection:
    """Perform verified acquisition, target probing, support publication and commit.

    Applications retain normal-Python control over action ordering and call this
    primitive where their chosen install sequence requires it. Every externally
    visible package mutation is preceded by pending authority and exact source
    validation; any pre-commit error remains resumable as incomplete state.

    :param plan: Read-only plan whose revision/generation will be revalidated.
    :param environment: Captured subprocess environment; no ambient lookup is added.
    :param probe_path: Absolute staged stdlib target probe.
    :param support_files: Exact installation-relative support bytes owned by this generation.
    :param after_source_acquired: Repository-owned setup after source verification, before package mutation.
    :param python_requirement: Application's declared Python compatibility.
    :return: Final ready installation inspection.
    """
    support_files = _current_platform_support(support_files)
    authority = inspect_installation(
        plan.directory, app_id=plan.target.identity.app_id
    )
    inventory = inspect_uv_tools(plan.target.backend, environment=environment)
    distribution_present = plan.target.identity.distribution in inventory
    if distribution_present:
        saved_current = (
            authority.record.current if authority.record is not None else None
        )
        pending_target = (
            authority.record.operation.intended
            if authority.record is not None
            and authority.record.operation is not None
            else None
        )
        saved_owner = (
            saved_current is not None
            and saved_current.identity.distribution
            == plan.target.identity.distribution
            and saved_current.backend == plan.target.backend
        )
        pending_owner = (
            pending_target is not None
            and pending_target.identity == plan.target.identity
            and pending_target.backend == plan.target.backend
        )
        if not saved_owner and not pending_owner:
            raise InstallationError(
                "The selected uv tool name is already owned outside this installation."
            )
    staged = Path(tempfile.mkdtemp(prefix="apprc-install-"))
    os.chmod(staged, 0o700)
    operation_id = plan.operation_id
    revision: str | None = None
    committed = False
    try:
        prepared = prepared_source or prepare_source(plan.target.source, staged)
        _validate_prepared_source(plan, prepared)
        current = begin_operation(plan)
        revision = current.revision
        if revision is None:
            raise InstallationError(
                "Pending installation authority did not produce a revision."
            )
        if after_source_acquired is not None:
            after_source_acquired(prepared)
        _validate_prepared_source(plan, prepared)
        context = OperationContext(
            plan.directory,
            operation_id,
            plan.generation_id,
            plan.target.placement,
        )
        context_path = staged / "operation-context.json"
        context_path.write_bytes(encode_operation_context(context))
        operation = (
            current.record.operation if current.record is not None else None
        )
        package_checkpointed = (
            operation is not None
            and OperationStep.PACKAGE_CHANGED in operation.steps
        )
        prior_current = (
            (authority.record.current or authority.record.last_successful)
            if authority.record is not None
            else None
        )
        acquisition = replace(
            plan.target.source,
            requirement=prepared.requirement,
        )
        probe_source = plan.target.source
        probe_requirement: str | None = prepared.requirement
        probe_digest = prepared.digest
        if (
            plan.kind == "repair"
            and prior_current is not None
            and plan.target.source.matches_observation(prior_current.source)
        ):
            probe_source = prior_current.source
            probe_digest = prior_current.source.digest
            probe_requirement = None
        expected_record_digest = (
            prior_current.distribution_record_digest
            if plan.kind == "repair" and prior_current is not None
            else None
        )
        requires_record_proof = plan.target.source.kind in {
            "release-sdist",
            "wheel",
        } or (
            prepared.digest is not None
            and plan.target.source.kind == "index"
            and re.fullmatch(
                r"git\+https://github\.com/[^/@]+/[^/@]+@[0-9a-f]{40}(?:#subdirectory=[^\\\x00\r\n]+)?",
                plan.target.source.requirement,
            )
            is not None
        )
        if (
            plan.kind == "repair"
            and requires_record_proof
            and prior_current is not None
            and expected_record_digest is None
        ):
            raise InstallationError(
                "Saved archive observation has no installed RECORD fingerprint; repair cannot verify it."
            )
        should_probe_existing = distribution_present and (
            package_checkpointed
            or plan.kind == "repair"
            or prior_current is None
        )
        observed: InstalledSnapshot | None = None
        if should_probe_existing:
            try:
                observed = probe_installed_tool(
                    plan.target.backend,
                    plan.target.identity,
                    probe_source,
                    plan.target.placement,
                    probe_path=probe_path,
                    environment=environment,
                    operation_context=context_path,
                    acquisition_requirement=probe_requirement,
                    acquisition_digest=probe_digest,
                    expected_record_digest=expected_record_digest,
                )
            except (InstallationError, OSError, ValueError) as target_error:
                if prior_current is None:
                    raise InstallationError(
                        "An existing uv tool is not proven to match the pending source; refusing adoption."
                    ) from target_error
                if (
                    requires_record_proof
                    and prior_current.distribution_record_digest is None
                ):
                    raise InstallationError(
                        "Saved archive observation has no installed RECORD fingerprint; refusing fallback adoption."
                    ) from target_error
                try:
                    previous_snapshot = probe_installed_tool(
                        prior_current.backend,
                        prior_current.identity,
                        prior_current.source,
                        prior_current.placement,
                        probe_path=probe_path,
                        environment=environment,
                        expected_record_digest=(
                            prior_current.distribution_record_digest
                        ),
                    )
                except (
                    InstallationError,
                    OSError,
                    ValueError,
                ) as previous_error:
                    raise InstallationError(
                        "The live uv tool matches neither the intended target nor the last successful installation."
                    ) from previous_error
                if (
                    previous_snapshot.identity != prior_current.identity
                    or previous_snapshot.version != prior_current.version
                    or previous_snapshot.backend != prior_current.backend
                    or previous_snapshot.prefix != prior_current.prefix
                    or previous_snapshot.interpreter
                    != prior_current.interpreter
                    or previous_snapshot.commands != prior_current.commands
                ):
                    raise InstallationError(
                        "The live uv tool does not match the last successful installation."
                    ) from target_error
        if observed is None:
            current = record_step(
                plan.directory,
                operation_id=operation_id,
                expected_revision=revision,
                step=OperationStep.PACKAGE_CHANGED,
                observed=None,
            )
            revision = current.revision
            if revision is None:
                raise InstallationError(
                    "Package-mutation checkpoint has no authority revision."
                )
            _validate_prepared_source(plan, prepared)
            install_uv_tool(
                plan.target.backend,
                acquisition,
                environment=environment,
                python_requirement=python_requirement,
                constraints=prepared.constraints,
            )
            if prepared.archive is not None and prepared.digest is not None:
                if _sha256_file(prepared.archive) != prepared.digest:
                    raise InstallationError(
                        "Original package archive changed during installation."
                    )
                if plan.target.source.kind == "wheel":
                    wheel = Path(prepared.requirement)
                    if _sha256_file(wheel) != prepared.digest:
                        raise InstallationError(
                            "Staged wheel changed during installation."
                        )
                elif prepared.source_root is not None:
                    _archive_inputs(
                        prepared.archive, prepared.source_root, extract=False
                    )
            observed = probe_installed_tool(
                plan.target.backend,
                plan.target.identity,
                plan.target.source,
                plan.target.placement,
                probe_path=probe_path,
                environment=environment,
                operation_context=context_path,
                acquisition_requirement=prepared.requirement,
                acquisition_digest=prepared.digest,
                expected_record_digest=(expected_record_digest),
            )
        current = record_step(
            plan.directory,
            operation_id=operation_id,
            expected_revision=revision,
            step=OperationStep.PACKAGE_CHANGED,
            observed=observed,
        )
        revision = current.revision
        if revision is None:
            raise InstallationError(
                "Observed package proof has no authority revision."
            )
        owner_candidates: list[OwnedOutput] = []
        if authority.record is not None:
            owner_candidates.extend(authority.record.owned_outputs)
            for saved in (
                authority.record.current,
                authority.record.last_successful,
            ):
                if saved is not None:
                    owner_candidates.extend(saved.owned_outputs)
        previous_owner = tuple(dict.fromkeys(owner_candidates))
        previous: dict[str, set[str]] = {}
        for item in previous_owner:
            if item.kind == "support" and item.digest is not None:
                previous.setdefault(item.path, set()).add(item.digest)
        support_files = _bind_install_addresses(
            support_files,
            observed,
            plan.directory,
            previous_owner,
        )
        outputs: list[OwnedOutput] = []
        for relative, content in sorted(
            support_files.items(), key=lambda item: str(item[0])
        ):
            if (
                not relative.parts
                or relative.is_absolute()
                or ".." in relative.parts
                or "\\" in str(relative)
                or relative.parts[0] in {"locks", "installation.json"}
            ):
                raise InstallationError(
                    "Generated support path escapes the installation support namespace."
                )
            _validate_support_destination(
                plan.directory.joinpath(*relative.parts),
                relative,
                previous.get(str(relative), ()),
            )
            outputs.append(
                OwnedOutput(
                    "support",
                    str(relative),
                    hashlib.sha256(content).hexdigest(),
                )
            )
        if os.name == "nt":
            subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{plan.target.identity.app_id}"
            outputs.append(OwnedOutput("hkcu", rf"HKCU\{subkey}", None))
        observed = replace(observed, owned_outputs=tuple(outputs))
        current = record_step(
            plan.directory,
            operation_id=operation_id,
            expected_revision=revision,
            step=OperationStep.PACKAGE_CHANGED,
            observed=observed,
        )
        revision = current.revision
        if revision is None:
            raise InstallationError(
                "Package checkpoint has no authority revision."
            )
        current = record_step(
            plan.directory,
            operation_id=operation_id,
            expected_revision=revision,
            step=OperationStep.RESOURCES_READY,
        )
        revision = current.revision
        for relative, content in sorted(
            support_files.items(), key=lambda item: str(item[0])
        ):
            destination = plan.directory.joinpath(*relative.parts)
            _validate_support_destination(
                destination,
                relative,
                previous.get(str(relative), ()),
            )
            write_bytes_atomic(destination, content, private=True)
            if relative in {
                PurePosixPath("launch.sh"),
                PurePosixPath("uninstall.sh"),
            }:
                destination.chmod(0o700)
        snapshot = observed
        if revision is None:
            raise InstallationError(
                "Support checkpoint has no authority revision."
            )
        current = record_step(
            plan.directory,
            operation_id=operation_id,
            expected_revision=revision,
            step=OperationStep.SUPPORT_READY,
        )
        revision = current.revision
        if revision is None:
            raise InstallationError(
                "Support checkpoint has no authority revision."
            )
        _register_windows(
            snapshot,
            plan.directory,
            previous_outputs=previous_owner,
            previous_prefix=(
                authority.record.last_successful.prefix
                if authority.record is not None
                and authority.record.last_successful is not None
                else authority.record.current.prefix
                if authority.record is not None
                and authority.record.current is not None
                else None
            ),
        )
        current = record_step(
            plan.directory,
            operation_id=operation_id,
            expected_revision=revision,
            step=OperationStep.REGISTRATION_READY,
        )
        revision = current.revision
        if revision is None:
            raise InstallationError(
                "Commit checkpoint has no authority revision."
            )
        result = commit_installation(
            plan.directory,
            operation_id=operation_id,
            expected_revision=revision,
            observed=snapshot,
        )
        committed = True
        return result
    except BaseException as error:
        if not committed:
            latest = inspect_installation(
                plan.directory, app_id=plan.target.identity.app_id
            )
            if (
                latest.record is not None
                and latest.record.operation is not None
            ):
                diagnostic = InstallationDiagnostic(
                    "installation-incomplete",
                    str(error),
                    "Resume or repair this recorded operation; do not select another backend or source implicitly.",
                )
                expected_revision = latest.revision or revision
                if expected_revision is None:
                    raise InstallationError(
                        "Cannot recover operation without a current authority revision."
                    )
                try:
                    fail_operation(
                        plan.directory,
                        operation_id=operation_id,
                        expected_revision=expected_revision,
                        diagnostic=diagnostic,
                    )
                except BaseException as journal_error:
                    raise BaseExceptionGroup(
                        "Installation failed and its recovery diagnostic could not be recorded.",
                        [error, journal_error],
                    ) from error
        raise
    finally:
        active_error = sys.exception()
        try:
            if staged.is_symlink():
                raise InstallationError(
                    "Private acquisition staging path was replaced by a link."
                )
            shutil.rmtree(staged)
        except BaseException as cleanup_error:
            if active_error is not None:
                raise BaseExceptionGroup(
                    "Installation failed and private acquisition staging could not be removed.",
                    [active_error, cleanup_error],
                ) from active_error
            raise


def _validate_prepared_source(
    plan: InstallPlan, prepared: PreparedSource
) -> None:
    """Revalidate caller-prepared inputs before binding them to a transaction."""
    source = plan.target.source
    if not (
        prepared.source == source or prepared.source.matches_observation(source)
    ):
        raise InstallationError(
            "Prepared package input does not match the planned source identity."
        )
    if source.kind not in {"editable", "release-sdist", "wheel", "index"}:
        raise InstallationError(
            "Prepared package input has an unsupported source kind."
        )
    validate_requirement(source.requirement)
    forbidden = (
        plan.directory.resolve(strict=False),
        plan.target.backend.tool_dir.resolve(strict=False),
        plan.target.backend.bin_dir.resolve(strict=False),
    )
    if source.kind == "editable":
        project = Path(source.requirement)
        if (
            not project.is_absolute()
            or not (project / "pyproject.toml").is_file()
            or prepared.requirement != source.requirement
            or prepared.digest is not None
        ):
            raise InstallationError(
                "Prepared editable source differs from the planned checkout."
            )
        assert_no_links(project)
    elif source.kind == "wheel":
        archive = prepared.archive
        digest = prepared.digest
        root = prepared.source_root
        wheel = Path(prepared.requirement)
        if (
            archive is None
            or digest is None
            or root is None
            or prepared.project_directory is not None
            or not archive.is_absolute()
            or not archive.is_file()
            or source.digest != digest
            or _sha256_file(archive) != digest
        ):
            raise InstallationError(
                "Prepared wheel differs from selected bytes."
            )
        assert_no_links(archive)
        if any(
            archive.resolve(strict=True).is_relative_to(path)
            for path in forbidden
        ):
            raise InstallationError(
                "Prepared wheel must remain outside installation targets."
            )
        if not root.is_absolute():
            raise InstallationError(
                "Prepared wheel has invalid private staging."
            )
        assert_no_links(archive.parent)
        _assert_private_staging(archive.parent)
        expected_root = archive.parent / f"apprc-source-{digest}"
        if root != expected_root or not root.is_dir():
            raise InstallationError(
                "Prepared wheel has invalid private staging."
            )
        assert_no_links(root)
        assert_no_links(wheel)
        _assert_private_staging(root)
        if (
            wheel.parent != root
            or wheel.name != archive.name
            or not wheel.is_file()
            or _sha256_file(wheel) != digest
            or root.resolve(strict=True) != expected_root.resolve(strict=True)
            or wheel.resolve(strict=True)
            != expected_root.resolve(strict=True) / wheel.name
        ):
            raise InstallationError("Prepared wheel origin is invalid.")
        _validate_content_addressed_origin(source, digest, wheel)
        if any(
            wheel.resolve(strict=True).is_relative_to(path)
            for path in forbidden
        ):
            raise InstallationError(
                "Prepared wheel must remain outside installation targets."
            )
    elif source.kind == "release-sdist" or (
        source.kind == "index"
        and prepared.archive is not None
        and re.fullmatch(
            r"git\+https://github\.com/[^/@]+/[^/@]+@[0-9a-f]{40}(?:#subdirectory=[^\\\x00\r\n]+)?",
            source.requirement,
        )
    ):
        archive = prepared.archive
        if (
            archive is None
            or not archive.is_absolute()
            or not archive.is_file()
            or prepared.digest is None
            or re.fullmatch(r"[0-9a-f]{64}", prepared.digest) is None
            or source.digest is not None
            and prepared.digest != source.digest
        ):
            raise InstallationError(
                "Prepared archive has no valid acquisition digest."
            )
        assert_no_links(archive)
        if _sha256_file(archive) != prepared.digest:
            raise InstallationError(
                "Prepared original archive differs from its acquired digest."
            )
        assert_no_links(archive.parent)
        _assert_private_staging(archive.parent)
        resolved_archive = archive.resolve(strict=True)
        if any(resolved_archive.is_relative_to(path) for path in forbidden):
            raise InstallationError(
                "Prepared archive must remain outside installation targets."
            )
        root = prepared.source_root
        project = prepared.project_directory
        if root is None or not root.is_absolute() or project is None:
            raise InstallationError(
                "Prepared project does not match its content-addressed source identity."
            )
        staging = root.parent
        assert_no_links(staging)
        _assert_private_staging(staging)
        expected_root, expected_project = _materialized_source_paths(
            source, prepared.digest, staging
        )
        if (
            root != expected_root
            or project != expected_project
            or prepared.requirement != str(expected_project)
            or not root.is_dir()
            or not project.is_dir()
        ):
            raise InstallationError(
                "Prepared project does not match its content-addressed source identity."
            )
        assert_no_links(root)
        _assert_private_staging(root)
        if (
            root.resolve(strict=True) != expected_root
            or project.resolve(strict=True) != expected_project
            or _selected_project(root, _source_subdirectory(source)) != project
        ):
            raise InstallationError(
                "Prepared project does not match the selected source directory."
            )
        _archive_inputs(archive, root, extract=False)
        if any(
            root.resolve(strict=True).is_relative_to(path) for path in forbidden
        ):
            raise InstallationError(
                "Materialized source tree must remain outside installation targets."
            )
    else:
        if prepared.requirement != source.requirement:
            raise InstallationError(
                "Prepared backend requirement differs from the planned source."
            )
        if prepared.digest is not None and prepared.digest != source.digest:
            raise InstallationError(
                "Prepared package digest differs from selected source."
            )
    if source.runtime_requirements:
        constraints = prepared.constraints
        if (
            constraints is None
            or not constraints.is_absolute()
            or not constraints.is_file()
        ):
            raise InstallationError(
                "Prepared runtime constraints are missing or invalid."
            )
        _assert_private_staging(constraints.parent)
        assert_no_links(constraints)
        expected = "".join(
            requirement + "\n" for requirement in source.runtime_requirements
        )
        if constraints.read_text(encoding="utf-8") != expected:
            raise InstallationError(
                "Prepared runtime constraints differ from the planned source."
            )
        if any(
            constraints.resolve(strict=True).is_relative_to(path)
            for path in forbidden
        ):
            raise InstallationError(
                "Prepared runtime constraints must remain outside installation targets."
            )
    elif prepared.constraints is not None:
        raise InstallationError(
            "Unexpected runtime constraints were supplied for this source."
        )


def _assert_private_staging(directory: Path) -> None:
    """Reject caller-staged backend inputs exposed to another local user."""
    if os.name == "nt":
        if not windows_acl_is_private(directory):
            raise InstallationError(
                "Prepared package staging directory does not have a private Windows ACL."
            )
    elif stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise InstallationError(
            "Prepared package staging directory must be private."
        )


def _validate_support_destination(
    destination: Path,
    relative: PurePosixPath,
    recorded_digests: Collection[str],
) -> None:
    """Require saved digest authority for any existing publication target."""
    assert_no_links(destination)
    if destination.exists() or destination.is_symlink():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or hashlib.sha256(destination.read_bytes()).hexdigest()
            not in recorded_digests
        ):
            raise InstallationError(
                f"Refusing to replace unowned support output: {relative}."
            )


def _current_platform_support(
    support_files: Mapping[PurePosixPath, bytes],
) -> dict[PurePosixPath, bytes]:
    """Keep only frontends executable on this installation's current platform."""
    windows_frontends = {
        PurePosixPath("launch.cmd"),
        PurePosixPath("launch.ps1"),
        PurePosixPath("uninstall.cmd"),
        PurePosixPath("uninstall.ps1"),
    }
    posix_frontends = {
        PurePosixPath("launch.sh"),
        PurePosixPath("uninstall.sh"),
    }
    excluded = posix_frontends if os.name == "nt" else windows_frontends
    return {
        path: content
        for path, content in support_files.items()
        if path not in excluded
    }


def _bind_install_addresses(
    support_files: Mapping[PurePosixPath, bytes],
    observed: InstalledSnapshot,
    directory: Path,
    previous_outputs: tuple[OwnedOutput, ...],
) -> dict[PurePosixPath, bytes]:
    """Bind machine-specific executable addresses before journaling support digests."""
    files = dict(support_files)
    command_marker = PurePosixPath("launch-command.json")
    if command_marker not in files and not any(
        b"__APPRC_BASE_PYTHON__" in content
        or b"__APPRC_COMMAND_PATH__" in content
        for content in files.values()
    ):
        return files
    uninstall_path = PurePosixPath("uninstall.py")
    uninstall = directory / uninstall_path
    expected = {
        item.digest
        for item in previous_outputs
        if item.kind == "support"
        and item.path == str(uninstall_path)
        and item.digest is not None
    }
    base_python = None
    if uninstall.is_file() and not uninstall.is_symlink():
        existing = uninstall.read_bytes()
        if hashlib.sha256(existing).hexdigest() in expected:
            for line in existing.decode("utf-8").splitlines():
                if line.startswith("BASE_PYTHON = "):
                    try:
                        candidate = Path(
                            json.loads(line.partition("=")[2].strip())
                        )
                        base_python = external_base_python(
                            observed.prefix,
                            executable=candidate,
                        )
                    except (
                        OSError,
                        ValueError,
                        InstallationError,
                        json.JSONDecodeError,
                        subprocess.CalledProcessError,
                    ):
                        pass
                    break
    if base_python is None:
        base_python = external_base_python(observed.prefix)
    try:
        command_data = files[command_marker]
        command_name = json.loads(command_data.decode("utf-8"))["command"]
        command_index = observed.identity.commands.index(command_name)
        command_path = observed.commands[command_index]
    except (
        UnicodeDecodeError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
    ) as error:
        raise InstallationError(
            "Recorded launcher command is not present in the live package probe."
        ) from error
    if not command_path.is_absolute() or not command_path.is_file():
        raise InstallationError("Recorded launcher executable is unavailable.")
    bound = {}
    for path, content in files.items():
        if path == uninstall_path:
            content = content.replace(
                b'"__APPRC_BASE_PYTHON__"',
                json.dumps(str(base_python), ensure_ascii=True).encode("ascii"),
            )
        elif path.name in {
            "launch.sh",
            "launch.ps1",
            "launch.cmd",
            "uninstall.sh",
            "uninstall.ps1",
            "uninstall.cmd",
        }:
            if path.suffix == ".sh":
                command_value = shlex.quote(str(command_path))
                python_value = shlex.quote(str(base_python))
            elif path.suffix == ".ps1":
                command_value = "'" + str(command_path).replace("'", "''") + "'"
                python_value = "'" + str(base_python).replace("'", "''") + "'"
            else:
                command_value = (
                    '"'
                    + str(command_path).replace("%", "%%").replace('"', '""')
                    + '"'
                )
                python_value = (
                    '"'
                    + str(base_python).replace("%", "%%").replace('"', '""')
                    + '"'
                )
            content = content.replace(
                b"__APPRC_COMMAND_PATH__", command_value.encode("utf-8")
            )
            content = content.replace(
                b"__APPRC_BASE_PYTHON__", python_value.encode("utf-8")
            )
        bound[path] = content
    return bound


def _register_windows(
    snapshot: InstalledSnapshot,
    directory: Path,
    *,
    previous_outputs: tuple[OwnedOutput, ...],
    previous_prefix: Path | None,
) -> OwnedOutput | None:
    """Publish only an exactly owned current-user uninstall registration."""
    if os.name != "nt":
        return None
    import winreg

    identity = snapshot.identity
    subkey = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{identity.app_id}"
    output = OwnedOutput("hkcu", rf"HKCU\{subkey}", None)
    previously_owned = output in previous_outputs
    controller = directory / "uninstall.cmd"
    original_values: (
        dict[str, tuple[str | int | bytes | list[str] | None, int]] | None
    ) = None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            if not previously_owned:
                raise InstallationError(
                    "Refusing to claim an unowned current-user uninstall key."
                )
            count = winreg.QueryInfoKey(key)[1]
            values: dict[str, str | int | bytes | list[str] | None] = {}
            original_values = {}
            for index in range(count):
                name, value, kind = winreg.EnumValue(key, index)
                values[name] = value
                original_values[name] = (value, kind)
            allowed_prefixes = {str(snapshot.prefix)}
            if previous_prefix is not None:
                allowed_prefixes.add(str(previous_prefix))
            expected_values = {
                "DisplayName": {
                    identity.app_id,
                    f"{identity.app_id} (data retained)",
                },
                "UninstallString": {f'"{controller}"'},
                "InstallLocation": allowed_prefixes,
            }
            if not values.keys() <= expected_values.keys() or any(
                value not in expected_values[name]
                for name, value in values.items()
            ):
                raise InstallationError(
                    "Uninstall registration changed outside recorded ownership."
                )
    except FileNotFoundError:
        if previously_owned:
            raise InstallationError(
                "Previously owned uninstall registration is missing."
            )
    intended_values = {
        "DisplayName": identity.app_id,
        "UninstallString": f'"{controller}"',
        "InstallLocation": str(snapshot.prefix),
    }
    attempted: list[str] = []
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            count = winreg.QueryInfoKey(key)[1]
            current_values = {
                name: (value, kind)
                for name, value, kind in (
                    winreg.EnumValue(key, index) for index in range(count)
                )
            }
            if current_values != (original_values or {}):
                raise InstallationError(
                    "Uninstall registration changed during publication."
                )
            for name, value in intended_values.items():
                attempted.append(name)
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except BaseException as error:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
            ) as key:
                for name in attempted:
                    try:
                        value, kind = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    if value != intended_values[name] or kind != winreg.REG_SZ:
                        raise InstallationError(
                            f"Uninstall registration changed during rollback: {name}."
                        )
                    if original_values is not None and name in original_values:
                        old_value, old_kind = original_values[name]
                        winreg.SetValueEx(key, name, 0, old_kind, old_value)
                    else:
                        winreg.DeleteValue(key, name)
        except BaseException as rollback_error:
            raise BaseExceptionGroup(
                "Windows registration update and rollback both failed.",
                [error, rollback_error],
            ) from error
        raise
    return output
