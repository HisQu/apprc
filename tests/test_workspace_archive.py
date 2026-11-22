from __future__ import annotations

import io
import os
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import pytest

import apprc as rc
from apprc.services import workspaces as workspace_service
from apprc.services.workspaces import WorkspaceManager
from apprc.user_files.env_files.secrets import SecretFileStatus
from apprc.user_files.workspace_roots.archive import (
    ARCHIVE_SUFFIX,
    WorkspaceArchiveProgress,
    archive_workspace_directory,
    extract_workspace_archive,
    is_workspace_archive_path,
    workspace_archive_default_path,
    workspace_root_name_from_archive,
)
from apprc.user_files.workspace_roots.archive import (
    archive_workspace_directory as archive_directory,
)
from apprc.user_files.workspace_roots.archive import (
    extract_workspace_archive as extract_archive,
)
from apprc.user_files.workspace_roots.registry import (
    record_archived_workspace,
    repoint_workspace,
)


@pytest.fixture
def workspace_manager(tmp_path: Path) -> WorkspaceManager:
    app = rc.AppRC(
        app_id="workspace-archive",
        paths=rc.Paths(config=True),
        layout=rc.Layout.single_root(tmp_path / "app"),
        workspaces=rc.Workspaces(),
    )
    return app.workspaces(environment={})


def test_workspace_archive_helpers_name_paths(tmp_path: Path) -> None:
    workspace_root = tmp_path / "alpha"

    assert is_workspace_archive_path(f"alpha{ARCHIVE_SUFFIX}")
    assert workspace_archive_default_path(workspace_root) == (
        tmp_path / f"alpha{ARCHIVE_SUFFIX}"
    )
    assert (
        workspace_root_name_from_archive(tmp_path / f"alpha{ARCHIVE_SUFFIX}")
        == "alpha"
    )


def test_archive_directory_round_trips_with_progress(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "payload.txt").write_text("demo", encoding="utf-8")
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    progress: list[WorkspaceArchiveProgress] = []

    written = archive_workspace_directory(
        source_root=source,
        archive_path=archive,
        progress=progress.append,
    )
    restored = extract_workspace_archive(
        archive_path=written,
        destination_root=tmp_path / "restored",
        progress=progress.append,
    )

    assert written == archive.resolve()
    assert (restored / "nested" / "payload.txt").read_text(
        encoding="utf-8"
    ) == "demo"
    assert progress
    assert progress[-1].completed == progress[-1].total


def test_archive_directory_atomically_replaces_existing_archive(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    archive.write_text("old", encoding="utf-8")

    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive_directory(source_root=source, archive_path=archive)
    restored = extract_archive(
        archive_path=archive,
        destination_root=tmp_path / "restored",
    )

    assert (restored / "payload.txt").read_text(encoding="utf-8") == "new"
    assert not (tmp_path / f".source{ARCHIVE_SUFFIX}.tmp").exists()


def test_archive_directory_rejects_symlinks_before_writing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    temp_archive = tmp_path / f".source{ARCHIVE_SUFFIX}.tmp"
    temp_archive.write_text("stale", encoding="utf-8")
    (source / "payload.txt").write_text("demo", encoding="utf-8")
    try:
        (source / "linked-payload.txt").symlink_to("payload.txt")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable on this platform: {exc}")

    with pytest.raises(ValueError, match="may not contain links"):
        archive_directory(source_root=source, archive_path=archive)

    assert not archive.exists()
    assert not temp_archive.exists()


def test_archive_directory_rejects_hardlinks_before_writing(
    tmp_path: Path,
) -> None:
    if not hasattr(os, "link"):
        pytest.skip("hardlinks are unavailable on this platform")
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    payload = source / "payload.txt"
    payload.write_text("demo", encoding="utf-8")
    try:
        os.link(payload, source / "linked-payload.txt")
    except OSError as exc:
        pytest.skip(f"hardlinks are unavailable on this filesystem: {exc}")

    with pytest.raises(ValueError, match="may not contain links"):
        archive_directory(source_root=source, archive_path=archive)

    assert not archive.exists()
    assert not (tmp_path / f".source{ARCHIVE_SUFFIX}.tmp").exists()


def test_extract_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / f"evil{ARCHIVE_SUFFIX}"
    info = tarfile.TarInfo("../evil.txt")
    payload = b"nope"
    info.size = len(payload)
    with tarfile.open(archive, "w:xz", preset=9) as tar:
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="escapes destination"):
        extract_archive(
            archive_path=archive,
            destination_root=tmp_path / "restored",
        )

    assert not (tmp_path / "evil.txt").exists()


def test_extract_archive_validates_all_members_before_writing(
    tmp_path: Path,
) -> None:
    archive = tmp_path / f"mixed{ARCHIVE_SUFFIX}"
    good = tarfile.TarInfo("good.txt")
    good_payload = b"ok"
    good.size = len(good_payload)
    evil = tarfile.TarInfo("../evil.txt")
    evil_payload = b"nope"
    evil.size = len(evil_payload)
    with tarfile.open(archive, "w:xz", preset=9) as tar:
        tar.addfile(good, io.BytesIO(good_payload))
        tar.addfile(evil, io.BytesIO(evil_payload))

    with pytest.raises(ValueError, match="escapes destination"):
        extract_archive(
            archive_path=archive,
            destination_root=tmp_path / "restored",
        )

    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "evil.txt").exists()
    assert not list(tmp_path.glob(".restored.apprc-extract-*"))


def test_extract_archive_rejects_non_empty_destination_by_default(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive = archive_directory(
        source_root=source,
        archive_path=tmp_path / f"source{ARCHIVE_SUFFIX}",
    )
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "payload.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError, match="not empty"):
        extract_archive(
            archive_path=archive,
            destination_root=destination,
        )

    assert (destination / "payload.txt").read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".restored.apprc-extract-*"))


def test_extract_archive_replace_existing_swaps_after_staged_extract(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive = archive_directory(
        source_root=source,
        archive_path=tmp_path / f"source{ARCHIVE_SUFFIX}",
    )
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "payload.txt").write_text("old", encoding="utf-8")
    (destination / "old-only.txt").write_text("remove", encoding="utf-8")

    restored = extract_archive(
        archive_path=archive,
        destination_root=destination,
        replace_existing=True,
    )

    assert restored == destination.resolve()
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "new"
    assert not (destination / "old-only.txt").exists()
    assert not list(tmp_path.glob(".restored.apprc-extract-*"))
    assert not list(tmp_path.glob(".restored.apprc-backup-*"))


def test_extract_archive_rolls_back_new_destination_when_commit_fails(
    tmp_path: Path,
) -> None:
    """A registry commit failure removes the uncommitted extraction.

    :param tmp_path: Isolated archive and destination parent.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive = archive_directory(
        source_root=source,
        archive_path=tmp_path / f"source{ARCHIVE_SUFFIX}",
    )
    destination = tmp_path / "restored"

    def fail_commit(_root: Path) -> None:
        raise OSError("registry unavailable")

    with pytest.raises(OSError, match="registry unavailable"):
        extract_archive(
            archive_path=archive,
            destination_root=destination,
            after_install=fail_commit,
        )

    assert not destination.exists()


def test_extract_archive_restores_replaced_destination_when_commit_fails(
    tmp_path: Path,
) -> None:
    """A registry commit failure restores prior destination contents.

    :param tmp_path: Isolated archive and destination parent.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("new", encoding="utf-8")
    archive = archive_directory(
        source_root=source,
        archive_path=tmp_path / f"source{ARCHIVE_SUFFIX}",
    )
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "payload.txt").write_text("old", encoding="utf-8")

    def fail_commit(_root: Path) -> None:
        raise OSError("registry unavailable")

    with pytest.raises(OSError, match="registry unavailable"):
        extract_archive(
            archive_path=archive,
            destination_root=destination,
            replace_existing=True,
            after_install=fail_commit,
        )

    assert (destination / "payload.txt").read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".restored.apprc-backup-*"))


def test_workspace_archive_excludes_workspace_secret_companion(
    tmp_path: Path,
) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "config.env").write_text("VALUE=visible\n", encoding="utf-8")
    (source / "apprc.workspace.secret.env").write_text(
        "TOKEN=private\n",
        encoding="utf-8",
    )
    archive = archive_directory(
        source_root=source,
        archive_path=tmp_path / f"workspace{ARCHIVE_SUFFIX}",
    )

    restored = extract_archive(
        archive_path=archive,
        destination_root=tmp_path / "restored",
    )

    assert (restored / "config.env").read_text(
        encoding="utf-8"
    ) == "VALUE=visible\n"
    assert not (restored / "apprc.workspace.secret.env").exists()


@pytest.mark.parametrize("operation", ["archive", "unregister"])
def test_workspace_operation_rejects_repoint_while_waiting_for_lock(
    operation: Literal["archive", "unregister"],
    workspace_manager: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    replacement = tmp_path / "replacement"
    archive_path = tmp_path / f"source{ARCHIVE_SUFFIX}"
    workspace_manager.register_workspace("alpha", source)
    replacement.mkdir()
    registry_path = workspace_manager.registry_path()
    real_write_lock = workspace_manager._write_lock

    @contextmanager
    def repoint_before_lock(
        *roots: Path, private_directories: tuple[Path, ...] = ()
    ) -> Iterator[None]:
        repoint_workspace(name="alpha", root=replacement, path=registry_path)
        with real_write_lock(*roots, private_directories=private_directories):
            yield

    monkeypatch.setattr(workspace_manager, "_write_lock", repoint_before_lock)

    with pytest.raises(ValueError, match="changed while waiting"):
        if operation == "archive":
            workspace_manager.archive_workspace("alpha", archive_path)
        else:
            workspace_manager.remove_workspace("alpha")

    assert workspace_manager.registry().selected("alpha").root == replacement
    assert not workspace_manager.registry().archived_workspaces
    assert not archive_path.exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_restore_rejects_archive_row_replaced_while_waiting_for_lock(
    explicit: bool,
    workspace_manager: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    refreshed_archive = tmp_path / f"refreshed{ARCHIVE_SUFFIX}"
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "payload.txt").write_text("keep", encoding="utf-8")
    workspace_manager.register_workspace("alpha", source)
    workspace_manager.archive_workspace("alpha", archive)
    workspace_manager.remove_workspace("alpha")
    registry_path = workspace_manager.registry_path()
    real_write_lock = workspace_manager._write_lock

    @contextmanager
    def refresh_archive_before_lock(
        *roots: Path, private_directories: tuple[Path, ...] = ()
    ) -> Iterator[None]:
        record_archived_workspace(
            name="alpha",
            archive=refreshed_archive,
            source_root=source,
            path=registry_path,
        )
        with real_write_lock(*roots, private_directories=private_directories):
            yield

    monkeypatch.setattr(
        workspace_manager, "_write_lock", refresh_archive_before_lock
    )

    with pytest.raises(ValueError, match="changed while waiting"):
        workspace_manager.restore_workspace(
            "renamed" if explicit else "alpha",
            destination,
            archive=archive if explicit else None,
            archived_name="alpha" if explicit else None,
            replace_existing=True,
        )

    registry = workspace_manager.registry()
    assert registry.archived_workspaces["alpha"].archive == refreshed_archive
    assert not registry.workspaces
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("operation", ["register", "restore"])
@pytest.mark.parametrize("raises_error", [False, True])
def test_workspace_commit_survives_optional_private_companion_failure(
    operation: Literal["register", "restore"],
    raises_error: bool,
    workspace_manager: WorkspaceManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = tmp_path / "target"
    archive = tmp_path / f"source{ARCHIVE_SUFFIX}"
    if operation == "restore":
        source = tmp_path / "source"
        workspace_manager.register_workspace("alpha", source)
        (source / "payload.txt").write_text("archived", encoding="utf-8")
        workspace_manager.archive_workspace("alpha", archive)
        workspace_manager.remove_workspace("alpha")
        root.mkdir()
        (root / "payload.txt").write_text("previous", encoding="utf-8")

    def unavailable(path: Path) -> SecretFileStatus:
        if raises_error:
            raise PermissionError("Permission denied")
        return SecretFileStatus(
            path, False, "Directory is not private", "parent_not_private"
        )

    monkeypatch.setattr(workspace_service, "ensure_secret_file", unavailable)

    if operation == "restore":
        assert (
            workspace_manager.restore_workspace(
                "alpha", root, replace_existing=True
            )
            == root
        )
        assert (root / "payload.txt").read_text(encoding="utf-8") == "archived"
    else:
        registry = workspace_manager.register_workspace("alpha", root)
        assert registry.selected("alpha").root == root

    assert workspace_manager.registry().selected("alpha").root == root
    assert (root / workspace_manager.spec.workspace_dotenv_filename).is_file()
    assert not workspace_manager.registry().archived_workspaces
    assert "secret permissions repair" in caplog.text
    assert str(root) in caplog.text
