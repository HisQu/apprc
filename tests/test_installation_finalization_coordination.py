"""Generation locking at editable checkout and resource retirement boundaries."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
import shutil
from contextlib import ExitStack, contextmanager
from multiprocessing.connection import _ConnectionBase
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Callable, Iterator

import pytest

from apprc.definition.installation import (
    InstallationWriteAuthority,
    OperationContext,
)
from apprc.distribution.runtime import _process_waiter
from apprc.distribution.runtime.uninstall_handoff import (
    _stage_repository_finalizer,
)
from apprc.user_files.app_home.writes import (
    managed_lock_path,
    managed_write_lock,
)
from apprc.user_files.installation.coordination import (
    installation_lock,
    write_record,
)
from apprc.user_files.installation.discovery import inspect_installation
from apprc.user_files.installation.inventory import tree_revision
from tests.support_installation import installation_record, owned_child_process

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="POSIX installation finalization fixtures"
)


def _run_repository_leaf(
    proof: Path, pid: int, token: str, channel: _ConnectionBase
) -> None:
    spec = importlib.util.spec_from_file_location(
        "test_repository_leaf", proof.parent.parent / "repository_finalizer.py"
    )
    assert spec is not None and spec.loader is not None
    leaf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(leaf)
    original_loader = leaf._load_peer

    def load(name: str):
        module = original_loader(name)
        if name == "_namespace_lock":
            original_lock = module.FileLock
            announced = False

            def factory(*args: object, **kwargs: object):
                nonlocal announced
                if not announced:
                    announced = True
                    channel.send("lock-attempt")
                return original_lock(*args, **kwargs)

            module.FileLock = factory
        return module

    setattr(leaf, "_load_peer", load)
    try:
        leaf.finalize_repository(proof, pid, token)
    except ValueError as error:
        channel.send(str(error))
    else:
        channel.send("removed")
    channel.close()


def _stale_resource_writer(
    root: Path,
    authority: InstallationWriteAuthority,
    channel: _ConnectionBase,
) -> None:
    from apprc.user_files.installation import validation

    original_validation = validation.validate_snapshot
    first = True

    def validated(*args: object, **kwargs: object) -> None:
        nonlocal first
        original_validation(*args, **kwargs)  # pyright: ignore[reportArgumentType]
        if first:
            first = False
            channel.send("initial-snapshot-validated")
            channel.recv()

    validation.validate_snapshot = validated
    try:
        with managed_write_lock(root, authority=authority):
            (root / "should-not-exist").write_text("stale write")
    except ValueError as error:
        channel.send(str(error))
    else:
        channel.send("wrote")
    channel.close()


@contextmanager
def _child(
    target: Callable[..., None], args: tuple[object, ...]
) -> Iterator[tuple[BaseProcess, _ConnectionBase]]:
    # > Child targets open their own handles and cannot inherit a held lock.
    context = multiprocessing.get_context("spawn")
    parent_channel, child_channel = context.Pipe()
    process = context.Process(target=target, args=(*args, child_channel))
    process.start()
    child_channel.close()
    try:
        yield process, parent_channel
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        assert not process.is_alive()
        parent_channel.close()


def _finalization_fixture(tmp_path: Path) -> tuple[Path, Path, Path, int, str]:
    directory = tmp_path / "installation"
    with installation_lock(directory):
        pass
    repository = tmp_path / "checkout"
    repository.mkdir()
    (repository / "local-work").write_text("keep if registration won")
    staging = tmp_path / "staging"
    recovery = staging / "recovery"
    staging.mkdir(mode=0o700)
    recovery.mkdir(parents=True, mode=0o700)
    _stage_repository_finalizer(staging)
    proof = recovery / "repository.json"
    proof.write_text(
        json.dumps(
            {
                "directory": str(directory),
                "app_id": "coordination-fixture",
                "generation_id": "00000000-0000-0000-0000-000000000000",
                "repository": str(repository),
                "revision": tree_revision(repository),
            }
        )
    )
    with owned_child_process() as process:
        token = _process_waiter.process_start_token(process.pid)
        assert process.stdin is not None
        process.stdin.write("exit\n")
        process.stdin.flush()
        process.wait(timeout=5)
        pid = process.pid
    return directory, repository, proof, pid, token


def test_repository_leaf_preserves_registration_that_wins_namespace_lock(
    tmp_path: Path,
) -> None:
    directory, repository, proof, pid, token = _finalization_fixture(tmp_path)
    with ExitStack() as stack:
        with installation_lock(directory):
            process, channel = stack.enter_context(
                _child(_run_repository_leaf, (proof, pid, token))
            )
            assert channel.poll(5) and channel.recv() == "lock-attempt"
            write_record(
                directory, installation_record(), expected_revision=None
            )
            # > The helper is blocked by the registration's physical lock.
            if channel.poll(0.1):
                pytest.fail(
                    f"Finalizer completed while registration held its lock: {channel.recv()!r}"
                )
        assert channel.poll(5) and "new installation" in channel.recv()
        process.join(timeout=5)
        assert process.exitcode == 0
    assert (repository / "local-work").read_text() == "keep if registration won"
    assert (directory / "installation.json").exists()


def test_waiting_stale_writer_cannot_recreate_retired_resource_parents(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "installation"
    root = tmp_path / "single-root" / "state"
    root.mkdir(parents=True)
    with installation_lock(directory):
        write_record(directory, installation_record(), expected_revision=None)
    inspection = inspect_installation(directory, app_id="coordination-fixture")
    authority = InstallationWriteAuthority(
        "coordination-fixture", inspection.snapshot
    )
    with _child(_stale_resource_writer, (root, authority)) as (
        process,
        channel,
    ):
        assert (
            channel.poll(5) and channel.recv() == "initial-snapshot-validated"
        )
        with installation_lock(directory):
            replacement = installation_record()
            write_record(
                directory, replacement, expected_revision=inspection.revision
            )
            shutil.rmtree(root.parent)
            channel.send("resume")
        assert channel.poll(5) and "generation changed" in channel.recv()
        process.join(timeout=5)
        assert process.exitcode == 0
    assert not root.parent.exists()
    assert not managed_lock_path(root).exists()


def _initialize_pending_resources(
    directory: Path, context: OperationContext, channel: _ConnectionBase
) -> None:
    from apprc import AppRC, Paths
    from apprc.services.installation import InstallationManager

    declaration = AppRC(app_id="coordination-fixture", paths=Paths(cache=True))
    manager = InstallationManager(declaration.schema, directory=directory)
    report = manager.initialize(context=context)
    channel.send(tuple(str(path) for path in report.paths))
    channel.close()


def test_operation_probe_initializes_resources_while_parent_owns_namespace(
    tmp_path: Path,
) -> None:
    from apprc.definition.installation import (
        InstallationPlacement,
        ProjectSnapshot,
        RuntimeSelection,
        RuntimeSlot,
    )
    from apprc.definition.paths import Layout
    from apprc.user_files.installation.operations import (
        begin_operation,
        plan_install,
    )
    from uuid import uuid4

    directory = tmp_path / "installation"
    root = tmp_path / "cache"
    placement = InstallationPlacement(
        Layout.native(), cache_dir=root, capabilities=frozenset({"cache"})
    )
    plan = plan_install(
        installation_record().identity,
        RuntimeSlot(
            uuid4(),
            ProjectSnapshot("a" * 64, "b" * 64, "c" * 40),
            RuntimeSelection("3.14"),
        ),
        placement,
        inspection=inspect_installation(
            directory, app_id="coordination-fixture"
        ),
    )
    with installation_lock(directory):
        begin_operation(plan)
        context = OperationContext(
            directory, plan.operation_id, plan.generation_id, placement
        )
        with _child(_initialize_pending_resources, (directory, context)) as (
            process,
            channel,
        ):
            assert channel.poll(5), (
                "Resource probe tried to reacquire its parent's namespace lock"
            )
            assert channel.recv() == (str(root),)
            process.join(timeout=5)
            assert process.exitcode == 0
    assert (root / ".apprc-owner.json").is_file()
